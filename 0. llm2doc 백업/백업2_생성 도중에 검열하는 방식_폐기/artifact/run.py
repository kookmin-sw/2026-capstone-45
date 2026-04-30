import asyncio
import os
import json

from pathlib import Path
from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence, Type, TypeVar
from beartype import beartype
from pydantic import BaseModel
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tqdm import tqdm

from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.artifact.ocr import OCRArtifact, OCRPage, OCRBlock, OCRArtifactPipeline
from llm2doc.artifact.style import StyleArtifactPipeline
from llm2doc.artifact.semantic import SemanticArtifactPipeline
from llm2doc.context.document import DocumentContext
from llm2doc.context.pipeline import PipelineContext
from llm2doc.entity import Document
from llm2doc.repository.artifact import load_artifact, save_artifact
from llm2doc.util import join_thread_async


PIPELINES: Sequence[Type[ArtifactPipeline]] = [
    OCRArtifactPipeline,
    StyleArtifactPipeline,
    SemanticArtifactPipeline,
]


def _artifact_log(message: str):
    tqdm.write(f"[artifact] {message}")


def _load_precomputed_ocr(display_name: str) -> OCRArtifact | None:
    doc_stem = Path(display_name).stem
    layout_path = Path("data") / doc_stem / "generated" / "layout.pickle.json"
    if not layout_path.is_file():
        return None

    with layout_path.open("rt", encoding="utf-8") as f:
        payload = json.load(f)

    pages: list[OCRPage] = []
    for page_payload in payload.get("pages", []):
        blocks: list[OCRBlock] = []
        markdown_parts: list[str] = []

        for block_payload in page_payload.get("blocks", []):
            block = OCRBlock(
                label=str(block_payload.get("label") or "text"),
                content=str(block_payload.get("content") or ""),
                bbox=[int(x) for x in block_payload.get("bbox", [0, 0, 0, 0])],
            )
            blocks.append(block)
            if block.content.strip():
                markdown_parts.append(block.content.strip())

        pages.append(
            OCRPage(
                width=int(page_payload["width"]),
                height=int(page_payload["height"]),
                blocks=blocks,
                content_json=json.dumps(page_payload, ensure_ascii=False),
                content_markdown="\n\n".join(markdown_parts),
            )
        )

    if not pages:
        return None

    return OCRArtifact(pages=pages)


@beartype
def _build_artifact_inner(
    pipeline_ctx: PipelineContext,
    doc_ids: Sequence[int],
    file_paths: Sequence[Sequence[str]],
    artifacts: Sequence[dict[str, BaseModel]],
):
    images = [[Image.open(x) for x in pages] for pages in file_paths]
    doc_inputs = list(zip(doc_ids, images, artifacts))

    for pipeline in tqdm(PIPELINES, desc="Artifact pipelines", unit="pipeline"):
        _artifact_log(f"start {pipeline.ARTIFACT_NAME}")

        if all(pipeline.ARTIFACT_NAME in doc_artifacts for doc_artifacts in artifacts):
            _artifact_log(f"skip {pipeline.ARTIFACT_NAME} (cached)")
            continue

        now = pipeline(pipeline_ctx)
        try:
            for doc_id, pages, doc_artifacts in tqdm(
                doc_inputs,
                desc=pipeline.ARTIFACT_NAME,
                unit="doc",
                leave=False,
            ):
                _artifact_log(
                    f"processing doc_id={doc_id}, pipeline={pipeline.ARTIFACT_NAME}, pages={len(pages)}"
                )

                if any(x not in doc_artifacts for x in pipeline.INPUT_ARTIFACTS):
                    raise ValueError("PIPELINES order is invalid")

                if pipeline.ARTIFACT_NAME in doc_artifacts:
                    _artifact_log(f"skip doc_id={doc_id}, pipeline={pipeline.ARTIFACT_NAME} (cached)")
                    continue

                doc = DocumentContext(
                    doc_id=doc_id,
                    images=pages,
                    artifacts=doc_artifacts,
                )
                result = now.process(doc)
                doc_artifacts[now.ARTIFACT_NAME] = result
                _artifact_log(f"done doc_id={doc_id}, pipeline={pipeline.ARTIFACT_NAME}")
        finally:
            now.dispose()

        _artifact_log(f"finish {pipeline.ARTIFACT_NAME}")


async def build_artifact(engine: AsyncEngine, doc_ids: Sequence[int]):
    loop = asyncio.get_running_loop()

    cpu_count = os.cpu_count() or 4

    with ThreadPoolExecutor(max_workers=cpu_count) as exe:
        pipeline_ctx = PipelineContext(
            loop=loop,
            engine=engine,
            thread_pool=exe,
        )

        artifacts: list[dict[str, BaseModel]] = []
        file_paths: list[list[str]] = []

        async with pipeline_ctx.with_db() as db:
            for i, doc_id in enumerate(doc_ids):
                doc = await db.get_one(Document, doc_id)
                image_rows = (await db.execute(doc.images.select())).scalars().all()
                file_ids = [x.file_id for x in image_rows]

                artifacts.append(dict())
                file_paths.append([f"file/{x}" for x in file_ids])

                for pipeline in PIPELINES:
                    loaded = await load_artifact(db, doc_id, pipeline)
                    if loaded is not None:
                        artifacts[i][pipeline.ARTIFACT_NAME] = loaded

                if OCRArtifactPipeline.ARTIFACT_NAME not in artifacts[i]:
                    precomputed_ocr = _load_precomputed_ocr(doc.display_name)
                    if precomputed_ocr is not None:
                        artifacts[i][OCRArtifactPipeline.ARTIFACT_NAME] = precomputed_ocr
                        _artifact_log(
                            f"loaded precomputed OCRArtifact doc_id={doc_id}, display_name={doc.display_name}"
                        )

        thread = Thread(target=_build_artifact_inner, args=(pipeline_ctx, doc_ids, file_paths, artifacts))
        thread.start()

        await join_thread_async(thread)

        async with pipeline_ctx.with_db() as db:
            for i, doc_id in enumerate(doc_ids):
                for name, value in artifacts[i].items():
                    await save_artifact(db, doc_id, name, value)


T = TypeVar("T", bound=BaseModel)


async def get_or_build_artifact(engine: AsyncEngine, doc_id: int, pipeline: Type[ArtifactPipeline[T]]) -> T:
    async with AsyncSession(engine) as db:
        async with db.begin():
            loaded = await load_artifact(db, doc_id, pipeline)
            if loaded is not None:
                return loaded

    await build_artifact(engine, [doc_id])

    async with AsyncSession(engine) as db:
        async with db.begin():
            loaded = await load_artifact(db, doc_id, pipeline)
            if loaded is not None:
                return loaded

    raise RuntimeError(f"Failed to build artifact {pipeline.ARTIFACT_NAME} for document {doc_id}")
