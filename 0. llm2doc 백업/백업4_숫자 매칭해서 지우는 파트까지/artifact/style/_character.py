import asyncio
import unicodedata
import numpy as np
import cv2
import matplotlib.pyplot as plt

from typing import cast, Awaitable, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass
from itertools import chain
from beartype import beartype
from PIL import Image
from paddlex.inference.models.text_detection.result import TextDetResult
from tesserocr import RIL

from llm2doc.artifact.ocr import OCRBlock
from llm2doc.artifact.style._artifact import BlockStyle
from llm2doc.artifact.style._font_analyzer import FontAnalyzer, FontAnalysisResult
from llm2doc.util import validate_type
from llm2doc.tesseract import TesseractFleet


@dataclass
class StyleAnalyzeContext:
    font: FontAnalyzer
    block: OCRBlock
    text_det: TextDetResult
    block_img: np.ndarray
    exe: Executor
    tesseract_line: TesseractFleet
    tesseract_char: TesseractFleet


async def analyze_single_block(ctx: StyleAnalyzeContext) -> BlockStyle | None:
    """IO를 하기 때문에 async인것은 아니고, 내부에서 task를 관리하기 위해 async를 이용함"""

    if ctx.block.is_image:
        return None

    dt_polys = np.asarray(ctx.text_det["dt_polys"], dtype=np.int32)
    dt_scores = np.asarray(ctx.text_det["dt_scores"], dtype=np.int32)

    if dt_polys.size == 0:
        # 텍스트를 인식하지 못함
        return None

    lines = _extract_lines(dt_polys, dt_scores)
    line_count = len(lines)
    line_height = float(_estimate_line_height(ctx.block_img, lines))

    style = await _align_characters(ctx, lines)
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


def _extract_lines(dt_polys: np.ndarray, dt_scores: np.ndarray):
    assert 0 < len(dt_polys)

    dt_polys_ind = np.argsort(np.min(dt_polys[:, :, 1], axis=1))
    dt_polys = dt_polys[dt_polys_ind]
    dt_scores = dt_scores[dt_polys_ind]

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


def _estimate_line_height(img: np.ndarray, lines: list[list[np.ndarray]]):
    return img.shape[0] / len(lines)


async def _align_characters(ctx: StyleAnalyzeContext, lines: list[list[np.ndarray]]):
    futures = [_align_character_each_rect(ctx, rect) for line in lines for rect in line]
    results = await asyncio.gather(*futures)

    colors = list(chain.from_iterable([x[0] for x in results]))
    chars = list(chain.from_iterable([x[1] for x in results]))
    font_families = list(chain.from_iterable([x[2] for x in results]))

    if len(colors) == 0 or len(font_families) == 0:
        return None

    font_family = FontAnalysisResult.merge_prediction(font_families)
    color = _get_median_color(np.concat(colors, axis=0))

    # _show_font(chars, self.font, font_family)

    return font_family, color


async def _align_character_each_rect(ctx: StyleAnalyzeContext, rect: np.ndarray):
    xmin = np.min(rect[:, 0])
    xmax = np.max(rect[:, 0])
    ymin = np.min(rect[:, 1])
    ymax = np.max(rect[:, 1])

    segment_rgb = ctx.block_img[ymin : ymax + 1, xmin : xmax + 1]
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

    detections = await _segment_single_char(ctx, segment_mask)

    colors: list[np.ndarray] = []
    chars: list[tuple[np.ndarray, str]] = []
    font_families_futures: list[Awaitable[FontAnalysisResult]] = []

    for bbox, ch in detections:
        mask = _slice_img(segment_mask, bbox).copy()
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
        font_families_futures.append(asyncio.wrap_future(ctx.exe.submit(ctx.font.find_best_match, ch, mask)))

    font_families = await asyncio.gather(*font_families_futures)

    return colors, chars, font_families


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


async def _propose_character_segment(ctx: StyleAnalyzeContext, img_mask: np.ndarray) -> list[int]:
    """X좌표의 목록을 리턴함"""

    PIX_BG = 255
    H, W = img_mask.shape

    def inner():
        with ctx.tesseract_line.access() as tess:
            tess.SetImage(Image.fromarray(img_mask))
            return tess.GetComponentImages(RIL.SYMBOL, True)

    boxes = await asyncio.wrap_future(ctx.exe.submit(inner))

    coords = cast(list[int], [])

    fg_mask = np.where(img_mask < PIX_BG, 255, 0).astype(np.uint8)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(fg_mask, connectivity=4)

    for i in range(1, num_labels):  # Skip background (label 0)
        left = stats[i, cv2.CC_STAT_LEFT]
        right = left + stats[i, cv2.CC_STAT_WIDTH]

        coords.append(min(W - 1, max(0, left)))
        coords.append(min(W - 1, max(0, right)))

    if boxes:
        for im, box, _, _ in boxes:
            coords.append(min(W - 1, box["x"]))
            coords.append(min(W - 1, box["x"] + box["w"]))

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


async def _segment_single_char(ctx: StyleAnalyzeContext, img_mask: np.ndarray):
    MIN_RATIO = 0.1
    MAX_RATIO = 2
    H, W = img_mask.shape

    min_width = max(1, int(H * MIN_RATIO))
    max_width = int(H * MAX_RATIO)

    img_mask_padded = np.pad(img_mask, [[8, 8], [0, 0]], constant_values=255)

    def process_line(img: np.ndarray):
        with ctx.tesseract_line.access() as tess:
            tess.SetImage(Image.fromarray(img))
            return tess.GetUTF8Text()

    def process_char(img: np.ndarray):
        with ctx.tesseract_char.access() as tess:
            tess.SetImage(Image.fromarray(img))
            return tess.GetUTF8Text()

    pred_text_future = asyncio.wrap_future(ctx.exe.submit(process_line, img_mask_padded))

    x_bars = await _propose_character_segment(ctx, img_mask_padded)

    processed: set[tuple[int, ...]] = set()
    bboxes = cast(list[np.ndarray], [])
    char_texts = cast(list[Awaitable[str]], [])

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

            future = asyncio.wrap_future(ctx.exe.submit(process_char, segment))
            char_texts.append(future)

    pred_text = unicodedata.normalize("NFC", await pred_text_future).strip()

    begin, end = _slice_source_text(ctx.block.content, pred_text)
    full_text = ctx.block.content[begin:end].strip()

    candidates: list[tuple[np.ndarray, str]] = []
    for bbox, data in zip(bboxes, char_texts):
        data = unicodedata.normalize("NFC", await data).strip()

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
