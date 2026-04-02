import numpy as np
import json
import os
import gc
import re
import paddle
import pickle

from dataclasses import dataclass
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
    label: str
    content: str
    bbox: list[int]
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
    id: str
    pages: list[ParsedPage]
    concatenated_markdown: str

    def to_sturctured_html(self, indent: int = 0, doc_id: str | None = None) -> str:
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
    def __init__(self):
        self.pipeline: PaddleOCRVL | None = None

    def load_model(self):
        # 데모 프로그램의 세팅을 그대로 이용
        self.pipeline = PaddleOCRVL(
            use_layout_detection=True,
            merge_layout_blocks=True,
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

        os.makedirs(f"data/{doc}/generated/", exist_ok=True)
        with open(f"data/{doc}/generated/layout.pickle", "wb") as f:
            pickle.dump(ret, f)

        return ret

    def dispose(self):
        self.pipeline = None
        gc.collect()
        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count():
            paddle.device.cuda.empty_cache()


def recreate_cache():
    LayoutAnalyzer.clear_cache()

    layout_analyzer = LayoutAnalyzer()

    for doc in os.listdir("data"):
        if os.path.isdir(f"data/{doc}"):
            layout_analyzer(doc)
