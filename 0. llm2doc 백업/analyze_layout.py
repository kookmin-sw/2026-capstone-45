"""문서 이미지 묶음을 OCR + 레이아웃 구조 데이터로 변환하는 모듈.

이 파일은 프로젝트의 입력 전처리 단계에 해당한다. 각 문서 폴더 안의
`original*` 이미지들을 읽어 PaddleOCR-VL로 분석하고, 텍스트/표/이미지
블록 정보를 `ParsedDocument` 형태로 캐시해 이후 검색/생성 단계에서 재사용한다.
"""

import numpy as np
import json
import os
import gc
import re
import paddle
import pickle

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from beartype import beartype
from PIL import Image
from paddleocr import PaddleOCRVL
from paddlex.inference.pipelines.paddleocr_vl.result import (
    PaddleOCRVLResult,
    PaddleOCRVLBlock,
)

from .util import validate_type


REGEX_NEWLINE = re.compile(r"[\r\n]+")


@beartype
@dataclass
class BlockInfo:
    """페이지 안의 단일 블록을 표현한다.

    `label`은 OCR 모델이 판별한 블록 종류이고, `content`는 실제 텍스트/HTML,
    `bbox`는 원본 이미지 좌표계의 위치다. `is_text`, `is_image`, `is_html`은
    후속 렌더링 단계가 블록을 어떻게 처리할지 빠르게 판단하기 위한 플래그다.
    """

    label: str
    content: str
    bbox: list[int]
    is_text: bool
    is_image: bool
    is_html: bool

    def to_structured_html(self, page: "ParsedPage", indent: int = 0, block_id: str | None = None) -> str:
        """블록을 프로젝트 내부 공통 HTML 표현으로 직렬화한다."""
        result = []

        bbox = [
            self.bbox[0] * 1000 // page.width,
            self.bbox[1] * 1000 // page.height,
            self.bbox[2] * 1000 // page.width,
            self.bbox[3] * 1000 // page.height,
        ]
        bbox_str = ", ".join([str(x) for x in bbox])

        result.append(' ' * indent)
        result.append(f'<div id="{block_id}" data-bbox="[{bbox_str}]">\n')

        if self.is_text:
            for line in REGEX_NEWLINE.split(self.content.strip()):
                result.append(' ' * indent)
                result.append("  <p>")
                result.append(
                    line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                result.append("</p>\n")
        elif self.is_image:
            result.append(' ' * indent)
            result.append(f'  <img src="/{block_id}/image">\n')
        elif self.is_html:
            result.append(' ' * indent)
            result.append('  ')
            result.append(self.content)
            result.append("\n")
        else:
            print("[WARN] Block has no is_* directive")

        result.append(' ' * indent)
        result.append("</div>")

        return ''.join(result)


@beartype
@dataclass
class ParsedPage:
    """OCR 결과를 페이지 단위로 묶어 보관한다."""

    width: int
    height: int
    blocks: list[BlockInfo]
    screenshot: Image.Image
    json: str
    markdown: str
    markdown_images: dict[str, Image.Image]

    def __str__(self):
        content = "\n\n".join(
            [f"Block #{i}\n{blk}" for i, blk in enumerate(self.blocks)]
        )
        return f"#####\n{content}\n#####"

    def to_structured_html(self, indent: int = 0, page_id: str | None = None) -> str:
        """페이지 전체를 `<page>...</page>` 구조로 직렬화한다."""
        result = []
        result.append(' ' * indent)
        result.append(f'<page id="{page_id}">\n')

        for i, block in enumerate(self.blocks):
            if page_id is None:
                block_id = f"block-{i + 1}"
            else:
                block_id = f"{page_id}-block-{i + 1}"

            result.append(
                block.to_structured_html(self, indent=indent + 2, block_id=block_id)
            )
            result.append('\n')

        result.append(' ' * indent)
        result.append("</page>\n")

        return "".join(result)


@beartype
@dataclass
class ParsedDocument:
    """여러 페이지로 이루어진 문서 전체를 표현한다."""

    id: str
    pages: list[ParsedPage]
    concatenated_markdown: str

    def to_sturctured_html(self, indent: int = 0, doc_id: str | None = None) -> str:
        """문서 전체를 `<document>...</document>` 포맷으로 내보낸다."""
        result = []

        result.append(' ' * indent)
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
            result.append('\n')

        result.append(' ' * indent)
        result.append("</document>")

        return "".join(result)


@beartype
class LayoutAnalyzer:
    def __init__(self, data_root: str | os.PathLike[str] = "data"):
        """문서 데이터 루트를 기준으로 OCR 파이프라인 래퍼를 준비한다."""
        self.pipeline: PaddleOCRVL | None = None
        self.data_root = Path(data_root)

    def load_model(self):
        """실제 OCR 파이프라인을 지연 로딩한다."""
        # 데모 프로그램의 세팅을 그대로 이용
        self.pipeline = PaddleOCRVL(
            use_layout_detection=True,
            merge_layout_blocks=True,
        )

    @classmethod
    def clear_cache(cls, data_root: str | os.PathLike[str] = "data", doc_id: str | None = None):
        """저장된 `layout.pickle` 캐시를 삭제한다."""
        root = Path(data_root)
        if not root.exists():
            return

        def clear_one(d: Path):
            cache_path = d / "generated" / "layout.pickle"
            if d.is_dir() and cache_path.exists():
                cache_path.unlink()
                print(f"[INFO] Cleared cache for {d.name}")

        if doc_id:
            clear_one(root / doc_id)
        else:
            for doc_dir in root.iterdir():
                clear_one(doc_dir)

    def __call__(self, doc: str) -> ParsedDocument:
        # 문서 폴더를 읽어 `ParsedDocument`를 만들고, 가능하면 캐시를 재사용한다.
        """
        주어진 데이터의 이미지를 순서대로 분석함.
        """

        doc_dir = self.data_root / doc
        cache_path = doc_dir / "generated" / "layout.pickle"

        if not doc_dir.exists():
            raise FileNotFoundError(f"document directory does not exist: {doc_dir}")

        if cache_path.exists():
            with open(cache_path, "rb") as f:
                return pickle.load(f)

        file_paths = [x.name for x in doc_dir.iterdir() if x.is_file() and x.name.startswith("original")]
        file_paths.sort()
        pages = [Image.open(doc_dir / x) for x in file_paths]

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

        concatenated_markdown = self.pipeline.concatenate_markdown_pages(
            [x.markdown for x in pages_output]
        )

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

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "wb") as f:
            pickle.dump(ret, f)

        return ret

    def dispose(self):
        """모델 참조를 해제하고 가능한 경우 GPU 메모리까지 정리한다."""
        self.pipeline = None
        gc.collect()
        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count():
            paddle.device.cuda.empty_cache()


def recreate_cache(data_root: str | os.PathLike[str] = "data"):
    """데이터 루트의 모든 문서 캐시를 다시 생성한다."""
    populate_cache(clear=True, data_root=data_root)


def populate_cache(
    clear: bool = False,
    doc_ids: list[str] | None = None,
    data_root: str | os.PathLike[str] = "data",
):
    """선택한 문서들에 대해 OCR 캐시를 미리 생성해 둔다."""
    root = Path(data_root)
    if doc_ids is None:
        # 지정된 폴더가 없으면 data 폴더 내의 모든 디렉토리 대상
        doc_ids = [d.name for d in root.iterdir() if d.is_dir()]

    if clear:
        for doc_id in doc_ids:
            LayoutAnalyzer.clear_cache(data_root=data_root, doc_id=doc_id)

    layout_analyzer = LayoutAnalyzer(data_root=data_root)

    for doc_id in doc_ids:
        print(f"[INFO] Analyzing folder: {doc_id}")
        layout_analyzer(doc_id)

    layout_analyzer.dispose()
