import os
import cv2
import numpy as np
import matplotlib.pyplot as plt

from threading import Lock
from dataclasses import dataclass
from beartype import beartype
from typing import Sequence, Self
from PIL import Image, ImageFont, ImageDraw


FONT_PADDING = 8


def render_character(char: str, font: ImageFont.FreeTypeFont, target_height: int, target_width: int) -> np.ndarray:
    left, top, right, bottom = font.getbbox(char)

    base_width = int(right - left)
    base_height = int(bottom - top)

    if base_width <= 0 or base_height <= 0:
        return np.zeros((target_width, target_height), dtype=np.uint8)

    safe_width = base_width + (FONT_PADDING * 2)
    safe_height = base_height + (FONT_PADDING * 2)

    img = Image.new("L", (safe_width, safe_height), 0)
    draw = ImageDraw.Draw(img)

    draw.text((int(-left) + FONT_PADDING, int(-top) + FONT_PADDING), char, font=font, fill=255)

    tight_bbox = img.getbbox()

    if tight_bbox is None:
        return np.zeros((target_width, target_height), dtype=np.uint8)

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

    return final_arr


@beartype
@dataclass
class FontAnalysisResult:
    cost: np.ndarray
    """L2 difference between font and actual image."""

    font_paths: Sequence[str]
    """What font the i-th entry is."""

    def best_font(self):
        which = int(np.argmin(self.cost))
        return self.font_paths[which]

    @classmethod
    def merge_prediction(cls, results: Sequence[Self]):
        if len(results) == 0:
            raise RuntimeError("result array is empty")

        costs = np.stack([x.cost for x in results])
        weight = np.max(1 - costs, axis=1, keepdims=True)
        weight /= np.sum(weight)

        cost = np.sum(costs * weight, axis=0)
        # cost = np.min(costs, axis=0)

        return FontAnalysisResult(cost=cost, font_paths=results[0].font_paths)


@beartype
class FontAnalyzer:
    """
    이 클래스는 멀티스레드를 고려해서 코딩되어야 함.
    """

    def __init__(self):
        self.fonts: list[tuple[Lock, str, ImageFont.FreeTypeFont]] = []

        for file_name in os.listdir("data/font"):
            if not file_name.endswith(".ttf"):
                continue

            file_path = f"data/font/{file_name}"
            font = ImageFont.truetype(file_path, size=100)
            self.fonts.append((Lock(), file_path, font))

        self.font_paths = tuple((x[1] for x in self.fonts))

    def render_character(self, char: str, font_path: str, height: int, width: int):
        for lock, file_path, font in self.fonts:
            if file_path != font_path:
                continue

            with lock:
                return render_character(char, font, height, width)

        raise ValueError(f"Font {font_path} is not in registry")

    def find_best_match(self, char: str, img_gray: np.ndarray):
        assert img_gray.ndim == 2
        assert img_gray.dtype == np.uint8

        H, W = img_gray.shape
        BLUR = max(0, int(min(H, W) * 0.01))

        # 배경을 0으로 만듦
        img_gray = 255 - img_gray
        if BLUR != 0:
            img_gray = cv2.blur(img_gray, (BLUR, BLUR), dst=img_gray, borderType=cv2.BORDER_CONSTANT)
        img_gray = img_gray.astype(np.float32)
        img_gray /= 255

        costs = np.empty(len(self.fonts), dtype=np.float32)
        images = []

        for i, (lock, file_path, font) in enumerate(self.fonts):
            with lock:
                rendered = np.asarray(render_character(char, font, H, W))

            assert rendered.shape == img_gray.shape

            if BLUR != 0:
                rendered = cv2.blur(rendered, (BLUR, BLUR), borderType=cv2.BORDER_CONSTANT)
            images.append(rendered)

            rendered = rendered.astype(np.float32)
            rendered /= 255

            diff = rendered - img_gray
            diff = np.square(diff, out=diff)
            costs[i] = np.mean(diff)

        # which = np.argmin(costs)
        # plt.imshow(np.concat([(img_gray * 255).astype(np.uint8), images[which]], axis=1))
        # plt.show()

        return FontAnalysisResult(cost=costs, font_paths=self.font_paths)


if __name__ == "__main__":
    analyzer = FontAnalyzer()
    print(analyzer.find_best_match("가", np.ones((32, 32), dtype=np.uint8) * 255))
