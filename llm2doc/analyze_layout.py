import numpy as np
import json
import os
import gc
import re
import paddle
import pickle
import cv2
import pytesseract
import matplotlib.pyplot as plt
import unicodedata

from dataclasses import dataclass
from typing import Any, cast, Sequence
from beartype import beartype
from PIL import Image
from threading import Lock
from concurrent.futures import Executor, ThreadPoolExecutor, Future
from paddleocr import PaddleOCRVL, TextDetection
from paddlex.inference.pipelines.paddleocr_vl.result import (
    PaddleOCRVLResult,
    PaddleOCRVLBlock,
)
from paddlex.inference.models.text_detection.result import TextDetResult

from .util import validate_type
from .render_image import render_boxes
from .font_analyzer import FontAnalyzer, FontAnalysisResult


REGEX_NEWLINE = re.compile(r"[\r\n]+")
REGEX_KOR = re.compile(r"[ㄱ-ㅣ가-힣ᄀ-ᇿ]")


@beartype
def _show_image(
    img: np.ndarray,
    *,
    polys: np.ndarray | None = None,
    aabb: np.ndarray | None = None,
    scale: int | None = None,
):
    if img.ndim == 3:
        vis_img = img[..., ::-1].copy()
    else:
        vis_img = np.tile(np.expand_dims(img, axis=-1), [1, 1, 3]).copy()

    if scale is None:
        H, W, _ = vis_img.shape
        scale = max(1, int(200 // min(H, W)))

    if scale != 1:
        vis_img = cv2.resize(vis_img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)

    if polys is not None:
        polys = np.round(polys).astype(np.int32) * scale

        num_points = polys.shape[1]
        polygons_cv = polys.reshape(-1, num_points, 1, 2)
        polygons_cv = cast(Sequence[cv2.typing.MatLike], polygons_cv)

        cv2.polylines(vis_img, polygons_cv, isClosed=True, color=(0, 255, 0), thickness=2)
    if aabb is not None:
        aabb = np.round(aabb).astype(np.int32) * scale

        for box in aabb:
            xmin, ymin, xmax, ymax = box
            cv2.rectangle(
                vis_img,
                (xmin, ymin),
                (xmax, ymax),
                color=(0, 0, 255),  # Red in BGR
                thickness=2,
            )

    try:
        cv2.imshow("bbox", vis_img)
        while cv2.waitKey(1) & 0xFF != ord("q"):
            continue
    finally:
        cv2.destroyWindow("bbox")


def _slice_img(img: np.ndarray, bbox: np.ndarray | Sequence[int]):
    xmin, ymin, xmax, ymax = bbox
    return img[ymin : ymax + 1, xmin : xmax + 1]


def _get_median_color(srgb_array: np.ndarray):
    assert srgb_array.shape[-1] == 3
    assert srgb_array.ndim == 2
    assert srgb_array.dtype == np.uint8

    linear_colors = (srgb_array.astype(np.float32) / 255.0) ** 2.2

    median_linear = np.median(linear_colors, axis=0)

    median_srgb = np.clip(median_linear ** (1.0 / 2.2), 0.0, 1.0)

    return np.astype(median_srgb * 255, np.uint8)


def _fit_bbox_by_connected(img: np.ndarray, bbox: np.ndarray | Sequence):
    xmin, ymin, xmax, ymax = bbox

    inverted = cv2.bitwise_not(img)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(inverted, connectivity=4)

    roi_labels = np.unique(labels[ymin : ymax + 1, xmin : xmax + 1])
    roi_labels = roi_labels[roi_labels != 0]

    if len(roi_labels) == 0:
        return np.asarray(bbox, dtype=np.int32)

    selected_stats = stats[roi_labels.astype(np.int32, copy=False)]

    new_xmin = np.min(selected_stats[:, cv2.CC_STAT_LEFT])
    new_ymin = np.min(selected_stats[:, cv2.CC_STAT_TOP])
    new_xmax = np.max(selected_stats[:, cv2.CC_STAT_LEFT] + selected_stats[:, cv2.CC_STAT_WIDTH]) - 1
    new_ymax = np.max(selected_stats[:, cv2.CC_STAT_TOP] + selected_stats[:, cv2.CC_STAT_HEIGHT]) - 1

    return np.array([new_xmin, new_ymin, new_xmax, new_ymax], dtype=np.int32)


def _propose_character_segment(img_mask: np.ndarray, exe: Executor) -> list[int]:
    """X좌표의 목록을 리턴함"""

    PIX_BG = 255
    H, W = img_mask.shape

    # PSM: https://tesseract-ocr.github.io/tessdoc/ImproveQuality#page-segmentation-method
    data = exe.submit(lambda x: pytesseract.image_to_boxes(x, lang="kor+eng", config="--psm 7 --oem 0"), img_mask)

    coords = cast(list[int], [])

    fg_mask = np.where(img_mask < PIX_BG, 255, 0).astype(np.uint8)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(fg_mask, connectivity=4)

    for i in range(1, num_labels):  # Skip background (label 0)
        left = stats[i, cv2.CC_STAT_LEFT]
        right = left + stats[i, cv2.CC_STAT_WIDTH]

        coords.append(min(W - 1, max(0, left)))
        coords.append(min(W - 1, max(0, right)))

    data = unicodedata.normalize("NFC", data.result())

    for x in data.split("\n"):
        if len(x.strip()) == 0:
            continue
        _, xmin, _, xmax, _, _ = x.rsplit(maxsplit=5)
        coords.append(min(W - 1, int(xmin)))
        coords.append(min(W - 1, int(xmax)))

    coords.sort()

    if len(coords) == 0:
        return [0, W - 1]

    # VPP
    profile = np.min(img_mask, axis=0)

    valid = [True]
    prev = coords[0]
    was_empty = profile[prev] == PIX_BG

    for now in coords[1:]:
        if prev == now:
            valid.append(False)
            continue

        if was_empty and np.min(profile[prev + 1 : now + 1]) == PIX_BG:
            valid.append(False)
            continue

        prev = now
        was_empty = profile[prev] == PIX_BG
        valid.append(True)

    return [coords[i] for i in range(len(coords)) if valid[i]]


def _slice_source_text(gt_text: str, pred_text: str) -> tuple[int, int]:
    n, m = len(gt_text), len(pred_text)
    if not m or not n:
        return 0, 0

    # the edit distance
    dp = [0] * (n + 1)

    # the 'begin' index of the slice
    starts = list(range(n + 1))

    for i, p_char in enumerate(pred_text):
        next_dp = [i + 1] * (n + 1)
        next_starts = [0] * (n + 1)

        for j, g_char in enumerate(gt_text):
            cost_sub = dp[j] + (0 if p_char == g_char else 1)
            cost_del = dp[j + 1] + 1
            cost_ins = next_dp[j] + 1

            min_cost = cost_sub
            next_starts[j + 1] = starts[j]

            if cost_del < min_cost:
                min_cost = cost_del
                next_starts[j + 1] = starts[j + 1]

            if cost_ins < min_cost:
                min_cost = cost_ins
                next_starts[j + 1] = next_starts[j]

            next_dp[j + 1] = min_cost

        dp = next_dp
        starts = next_starts

    min_dist = float("inf")
    best_start, best_end = 0, 0

    for j in range(n + 1):
        if dp[j] < min_dist:
            min_dist = dp[j]
            best_end = j
            best_start = starts[j]
        elif dp[j] == min_dist:
            # Tie-breaker: prefer the shortest slice length
            curr_len = j - starts[j]
            best_len = best_end - best_start
            if curr_len < best_len:
                best_end = j
                best_start = starts[j]

    return best_start, best_end


def _segment_single_char(img_mask: np.ndarray, real_text: str, exe: Executor):
    MIN_RATIO = 0.1
    MAX_RATIO = 2
    H, W = img_mask.shape

    min_width = max(1, int(H * MIN_RATIO))
    max_width = int(H * MAX_RATIO)

    img_mask_padded = np.pad(img_mask, [[8, 8], [0, 0]], constant_values=255)

    # PSM: https://tesseract-ocr.github.io/tessdoc/ImproveQuality#page-segmentation-method
    pred_text = exe.submit(
        lambda x: pytesseract.image_to_string(x, lang="kor+eng", config="--psm 7 --oem 1"), img_mask_padded
    )

    x_bars = _propose_character_segment(img_mask_padded, exe)

    processed: set[tuple[int, ...]] = set()
    bboxes = cast(list[np.ndarray], [])
    futures = cast(list[Future[str]], [])

    for i, begin in enumerate(x_bars[:-1]):
        for end in x_bars[i + 1 :]:
            width = end - begin + 1
            if width <= 1:
                continue

            if width <= min_width or max_width <= width:
                break

            bbox = [begin, 0, end, H - 1]
            bbox = _fit_bbox_by_connected(img_mask, bbox)
            bbox[1] = 0
            bbox[3] = H - 1
            bbox = _fit_bbox_by_connected(img_mask, bbox)

            bbox_tuple = tuple(map(int, bbox))
            if bbox_tuple in processed:
                continue

            processed.add(bbox_tuple)

            segment = _slice_img(img_mask, bbox)
            if np.min(segment) == 255:
                continue

            segment = np.pad(segment, [[8, 8], [8, 8]], constant_values=255)

            bboxes.append(bbox)
            futures.append(
                exe.submit(lambda x: pytesseract.image_to_string(x, lang="kor+eng", config="--psm 10 --oem 1"), segment)
            )

    pred_text = pred_text.result()
    pred_text = unicodedata.normalize("NFC", pred_text).strip()

    begin, end = _slice_source_text(real_text, pred_text)
    full_text = real_text[begin:end].strip()

    candidates: list[tuple[np.ndarray, str]] = []
    for bbox, future in zip(bboxes, futures):
        data = future.result()
        data = unicodedata.normalize("NFC", data).strip()

        # 1글자짜리 텍스트만 남김
        if len(data) != 1:
            continue

        candidates.append((bbox, data))

    candidates.sort(key=lambda x: x[0][2])
    candidates.insert(0, (np.asarray([-1, -1, -1, -1], dtype=np.int32), ""))

    # 이 아래 코드는 AI로 생성했음.

    M = len(candidates)
    N = len(full_text)

    # dp[i][j]: max matched length ending exactly at candidate i, consuming j chars of full_text
    dp = np.full((M, N + 1), -1, dtype=int)

    # Running maximums to accelerate predecessor lookup from O(M^2) to O(M)
    max_dp = np.full((M, N + 1), -1, dtype=int)
    max_back = np.full((M, N + 1), -1, dtype=int)
    backtrack: list[list[tuple[int, int] | None]] = [[None] * (N + 1) for _ in range(M)]

    dp[0][0] = 0
    max_dp[0][0] = 0
    max_back[0][0] = 0

    def match_subseq(s: str, t: str, start: int) -> int:
        curr = start
        for char in s:
            curr = t.find(char, curr)
            if curr == -1:
                return -1
            curr += 1
        return curr

    for i in range(1, M):
        cand_bbox, cand_text = candidates[i]
        cand_xmin = cand_bbox[0]
        cand_len = len(cand_text)

        # Find the largest valid predecessor index (enforces no bbox overlap)
        max_p = -1
        for p in range(i - 1, -1, -1):
            if candidates[p][0][2] < cand_xmin:
                max_p = p
                break

        if max_p != -1:
            for k in range(N + 1):
                best_prev_len = max_dp[max_p][k]
                if best_prev_len != -1:
                    j = match_subseq(cand_text, full_text, k)
                    if j != -1:
                        new_len = best_prev_len + cand_len
                        if new_len > dp[i][j]:
                            dp[i][j] = new_len
                            backtrack[i][j] = (max_back[max_p][k], k)

        # Update running maximums for the next iterations
        for j in range(N + 1):
            if dp[i][j] > max_dp[i - 1][j]:
                max_dp[i][j] = dp[i][j]
                max_back[i][j] = i
            else:
                max_dp[i][j] = max_dp[i - 1][j]
                max_back[i][j] = max_back[i - 1][j]

    # Find the sequence that yielded the maximum matched characters
    best_i, best_j = -1, -1
    max_matched = -1
    for i in range(M):
        for j in range(N + 1):
            if dp[i][j] > max_matched:
                max_matched = dp[i][j]
                best_i, best_j = i, j
            elif dp[i][j] == max_matched and max_matched != -1:
                if j < best_j:  # Tie-breaker: prefer matches that finish earlier in full_text
                    best_i, best_j = i, j

    final_bboxes: list[np.ndarray] = []
    final_texts: list[str] = []

    # Backtrack to reconstruct the optimal sequence
    if max_matched > 0:
        curr_i, curr_j = best_i, best_j
        while curr_i != 0:
            prev_i, prev_j = backtrack[curr_i][curr_j]  # type: ignore
            final_bboxes.append(candidates[curr_i][0])
            final_texts.append(candidates[curr_i][1])
            curr_i, curr_j = prev_i, prev_j

        final_bboxes.reverse()
        final_texts.reverse()

    return list(zip(final_bboxes, final_texts))


def _show_font(collected_chars: list, font: FontAnalyzer, font_family: FontAnalysisResult):
    target_h = 128
    top_row_images = []
    bottom_row_images = []

    for mask, ch in collected_chars:
        h, w = mask.shape[:2]
        if h == 0 or w == 0:
            continue

        target_w = max(1, int(w * (target_h / h)))
        orig_resized = cv2.resize(mask, (target_w, target_h), interpolation=cv2.INTER_CUBIC)

        rendered = font.render_character(ch, font_family.best_font_path(), target_h, target_w)

        top_row_images.append(orig_resized)
        bottom_row_images.append(rendered)

    if top_row_images and bottom_row_images:
        top_row = np.hstack(top_row_images)
        bottom_row = np.hstack(bottom_row_images)

        comparison_img = np.vstack([top_row, bottom_row])

        plt.figure(figsize=(15, 6))
        plt.imshow(comparison_img, cmap="gray", vmin=0, vmax=255)
        plt.title(f"Font Comparison (Top: Original | Bottom: Rendered)\nMatched Font: {font_family.best_font_path()}")
        plt.axis("off")
        plt.tight_layout()
        plt.show()


@beartype
@dataclass
class BlockStyle:
    line_count: int

    line_height: float
    """ pixels """

    font_family: str
    """ path to the font """

    color: tuple[int, ...]
    """ (r, g, b). None means transparent """

    font_size: float

    @property
    def color_css(self):
        if self.color is None:
            return "#000000"

        r, g, b = self.color
        return f"#{r:02x}{g:02x}{b:02x}"


@beartype
@dataclass
class BlockInfo:
    label: str
    content: str
    bbox: list[int]
    style: BlockStyle | None
    is_text: bool
    is_image: bool
    is_html: bool

    def to_structured_html(self, page: "ParsedPage", indent: int = 0, block_id: str | None = None) -> str:
        result = []

        bbox = [
            self.bbox[0] * 1000 // page.width,
            self.bbox[1] * 1000 // page.height,
            self.bbox[2] * 1000 // page.width,
            self.bbox[3] * 1000 // page.height,
        ]
        bbox_str = ", ".join([str(x) for x in bbox])

        result.append(" " * indent)
        result.append(f'<div id="{block_id}" data-bbox="[{bbox_str}]">\n')

        if self.is_text:
            for line in REGEX_NEWLINE.split(self.content.strip()):
                result.append(" " * indent)
                result.append("  <p>")
                result.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                result.append("</p>\n")
        elif self.is_image:
            result.append(" " * indent)
            result.append(f'  <img src="/{block_id}/image">\n')
        elif self.is_html:
            result.append(" " * indent)
            result.append("  ")
            result.append(self.content)
            result.append("\n")
        else:
            print("[WARN] Block has no is_* directive")

        result.append(" " * indent)
        result.append("</div>")

        return "".join(result)


@beartype
@dataclass
class ParsedPage:
    width: int
    height: int
    blocks: list[BlockInfo]
    screenshot: Image.Image
    json: str
    markdown: str
    markdown_images: dict[str, Image.Image]

    def __str__(self):
        content = "\n\n".join([f"Block #{i}\n{blk}" for i, blk in enumerate(self.blocks)])
        return f"#####\n{content}\n#####"

    def to_structured_html(self, indent: int = 0, page_id: str | None = None) -> str:
        result = []
        result.append(" " * indent)
        result.append(f'<page id="{page_id}">\n')

        for i, block in enumerate(self.blocks):
            if page_id is None:
                block_id = f"block-{i + 1}"
            else:
                block_id = f"{page_id}-block-{i + 1}"

            result.append(block.to_structured_html(self, indent=indent + 2, block_id=block_id))
            result.append("\n")

        result.append(" " * indent)
        result.append("</page>\n")

        return "".join(result)

    def reconstruct_image(self) -> Image.Image:
        reconstructed_img = Image.new("RGB", (self.width, self.height), color="white")

        bboxes = []
        texts = []

        for block in self.blocks:
            bboxes.append(block.bbox)

            if block.is_text:
                texts.append(block.content.strip())
            else:
                texts.append(f"[{block.label}]")

        return render_boxes(reconstructed_img, bboxes=bboxes, selected=-1, text=texts)


@beartype
@dataclass
class ParsedDocument:
    id: str
    pages: list[ParsedPage]
    concatenated_markdown: str

    def to_sturctured_html(self, indent: int = 0, doc_id: str | None = None) -> str:
        result = []

        result.append(" " * indent)
        if doc_id is None:
            result.append("<document>\n")
        else:
            result.append(f'<document id="{doc_id}">\n')

        for i, page in enumerate(self.pages):
            if doc_id is None:
                page_id = f"page-{i + 1}"
            else:
                page_id = f"{doc_id}-page-{i + 1}"

            result.append(page.to_structured_html(indent=indent + 2, page_id=page_id))
            result.append("\n")

        result.append(" " * indent)
        result.append("</document>")

        return "".join(result)

    def save_as_cache(self):
        os.makedirs(f"data/{self.id}/generated/", exist_ok=True)
        with open(f"data/{self.id}/generated/layout.pickle", "wb") as f:
            pickle.dump(self, f)


@beartype
class LayoutAnalyzer:
    def __init__(self):
        self.pipeline: PaddleOCRVL | None = None

    def load_model(self):
        # 데모 프로그램의 세팅을 그대로 이용
        self.pipeline = PaddleOCRVL(
            use_layout_detection=True,
            merge_layout_blocks=False,
            layout_threshold=0.5,
            layout_nms=True,
            # layout_unclip_ratio=1.05,
        )

    @classmethod
    def clear_cache(cls):
        for dir in os.listdir("data"):
            if os.path.isdir(f"data/{dir}/generated"):
                file_name = f"data/{dir}/generated/layout.pickle"
                if os.path.exists(file_name):
                    os.remove(file_name)

    def __call__(self, doc: str) -> ParsedDocument:
        """
        주어진 데이터의 이미지를 순서대로 분석함.
        """

        if os.path.exists(f"data/{doc}/generated/layout.pickle"):
            with open(f"data/{doc}/generated/layout.pickle", "rb") as f:
                return pickle.load(f)

        file_paths = [x for x in os.listdir(f"data/{doc}") if x.startswith("original")]
        file_paths.sort()
        pages = [Image.open(f"data/{doc}/{x}") for x in file_paths]

        if self.pipeline is None:
            self.load_model()
            assert self.pipeline is not None

        pages_arrays = []
        for img in pages:
            img = img.convert("RGB")
            img_arr = np.asarray(img)[..., ::-1].copy()
            pages_arrays.append(img_arr)

        pages_output = self.pipeline.predict(pages_arrays)
        assert len(pages_output) == len(pages)

        pages_output = self.pipeline.restructure_pages(
            pages_output,
            merge_tables=False,
            relevel_titles=True,
            concatenate_pages=False,
        )
        pages_output = validate_type(pages_output, list[PaddleOCRVLResult])
        assert len(pages_output) == len(pages)

        concatenated_markdown = self.pipeline.concatenate_markdown_pages([x.markdown for x in pages_output])

        # VRAM OOM 발생함
        gc.collect()
        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count():
            paddle.device.cuda.empty_cache()

        parsed_pages = []

        for i, output in enumerate(pages_output):
            as_json = json.dumps(output.json, ensure_ascii=False)
            as_markdown: Any = output.markdown

            blocks = []
            for block in output["parsing_res_list"]:
                block = validate_type(block, PaddleOCRVLBlock)

                is_image = block.label == "image"
                is_html = block.label == "table"
                is_text = not is_image and not is_html

                blocks.append(
                    BlockInfo(
                        label=block.label,
                        content=block.content,
                        bbox=block.bbox,
                        style=None,
                        is_text=is_text,
                        is_image=is_image,
                        is_html=is_html,
                    )
                )

            parsed_pages.append(
                ParsedPage(
                    width=pages[i].width,
                    height=pages[i].height,
                    blocks=blocks,
                    screenshot=pages[i],
                    json=as_json,
                    markdown=as_markdown["markdown_texts"],
                    markdown_images=as_markdown["markdown_images"],
                )
            )

        ret = ParsedDocument(
            id=doc,
            pages=parsed_pages,
            concatenated_markdown=concatenated_markdown,
        )

        ret.save_as_cache()

        return ret

    def dispose(self):
        self.pipeline = None
        gc.collect()
        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count():
            paddle.device.cuda.empty_cache()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.dispose()


@beartype
class LayoutStyleAnalyzer:
    def __init__(self):
        self.ocr_lock = Lock()
        self.ocr: TextDetection | None = None
        self.font = FontAnalyzer()

    def load_model(self):
        self.ocr = TextDetection(
            model_name="PP-OCRv5_server_det",
            box_thresh=0.2,
        )

    def __call__(self, block: BlockInfo, block_img: np.ndarray, exe: ThreadPoolExecutor) -> BlockStyle | None:
        if block.is_image:
            return None

        with self.ocr_lock:
            if self.ocr is None:
                self.load_model()
                assert self.ocr is not None

            result = self.ocr.predict(block_img)[0]

        result = validate_type(result, TextDetResult)

        dt_polys = np.asarray(result["dt_polys"], dtype=np.int32)
        dt_scores = np.asarray(result["dt_scores"], dtype=np.int32)

        if dt_polys.size == 0:
            print("[WARN] 텍스트를 인식하지 못함")
            plt.imshow(block_img)
            plt.show()
            return None

        lines = self._extract_lines(dt_polys, dt_scores)
        line_count = len(lines)
        line_height = float(self._estimate_line_height(block_img, lines))

        style = self._align_characters(block, block_img, lines, exe)
        if style is None:
            return None

        font, color = style

        return BlockStyle(
            line_count=line_count,
            line_height=line_height,
            color=tuple(map(int, color)),
            font_family=font.best_font_path(),
            font_size=float(font.best_font_size()),
        )

    def _extract_lines(self, dt_polys: np.ndarray, dt_scores: np.ndarray):
        dt_polys_ind = np.argsort(np.min(dt_polys[:, :, 1], axis=1))
        dt_polys = dt_polys[dt_polys_ind]
        dt_scores = dt_scores[dt_polys_ind]

        ymin = np.min(dt_polys[:, :, 1], axis=1)
        ymax = np.max(dt_polys[:, :, 1], axis=1)

        box_heights = ymax - ymin
        box_height = np.median(box_heights)

        # 중앙값과 비슷한 높이만 걸러냄 (문단단위로 박스가 나눠졌기 때문에 괜찮음)
        dt_polys_mask = np.isclose(box_heights, box_height, rtol=0.5, atol=0)
        dt_polys = dt_polys[dt_polys_mask]
        dt_scores = dt_scores[dt_polys_mask]
        assert 0 < len(dt_polys)

        # y좌표가 절반 이상 겹치면 한 줄로 간주
        lines = cast(list[list[np.ndarray]], [[dt_polys[0].copy()]])
        for poly in dt_polys[1:]:
            ymin = min((np.min(x[:, 1]) for x in lines[-1]))
            ymax = max((np.max(x[:, 1]) for x in lines[-1]))

            curr_ymin = np.min(poly[:, 1])
            curr_ymax = np.max(poly[:, 1])

            overlap_start = max(ymin, curr_ymin)
            overlap_end = min(ymax, curr_ymax)
            overlap = max(overlap_end - overlap_start, 0)

            if (curr_ymax - curr_ymin) // 2 <= overlap:
                lines[-1].append(poly.copy())
            else:
                lines.append([poly.copy()])

        for line in lines:
            line.sort(key=lambda x: np.min(x[:, 0]))

        return lines

    def _estimate_line_height(self, img: np.ndarray, lines: list[list[np.ndarray]]):
        return img.shape[0] / len(lines)

    def _align_characters(self, block: BlockInfo, img_rgb: np.ndarray, lines: list[list[np.ndarray]], exe: Executor):
        font_families: list[FontAnalysisResult] = []
        colors = []
        chars = []

        for line in lines:
            for box in line:
                xmin = np.min(box[:, 0])
                xmax = np.max(box[:, 0])
                ymin = np.min(box[:, 1])
                ymax = np.max(box[:, 1])

                segment_rgb = img_rgb[ymin : ymax + 1, xmin : xmax + 1]
                segment_gray = cv2.cvtColor(segment_rgb, cv2.COLOR_RGB2GRAY)
                _, segment_mask = cv2.threshold(segment_gray, -1, 255, cv2.THRESH_OTSU)

                segment_mask = validate_type(segment_mask, np.ndarray)

                # border의 median color
                border1 = np.ravel(segment_mask[:2])
                border2 = np.ravel(segment_mask[2:-2, :2])
                border3 = np.ravel(segment_mask[2:-2, -2:])
                border4 = np.ravel(segment_mask[-2:])
                bg_color = np.median(np.concat([border1, border2, border3, border4]))

                # 배경색을 255로 맞춤
                flip_bg = bg_color <= 127
                if flip_bg:
                    np.subtract(255, segment_mask, out=segment_mask)

                # TODO: Tesseract 호출 전에 높이를 20~60px로 맞추기

                detections = _segment_single_char(segment_mask, block.content, exe)

                for bbox, ch in detections:
                    mask = _slice_img(segment_mask, bbox)
                    chars.append((mask, ch))

                    # color
                    if np.min(mask) != 255:
                        ind = np.expand_dims(mask <= 127, -1)
                        ind = np.tile(ind, [1, 1, 3])

                        # TODO: ind에 erode/dilate 한번 하기 (가장자리 반투명 픽셀 빼고 계산)

                        pixels = _slice_img(segment_rgb, bbox)
                        pixels = np.reshape(pixels[ind], [-1, 3])
                        colors.append(pixels.copy())

                    # font family
                    font_families.append(self.font.find_best_match(ch, mask))

        if len(colors) == 0 or len(font_families) == 0:
            return None

        font_family = FontAnalysisResult.merge_prediction(font_families)
        color = _get_median_color(np.concat(colors, axis=0))

        _show_font(chars, self.font, font_family)

        return font_family, color

    def dispose(self):
        self.ocr = None
        gc.collect()
        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count():
            paddle.device.cuda.empty_cache()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.dispose()


def populate_cache(clear_all: bool = False):
    if clear_all:
        LayoutAnalyzer.clear_cache()

    documents = cast(list[ParsedDocument], [])

    with LayoutAnalyzer() as layout_analyzer:
        for doc in os.listdir("data"):
            if os.path.isdir(f"data/{doc}"):
                documents.append(layout_analyzer(doc))

    with LayoutStyleAnalyzer() as layout_style_analyzer:
        with ThreadPoolExecutor() as exe:
            try:
                doc = documents[4]
                page = doc.pages[0]
                page_img = np.asarray(page.screenshot.convert("RGB"))

                for block in page.blocks:
                    xmin, ymin, xmax, ymax = block.bbox

                    # Padding
                    xmin = max(xmin - 8, 0)
                    ymin = max(ymin - 8, 0)
                    xmax = min(xmax + 8, page_img.shape[1])
                    ymax = min(ymax + 8, page_img.shape[0])

                    block_img = page_img[ymin:ymax, xmin:xmax]
                    block.style = layout_style_analyzer(block, block_img, exe)
                exit()

                for doc in documents:
                    for page in doc.pages:
                        page_img = np.asarray(page.screenshot.convert("RGB"))

                        for block in page.blocks:
                            xmin, ymin, xmax, ymax = block.bbox

                            # Padding
                            xmin = max(xmin - 8, 0)
                            ymin = max(ymin - 8, 0)
                            xmax = min(xmax + 8, page_img.shape[1])
                            ymax = min(ymax + 8, page_img.shape[0])

                            block_img = page_img[ymin:ymax, xmin:xmax]
                            block.style = layout_style_analyzer(block, block_img, exe)

                    doc.save_as_cache()
            except KeyboardInterrupt:
                exe.shutdown(wait=False, cancel_futures=True)
                raise
