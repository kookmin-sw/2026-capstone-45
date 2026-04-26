import gc
import numpy as np
import paddle
import asyncio

from typing import Awaitable, Any
from concurrent.futures import Executor, Future
from paddleocr import TextDetection
from paddlex.inference.models.text_detection.result import TextDetResult
from tesserocr import OEM, PSM

from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.artifact.style._artifact import StyleArtifact, BlockStyle
from llm2doc.artifact.style._font_analyzer import FontAnalyzer
from llm2doc.artifact.style._character import StyleAnalyzeContext, analyze_single_block
from llm2doc.util import validate_type
from llm2doc.tesseract import download_tessdata, TesseractFleet


class StyleArtifactPipeline(ArtifactPipeline[StyleArtifact]):
    ARTIFACT = StyleArtifact
    ARTIFACT_NAME = "StyleArtifact"
    INPUT_ARTIFACTS = ["OCRArtifact"]

    def __init__(self):
        download_tessdata()
        self.tesseract_line = TesseractFleet(path="./tessdata", lang="eng+kor", oem=OEM.DEFAULT, psm=PSM.SINGLE_LINE)
        self.tesseract_char = TesseractFleet(path="./tessdata", lang="eng+kor", oem=OEM.DEFAULT, psm=PSM.SINGLE_CHAR)

        self.ocr = TextDetection(
            model_name="PP-OCRv5_server_det",
            box_thresh=0.2,
        )
        self.font = FontAnalyzer()

        self.tesseract_char.__enter__()
        self.tesseract_line.__enter__()

    def process(self, document):
        from llm2doc.artifact.ocr import OCRArtifactPipeline

        ocr_doc = document.get_artifact(OCRArtifactPipeline)
        ocr_results: list[list[TextDetResult]] = []

        for i, page in enumerate(ocr_doc.pages):
            page_img = np.asarray(document.images[i].convert("RGB"))
            page_img = page_img.view()
            page_img.flags.writeable = False

            ocr_results.append([])

            for block in page.blocks:
                xmin, ymin, xmax, ymax = block.bbox
                block_img = page_img[ymin:ymax, xmin:xmax]

                ocr_result = self.ocr.predict(block_img)[0]
                ocr_result = validate_type(ocr_result, TextDetResult)

                ocr_results[-1].append(ocr_result)

        async def inner():
            futures: list[Awaitable[list[BlockStyle | None]]] = []

            for i, page in enumerate(ocr_doc.pages):
                page_img = np.asarray(document.images[i].convert("RGB"))
                page_img = page_img.view()
                page_img.flags.writeable = False

                page_futures: list[Awaitable[BlockStyle | None]] = []

                for j, block in enumerate(page.blocks):
                    xmin, ymin, xmax, ymax = block.bbox
                    block_img = page_img[ymin:ymax, xmin:xmax]
                    text_det = ocr_results[i][j]

                    analyzer_ctx = StyleAnalyzeContext(
                        font=self.font,
                        block=block,
                        text_det=text_det,
                        block_img=block_img,
                        exe=self.ctx.thread_pool,
                        tesseract_line=self.tesseract_line,
                        tesseract_char=self.tesseract_char,
                    )
                    page_futures.append(analyze_single_block(analyzer_ctx))

                futures.append(asyncio.gather(*page_futures))

            return await asyncio.gather(*futures)

        results = asyncio.run(inner())
        return StyleArtifact(pages=results)

    def dispose(self):
        del self.ocr
        gc.collect()
        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count():
            paddle.device.cuda.empty_cache()

        self.tesseract_char.__exit__(None, None, None)
        self.tesseract_line.__exit__(None, None, None)
