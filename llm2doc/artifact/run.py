import asyncio
import os

from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence, Type
from beartype import beartype
from pydantic import BaseModel
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncEngine

from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.artifact.ocr import OCRArtifactPipeline
from llm2doc.artifact.style import StyleArtifactPipeline
from llm2doc.context.document import DocumentContext
from llm2doc.context.pipeline import PipelineContext
from llm2doc.entity import Document
from llm2doc.util import join_thread_async


PIPELINES: Sequence[Type[ArtifactPipeline]] = [
    OCRArtifactPipeline,
    StyleArtifactPipeline,
]


@beartype
def _build_artifact_inner(
    pipeline_ctx: PipelineContext,
    doc_ids: Sequence[int],
    file_paths: Sequence[Sequence[str]],
    artifacts: Sequence[dict[str, BaseModel]],
):
    images = [Image.open(x) for pages in file_paths for x in pages]

    for pipeline in PIPELINES:
        now = pipeline(pipeline_ctx)
        try:
            for doc_id, pages, doc_artifacts in zip(doc_ids, images, artifacts):
                if any(x not in doc_artifacts for x in pipeline.INPUT_ARTIFACTS):
                    raise ValueError("PIPELINES order is invalid")
                doc = DocumentContext(
                    doc_id=doc_id,
                    images=images,
                    artifacts=doc_artifacts,
                )
                result = now.process(doc)
                doc_artifacts[now.ARTIFACT_NAME] = result
        finally:
            now.dispose()


async def build_artifact(engine: AsyncEngine, doc_ids: Sequence[int]):
    loop = asyncio.get_running_loop()

    cpu_count = os.cpu_count() or 4

    with ThreadPoolExecutor(max_workers=cpu_count) as exe:
        pipeline_ctx = PipelineContext(
            loop=loop,
            engine=engine,
            thread_pool=exe,
        )

        artifacts: list[dict[str, BaseModel]] = [dict() for _ in doc_ids]
        file_paths: list[list[str]] = [[] for _ in doc_ids]

        async with pipeline_ctx.with_db() as db:
            for doc_id in doc_ids:
                doc = await db.get_one(Document, doc_id)
                image_rows = (await db.execute(doc.images.select())).scalars().all()
                file_ids = [x.file_id for x in image_rows]
                file_paths.append([f"file/{x}" for x in file_ids])

                # TODO: Load artifacts

        thread = Thread(target=_build_artifact_inner, args=(pipeline_ctx, doc_ids, file_paths, artifacts))
        thread.start()

        await join_thread_async(thread)

        async with pipeline_ctx.with_db() as db:
            # TODO: Store artifacts
            pass
