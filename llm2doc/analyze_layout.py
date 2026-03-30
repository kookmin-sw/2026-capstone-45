import numpy as np
import json
import os
import gc
import paddle
import pickle

from dataclasses import dataclass
from beartype import beartype
from PIL import Image
from paddleocr import PaddleOCRVL
from paddlex.inference.pipelines.paddleocr_vl.result import (
    PaddleOCRVLResult,
    PaddleOCRVLBlock,
)

from .util import validate_type


@beartype
@dataclass
class BlockInfo:
    label: str
    content: str
    bbox: list[int]
    is_text: bool
    is_image: bool
    is_html: bool


@beartype
@dataclass
class ParsedPage:
    width: int
    height: int
    blocks: list[BlockInfo]
    json: str
    markdown: str
    markdown_images: dict[str, Image.Image]

    def __str__(self):
        content = "\n\n".join(
            [f"Block #{i}\n{blk}" for i, blk in enumerate(self.blocks)]
        )
        return f"#####\n{content}\n#####"


@beartype
@dataclass
class ParsedDocument:
    pages: list[ParsedPage]
    concatenated_markdown: str


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

    def __call__(self, data: str) -> ParsedDocument:
        """
        주어진 데이터의 이미지를 순서대로 분석함.
        """

        if os.path.exists(f"data/{data}/generated/layout.pickle"):
            with open(f"data/{data}/generated/layout.pickle", "rb") as f:
                return pickle.load(f)

        file_paths = [x for x in os.listdir(f"data/{data}") if x.startswith("original")]
        file_paths.sort()
        pages = [Image.open(f"data/{data}/{x}") for x in file_paths]

        if self.pipeline is None:
            self.load_model()

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
            as_markdown = output.markdown

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
                    json=as_json,
                    markdown=as_markdown["markdown_texts"],
                    markdown_images=as_markdown["markdown_images"],
                )
            )

        ret = ParsedDocument(
            pages=parsed_pages,
            concatenated_markdown=concatenated_markdown,
        )

        os.makedirs(f"data/{data}/generated/", exist_ok=True)
        with open(f"data/{data}/generated/layout.pickle", "wb") as f:
            pickle.dump(ret, f)

        return ret

    def dispose(self):
        self.pipeline = None
        gc.collect()
        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count():
            paddle.device.cuda.empty_cache()


def main():
    LayoutAnalyzer.clear_cache()

    layout_analyzer = LayoutAnalyzer()
    layout = layout_analyzer("financial1")

    print(layout)


if __name__ == "__main__":
    main()
