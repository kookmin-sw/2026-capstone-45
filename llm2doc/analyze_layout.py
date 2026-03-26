import numpy as np
import json

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


@beartype
@dataclass
class ParseResult:
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
class LayoutAnalyzer:
    def __init__(self):
        # 데모 프로그램의 세팅을 그대로 이용
        self.pipeline = PaddleOCRVL(
            use_layout_detection=True,
            merge_layout_blocks=True,
        )

    def __call__(self, pages: list[Image.Image]) -> list[ParseResult]:
        """
        주어진 이미지를 순서대로 분석함.
        """

        pages_arrays = []
        for img in pages:
            img = img.convert("RGB")
            img_arr = np.asarray(img)[..., ::-1].copy()
            pages_arrays.append(img_arr)

        pages_output = validate_type(
            self.pipeline.predict(pages_arrays), list[PaddleOCRVLResult]
        )
        assert len(pages) == len(pages_output)

        result = []

        for output in pages_output:
            as_json = json.dumps(output.json)
            as_markdown = output.markdown

            blocks = []
            for block in output["parsing_res_list"]:
                block = validate_type(block, PaddleOCRVLBlock)

                blocks.append(
                    BlockInfo(
                        label=block.label,
                        content=block.content,
                        bbox=block.bbox,
                    )
                )

            result.append(
                ParseResult(
                    blocks=blocks,
                    json=as_json,
                    markdown=as_markdown["markdown_texts"],
                    markdown_images=as_markdown["markdown_images"],
                )
            )

        return result


def main():
    layout_analyzer = LayoutAnalyzer()
    layout = layout_analyzer([Image.open("data/financial1/original-00.png")])[0]
    print(layout)


if __name__ == "__main__":
    main()
