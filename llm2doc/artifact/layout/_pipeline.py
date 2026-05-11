import asyncio
import os

from PIL import ImageDraw
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import Literal, Awaitable

from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.artifact.ocr import OCRArtifact, OCRArtifactPipeline
from llm2doc.artifact.layout._artifact import LayoutArtifact
from llm2doc.context.pipeline import PipelineContext
from llm2doc.context.document import DocumentContext
from llm2doc.util import image_as_data_uri


LAYOUT_CLASSIFY_SYSTEM_PROMPT = """
You are an AI assistant.

# Task
You need to classify each box into one of following categories:
* **fixed**: Placed at an absolute page location (it would not move). Visually, these are headers, footers, marginalia, floating callout boxes, or any element that does not flow with main text.
* **block**: Stacks vertically (it would move up/down). Visually, these interrupt the vertical flow. Text stops above it and resumes below it. This includes full-width paragraphs, but also centered titles or charts that have empty whitespace to their left/right.
* **inline**: Flows horizontally (it would move in any direction within the text). Visually, these are embedded inside a line. They sit on the same baseline as adjacent elements, with text immediately to their left or right.

# Input format
You'll be given with an screenshot of the page and bounding box. Bounding box has [xmin, ymin, xmax, ymax] format.

Transcription of that box will be provided if available. If not available, it might be either due to OCR failure, or graphics (not text).

# Output format
Write a JSON without any other text. No code block, no explanation, but just pure JSON.

**Never** write code block (```).

Your previous attempt resulted in parse error. Take extra care on formatting.

# Input example

## Image
(image would go here)

## Text transcription
Lorem ipsum

## Box
[100,100,900,200]

# Output example
{"category":"block"}
"""


class LayoutClassifyOutput(BaseModel):
    category: Literal["fixed"] | Literal["block"] | Literal["inline"]


class LayoutArtifactPipeline(ArtifactPipeline[LayoutArtifact]):
    ARTIFACT = LayoutArtifact
    ARTIFACT_NAME = "LayoutArtifact"
    INPUT_ARTIFACTS = ["OCRArtifact"]

    ctx: PipelineContext

    def __init__(self, ctx: PipelineContext):
        super().__init__(ctx)
        self.ctx = ctx
        self.openai = AsyncOpenAI(
            base_url=os.environ["OPENAI_BASE_URL"],
            api_key=os.environ["OPENAI_API_KEY"],
        )

    def process(self, document: DocumentContext) -> LayoutArtifact:
        return asyncio.run_coroutine_threadsafe(self.process_impl(document), self.ctx.loop).result()

    async def process_impl(self, document: DocumentContext) -> LayoutArtifact:
        tasks: list[Awaitable[list[LayoutClassifyOutput]]] = []

        ocr = document.get_artifact(OCRArtifactPipeline)

        for i, page in enumerate(ocr.pages):
            image_url = image_as_data_uri(document.images[0])

            curr_page_tasks: list[Awaitable[LayoutClassifyOutput]] = []

            for j in range(len(page.blocks)):
                curr_page_tasks.append(self.classify_single_block(document, ocr, image_url, i, j))

            tasks.append(asyncio.gather(*curr_page_tasks))

        outputs = await asyncio.gather(*tasks)

        for i, page in enumerate(outputs):
            img = document.images[i].copy()
            draw = ImageDraw.Draw(img)

            color_map = {"fixed": "red", "block": "blue", "inline": "green"}

            ocr_page = ocr.pages[i]
            for j, block in enumerate(ocr_page.blocks):
                category = page[j].category
                color = color_map.get(category, "yellow")

                x1, y1, x2, y2 = block.bbox
                draw.rectangle([x1, y1, x2, y2], outline=color, width=2)

            img.save(f"debug_{i}.png")

        raise RuntimeError("todo")

    async def classify_single_block(
        self, document: DocumentContext, ocr: OCRArtifact, image_url: str, page_idx: int, block_idx: int
    ) -> LayoutClassifyOutput:
        page = ocr.pages[page_idx]

        w = page.width
        h = page.height

        block = page.blocks[block_idx]

        box_text = "(graphics)" if block.is_image else block.content.strip()

        x1, y1, x2, y2 = block.bbox
        box = [x1 * 1000 // w, y1 * 1000 // h, x2 * 1000 // w, y2 * 1000 // h]
        box_str = repr(box).replace(" ", "")

        fail_cnt = 0

        while fail_cnt < 1:
            try:
                response = await self.openai.responses.create(
                    model=os.environ["OPENAI_MODEL"],
                    reasoning={"effort": "low"},
                    input=[
                        {
                            "role": "system",
                            "content": [{"type": "input_text", "text": LAYOUT_CLASSIFY_SYSTEM_PROMPT}],
                        },
                        {  # type: ignore
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "# Image"},
                                {"type": "input_image", "image_url": image_url},
                                {"type": "input_text", "text": f"# Text transcription\n\n{box_text}\n# Box\n{box_str}"},
                            ],
                        },
                    ],
                )

                await document.append_log(
                    f"[LayoutArtifactPipeline] page={page_idx}, block={block_idx} " + response.model_dump_json()
                )

                text = response.output_text.strip()

                if text.startswith("```json"):
                    text = text[7:]

                if text.startswith("```"):
                    text = text[3:]

                if text.endswith("```"):
                    text = text[:-3]

                text = text.strip()

                return LayoutClassifyOutput.model_validate_json(text)
            except Exception as e:
                await document.append_log(f"[LayoutArtifactPipeline] page={page_idx}, block={block_idx} " + repr(e))
                fail_cnt += 1

        raise RuntimeError("Could not parse layout info")

    def dispose(self):
        asyncio.run_coroutine_threadsafe(self.openai.close(), self.ctx.loop).result()
        return
