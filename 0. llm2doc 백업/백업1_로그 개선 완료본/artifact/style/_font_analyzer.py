import os
import cv2
import numpy as np
import matplotlib.pyplot as plt

from threading import Lock
from dataclasses import dataclass
from beartype import beartype
from typing import Sequence, Self
from PIL import Image, ImageFont, ImageDraw
from collections import OrderedDict
from fontTools.ttLib import TTFont


FONT_PADDING = 8


def display_fonts(original: np.ndarray, images: Sequence[np.ndarray], costs: np.ndarray, which: int):
    total_images = len(images) + 1  # +1 to include the original target mask

    # Calculate grid dimensions dynamically (aiming for a roughly square grid)
    cols = int(np.ceil(np.sqrt(total_images)))
    rows = int(np.ceil(total_images / cols))

    # Create the plot
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.5, rows * 2.5))

    # Flatten axes array for easy 1D iteration, handling the case where total_images == 1
    if total_images > 1:
        axes = axes.flatten()
    else:
        axes = [axes]

    # 1. Plot the original target mask first
    axes[0].imshow(original, cmap="gray")
    axes[0].set_title("Target Mask", fontweight="bold")
    axes[0].axis("off")

    # 2. Plot all the rendered fonts
    for i in range(len(images)):
        ax = axes[i + 1]
        ax.imshow(images[i], cmap="gray")

        # Highlight the best match
        if i == which:
            ax.set_title(f"Best: {costs[i]:.1f}", color="red", fontweight="bold")
        else:
            ax.set_title(f"Cost: {costs[i]:.1f}")

        ax.axis("off")

    # 3. Hide any empty subplots in the grid
    for j in range(total_images, len(axes)):
        axes[j].axis("off")

    plt.tight_layout()
    plt.show()


def render_character_keep_aspect(
    char: str, font: ImageFont.FreeTypeFont, target_height: int, target_width: int
) -> tuple[np.ndarray, float | None]:
    left, top, right, bottom = font.getbbox(char)

    base_width = int(right - left)
    base_height = int(bottom - top)

    if base_width <= 0 or base_height <= 0:
        return np.zeros((target_height, target_width), dtype=np.uint8), None

    safe_width = base_width + (FONT_PADDING * 2)
    safe_height = base_height + (FONT_PADDING * 2)

    img = Image.new("L", (safe_width, safe_height), 0)
    draw = ImageDraw.Draw(img)

    draw.text((int(-left) + FONT_PADDING, int(-top) + FONT_PADDING), char, font=font, fill=255)

    tight_bbox = img.getbbox()

    if tight_bbox is None:
        return np.zeros((target_height, target_width), dtype=np.uint8), None

    cropped_img = img.crop(tight_bbox)
    crop_w, crop_h = cropped_img.size

    cropped_arr = np.asarray(cropped_img)

    scale = min(target_width / crop_w, target_height / crop_h)

    tx = (target_width - (crop_w * scale)) / 2.0
    ty = (target_height - (crop_h * scale)) / 2.0

    M = np.array([[scale, 0.0, tx], [0.0, scale, ty]], dtype=np.float32)

    final_arr = cv2.warpAffine(
        cropped_arr,
        M,
        (target_width, target_height),
        flags=cv2.INTER_AREA,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0,),
    )

    scaled_font_size = font.size * scale

    return final_arr, scaled_font_size


def render_character_stretch(
    char: str, font: ImageFont.FreeTypeFont, target_height: int, target_width: int
) -> tuple[np.ndarray, float | None]:
    left, top, right, bottom = font.getbbox(char)

    base_width = int(right - left)
    base_height = int(bottom - top)

    if base_width <= 0 or base_height <= 0:
        return np.zeros((target_height, target_width), dtype=np.uint8), None

    safe_width = base_width + (FONT_PADDING * 2)
    safe_height = base_height + (FONT_PADDING * 2)

    img = Image.new("L", (safe_width, safe_height), 0)
    draw = ImageDraw.Draw(img)

    draw.text((int(-left) + FONT_PADDING, int(-top) + FONT_PADDING), char, font=font, fill=255)

    tight_bbox = img.getbbox()

    if tight_bbox is None:
        return np.zeros((target_height, target_width), dtype=np.uint8), None

    cropped_img = img.crop(tight_bbox)
    crop_w, crop_h = cropped_img.size
    cropped_arr = np.asarray(cropped_img)

    final_arr = cv2.resize(cropped_arr, (target_width, target_height), interpolation=cv2.INTER_AREA)

    scale_y = target_height / crop_h
    scaled_font_size = font.size * scale_y

    return final_arr, scaled_font_size


@beartype
@dataclass
class FontAnalysisResult:
    cost: np.ndarray
    """L2 difference between font and actual image."""

    font_size: np.ndarray
    """Font size of i-th font in pixels."""

    font_paths: Sequence[str]
    """What font the i-th entry is."""

    def best_font_path(self):
        which = int(np.argmin(self.cost))
        return self.font_paths[which]

    def best_font_size(self) -> np.float32:
        which = int(np.argmin(self.cost))
        return self.font_size[which]

    def clone(self):
        return FontAnalysisResult(
            cost=self.cost.copy(),
            font_size=self.font_size.copy(),
            font_paths=self.font_paths,
        )

    @classmethod
    def merge_prediction(cls, results: Sequence[Self]):
        if len(results) == 0:
            raise RuntimeError("result array is empty")

        costs = np.stack([x.cost for x in results])
        cost = np.mean(costs, axis=0)

        font_size = np.nanmedian(np.stack([x.font_size for x in results]), axis=0)

        return FontAnalysisResult(cost=cost, font_size=font_size, font_paths=results[0].font_paths)


def contains_glyph(font_data: TTFont, char: str):
    for cmap in font_data["cmap"].tables:
        if cmap.isUnicode() and ord(char) in cmap.cmap:
            return True

    return False


def compute_font_match(
    char: str,
    img_mask: np.ndarray,
    fonts: list[tuple[Lock, str, ImageFont.FreeTypeFont]],
    font_datas: list[TTFont],
    font_paths: tuple[str, ...],
) -> FontAnalysisResult:
    assert img_mask.ndim == 2
    assert img_mask.dtype == np.uint8

    H, W = img_mask.shape
    STRUCTURE_WEIGHT = 0.5

    img_weight = (255 - img_mask).astype(np.float32) / 255.0

    img_bool = (img_mask >= 128).astype(np.uint8)
    dt_img = cv2.distanceTransform(img_bool, cv2.DIST_L2, 5)
    np.clip(dt_img, None, np.sqrt(H * W), out=dt_img)

    sum_img = np.sum(img_weight)

    costs = np.empty(len(fonts), dtype=np.float32)
    sizes = np.empty(len(fonts), dtype=np.float32)
    images = []

    sizes[...] = np.nan

    for i, ((lock, file_path, font), font_data) in enumerate(zip(fonts, font_datas)):
        with lock:
            if not contains_glyph(font_data, char):
                costs[i] = 100_000_000

            rendered, font_size = render_character_keep_aspect(char, font, H, W)

        assert rendered.shape == img_mask.shape
        images.append(rendered)

        rendered_weight = rendered.astype(np.float32) / 255.0
        rendered_mask = (rendered < 128).astype(np.uint8)
        dt_render = cv2.distanceTransform(rendered_mask, cv2.DIST_L2, 5)
        np.clip(dt_render, None, np.sqrt(H * W), out=dt_render)

        sum_render = np.sum(rendered_weight)

        # 1. Mean Chamfer Distance (Good for bulk shape/thickness alignment)
        cost_forward = np.sum(dt_render * img_weight) / sum_img if sum_img > 0 else 1e6
        cost_inverse = np.sum(dt_img * rendered_weight) / sum_render if sum_render > 0 else 1e6
        base_cost = cost_forward + cost_inverse

        # 2. Hausdorff Approximation (95th Percentile Distance)
        # This heavily penalizes protrusions like Serifs that exist in one but not the other
        mask_img_bool = img_weight > 0.5
        mask_render_bool = rendered_weight > 0.5

        haus_forward = np.percentile(dt_render[mask_img_bool], 95) if np.any(mask_img_bool) else 1e6
        haus_inverse = np.percentile(dt_img[mask_render_bool], 95) if np.any(mask_render_bool) else 1e6
        hausdorff_cost = haus_forward + haus_inverse

        # 3. Intersection over Union (IoU) Penalty
        intersection = np.logical_and(mask_img_bool, mask_render_bool)
        union = np.logical_or(mask_img_bool, mask_render_bool)
        iou = np.sum(intersection) / np.sum(union) if np.sum(union) > 0 else 0
        iou_penalty = (1.0 - iou) * 10.0  # Scale it up so it impacts the final score

        # Combine costs (You can tweak these weights)
        HAUSDORFF_WEIGHT = 0.5
        IOU_WEIGHT = 1.0

        costs[i] = base_cost + (HAUSDORFF_WEIGHT * hausdorff_cost) + (IOU_WEIGHT * iou_penalty)

        if font_size is not None:
            sizes[i] = font_size

    if False:
        which = int(np.argmin(costs))
        display_fonts(img_mask, images, costs, which)

    return FontAnalysisResult(cost=costs, font_size=sizes, font_paths=font_paths)


@beartype
class FontAnalyzer:
    """
    이 클래스는 멀티스레드를 고려해서 코딩되어야 함.
    """

    def __init__(self, max_cache_size: int = 500):
        self.fonts: list[tuple[Lock, str, ImageFont.FreeTypeFont]] = []
        self.font_datas: list[TTFont] = []
        self._cache: OrderedDict[tuple[str, bytes], FontAnalysisResult] = OrderedDict()
        self._cache_lock = Lock()
        self._max_cache_size = max_cache_size

        for file_name in os.listdir("data/font"):
            if not file_name.endswith(".ttf"):
                continue

            file_path = f"data/font/{file_name}"
            font = ImageFont.truetype(file_path, size=100)
            self.fonts.append((Lock(), file_path, font))
            self.font_datas.append(TTFont(file_path))

        self.font_paths = tuple((x[1] for x in self.fonts))

    def render_character(self, char: str, font_path: str, height: int, width: int):
        for lock, file_path, font in self.fonts:
            if file_path != font_path:
                continue

            with lock:
                return render_character_keep_aspect(char, font, height, width)[0]

        raise ValueError(f"Font {font_path} is not in registry")

    def find_best_match(self, char: str, img_mask: np.ndarray) -> FontAnalysisResult:
        cache_key = (char, img_mask.tobytes())

        with self._cache_lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key]

        result = compute_font_match(char, img_mask, self.fonts, self.font_datas, self.font_paths)

        with self._cache_lock:
            self._cache[cache_key] = result
            if len(self._cache) > self._max_cache_size:
                self._cache.popitem(last=False)

        return result.clone()


if __name__ == "__main__":
    analyzer = FontAnalyzer()
    print(analyzer.find_best_match("가", np.ones((32, 32), dtype=np.uint8) * 255))
