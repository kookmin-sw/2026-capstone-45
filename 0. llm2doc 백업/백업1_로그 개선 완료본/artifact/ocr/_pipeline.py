import gc
import json
import paddle
import numpy as np

from typing import Any
from paddleocr import PaddleOCRVL
from paddlex.inference.pipelines.paddleocr_vl.result import PaddleOCRVLResult, PaddleOCRVLBlock
from tqdm import tqdm

from llm2doc.artifact.ocr._artifact import OCRArtifact, OCRPage, OCRBlock
from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.context.pipeline import PipelineContext
from llm2doc.context.document import DocumentContext
from llm2doc.util import validate_type


class OCRArtifactPipeline(ArtifactPipeline[OCRArtifact]):
    """
    문서 이미지를 입력으로 받아 PaddleOCR-VL을 실행한다
    """

    ARTIFACT = OCRArtifact
    ARTIFACT_NAME = "OCRArtifact"
    INPUT_ARTIFACTS = []

    def __init__(self, ctx: PipelineContext):
        super().__init__(ctx)

        self.ocr = PaddleOCRVL(
            use_layout_detection=True,
            merge_layout_blocks=True,
            layout_nms=True,
        )

    def process(self, document: DocumentContext) -> OCRArtifact:
        pages = []
        for img in document.images:
            img = img.convert("RGB")
            img_arr = np.asarray(img)[..., ::-1].copy()
            pages.append(img_arr)

        pages_output = []
        for i, page in enumerate(tqdm(pages, desc=f"OCR doc_id={document.doc_id}", unit="page"), start=1):
            tqdm.write(f"[ocr] predict doc_id={document.doc_id}, page={i}/{len(pages)}")
            page_output = self.ocr.predict([page])
            pages_output.extend(page_output)
            tqdm.write(f"[ocr] done doc_id={document.doc_id}, page={i}/{len(pages)}")

        assert len(pages_output) == len(pages)

        tqdm.write(f"[ocr] restructure doc_id={document.doc_id}, pages={len(pages_output)}")
        pages_output = self.ocr.restructure_pages(
            pages_output,
            merge_tables=False,
            relevel_titles=True,
            concatenate_pages=False,
        )
        tqdm.write(f"[ocr] restructure done doc_id={document.doc_id}")
        pages_output = validate_type(pages_output, list[PaddleOCRVLResult])
        assert len(pages_output) == len(document.images)

        # 당장은 필요 없어서 주석처리함
        # concatenated_markdown = self.pipeline.concatenate_markdown_pages([x.markdown for x in pages_output])

        # VRAM OOM 완화
        self.free_vram()

        parsed_pages = []

        for i, output in enumerate(tqdm(pages_output, desc=f"OCR parse doc_id={document.doc_id}", unit="page")):
            as_json = json.dumps(output.json, ensure_ascii=False)
            as_markdown: Any = output.markdown

            blocks = []
            for block in output["parsing_res_list"]:
                block = validate_type(block, PaddleOCRVLBlock)

                blocks.append(
                    OCRBlock(
                        label=block.label,
                        content=block.content,
                        bbox=block.bbox,
                    )
                )

            # TODO: Handle markdown_images

            parsed_pages.append(
                OCRPage(
                    width=document.images[i].width,
                    height=document.images[i].height,
                    blocks=blocks,
                    content_json=as_json,
                    content_markdown=as_markdown["markdown_texts"],
                )
            )

        return OCRArtifact(
            pages=parsed_pages,
        )

    def __exit__(self, exc_type, exc, tb):
        # VRAM 정리
        self.pipeline = None
        self.free_vram()

    def free_vram(self):
        gc.collect()
        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count():
            paddle.device.cuda.empty_cache()
