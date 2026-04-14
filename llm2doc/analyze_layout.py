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
from concurrent.futures import ThreadPoolExecutor, Future
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


def _show_image(
    img: np.ndarray,
    *,
    polys: np.ndarray | None = None,
    aabb: np.ndarray | None = None,
):
    if img.ndim == 3:
        vis_img = img[..., ::-1].copy()
    else:
        vis_img = np.tile(np.expand_dims(img, axis=-1), [1, 1, 3]).copy()

    if polys is not None:
        polys = np.round(polys).astype(np.int32)

        num_points = polys.shape[1]
        polygons_cv = polys.reshape(-1, num_points, 1, 2)
        polygons_cv = cast(Sequence[cv2.typing.MatLike], polygons_cv)

        cv2.polylines(vis_img, polygons_cv, isClosed=True, color=(0, 255, 0), thickness=2)
    if aabb is not None:
        aabb = np.round(aabb).astype(np.int32)

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


def _expand_bbox_by_connected(img: np.ndarray, bbox: np.ndarray):
    xmin, ymin, xmax, ymax = bbox

    inverted = cv2.bitwise_not(img)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(inverted, connectivity=4)

    roi_labels = np.unique(labels[ymin : ymax + 1, xmin : xmax + 1])
    roi_labels = roi_labels[roi_labels != 0]

    if len(roi_labels) == 0:
        return bbox

    selected_stats = stats[roi_labels.astype(np.int32, copy=False)]

    new_xmin = np.min(selected_stats[:, cv2.CC_STAT_LEFT])
    new_ymin = np.min(selected_stats[:, cv2.CC_STAT_TOP])
    new_xmax = np.max(selected_stats[:, cv2.CC_STAT_LEFT] + selected_stats[:, cv2.CC_STAT_WIDTH]) - 1
    new_ymax = np.max(selected_stats[:, cv2.CC_STAT_TOP] + selected_stats[:, cv2.CC_STAT_HEIGHT]) - 1

    return np.array([new_xmin, new_ymin, new_xmax, new_ymax], dtype=np.int32)


@beartype
@dataclass
class BlockStyle:
    line_boxes: np.ndarray
    """
    [N, 4, 2] 형태.
    N: 줄 개수
    4: 사각형을 만드는 점 개수
    2: x, y값
    """

    line_count: int
    """ 줄 개수 """

    line_height: float
    """ 원본 이미지 크기 기준 픽셀 단위 """

    font_size: float
    """ 원본 이미지 크기 기준 픽셀 단위 """

    font_family: str
    """ 폰트 경로 """

    color: str
    """ #rrggbb 형태 """

    def __post_init__(self):
        assert self.line_boxes.dtype == np.int32
        assert len(self.line_boxes.shape) == 3
        assert self.line_boxes.shape[1:] == (4, 2)


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
            merge_tables=True,
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

    def __call__(self, block: BlockInfo, block_img: np.ndarray) -> BlockStyle | None:
        if block.is_image:
            return None

        with self.ocr_lock:
            if self.ocr is None:
                self.load_model()
                assert self.ocr is not None

            assert block_img.dtype == np.uint8 and block_img.shape[-1] == 3
            H, W, C = block_img.shape

            result = self.ocr.predict(block_img)[0]

        result = validate_type(result, TextDetResult)

        dt_polys = np.asarray(result["dt_polys"], dtype=np.int32)
        dt_scores = np.asarray(result["dt_scores"], dtype=np.int32)

        if dt_polys.size == 0:
            print("[WARN] 텍스트를 인식하지 못함")
            return None

        lines = self._extract_lines(dt_polys, dt_scores)
        line_count = len(lines)
        line_height = float(self._estimate_line_height(block_img, lines))

        result = self._align_characters(block, block_img, lines)
        if result is None:
            font_family = "sans-serif"
            color = "#000000"
        else:
            font_family, color = result

        font_size = line_height / 1.2

        return BlockStyle(
            line_boxes=dt_polys.astype(np.int32),
            line_count=line_count,
            line_height=line_height,
            font_size=font_size,
            font_family=font_family,
            color=color,
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

    def _align_characters(self, block: BlockInfo, img_rgb: np.ndarray, lines: list[list[np.ndarray]]):
        for line in lines:
            font_colors = cast(list[np.ndarray], [])
            font_families = cast(list[FontAnalysisResult], [])

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

                # PSM: https://tesseract-ocr.github.io/tessdoc/ImproveQuality#page-segmentation-method
                data = pytesseract.image_to_boxes(segment_mask, lang="kor+eng", config="--psm 7 --oem 1")
                data = unicodedata.normalize("NFC", data)

                detections = cast(list[tuple[str, np.ndarray]], [])
                for x in data.split("\n"):
                    if len(x.strip()) == 0:
                        continue
                    a, b, c, d, e, _ = x.rsplit(maxsplit=5)
                    curr_box = np.array([b, c, d, e], dtype=np.int32)

                    curr_box = _expand_bbox_by_connected(segment_mask, curr_box)

                    detections.append((a, curr_box))

                # 한 글자만 들어있는 박스만 남김
                valid = cast(list[tuple[str, np.ndarray]], [])
                for ch, bbox in detections:
                    lang = "kor" if REGEX_KOR.match(ch) else "eng"
                    curr_segment = segment_mask[bbox[1] : bbox[3] + 1, bbox[0] : bbox[2] + 1]

                    pad_len = int(curr_segment.shape[0] * 0.1)
                    curr_segment = np.pad(curr_segment, [[pad_len, pad_len], [pad_len, pad_len]], constant_values=255)

                    data = pytesseract.image_to_string(curr_segment, lang=lang, config="--psm 8 --oem 1")
                    data = unicodedata.normalize("NFC", data).strip()

                    if ch == data:
                        valid.append((ch, bbox))

                if len(valid) == 0:
                    continue

                # 폰트 추정
                for ch, bbox in valid:
                    curr_segment = segment_gray[bbox[1] : bbox[3] + 1, bbox[0] : bbox[2] + 1]
                    if flip_bg:
                        curr_segment = 255 - curr_segment
                    else:
                        curr_segment = curr_segment.copy()

                    cv2.normalize(curr_segment, curr_segment, 0, 255, cv2.NORM_MINMAX)
                    font_families.append(self.font.find_best_match(ch, curr_segment))

                # 이미지 전체에서 글자색 추정
                indexing_mask = segment_mask[..., None] == 0
                indexing_mask = np.tile(indexing_mask, [1, 1, 3])
                font_colors.append(np.reshape(segment_rgb[indexing_mask], [-1, 3]))

        if len(font_colors) == 0:
            return None

        # 감마 보정을 고려해 색깔 평균냄
        font_colors = np.concat(font_colors, axis=0).astype(np.float32)
        font_colors **= 2.2
        font_color = np.mean(font_colors, axis=0)
        font_color = (font_color ** (1 / 2.2)).astype(np.uint8)
        color_r, color_g, color_b = map(int, font_color)
        color = f"#{color_r:02x}{color_g:02x}{color_b:02x}"

        font_family = FontAnalysisResult.merge_prediction(font_families).best_font()

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
            if doc != "financial2":
                continue
            if os.path.isdir(f"data/{doc}"):
                documents.append(layout_analyzer(doc))

    num_cpu = os.cpu_count() or 4

    with LayoutStyleAnalyzer() as layout_style_analyzer:
        with ThreadPoolExecutor(max_workers=num_cpu) as exe:
            for doc in documents[2:]:
                style_futures = cast(list[Future[BlockStyle | None]], [])

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
                        style_futures.append(exe.submit(layout_style_analyzer, block, block_img))

                style_futures_iter = iter(style_futures)

                for page in doc.pages:
                    for block in page.blocks:
                        try:
                            block.style = next(style_futures_iter).result()
                        except StopIteration:
                            raise RuntimeError("length of style_futures is inconsistent")
                        except KeyboardInterrupt:
                            exe.shutdown(wait=False, cancel_futures=True)
                            raise

                doc.save_as_cache()
