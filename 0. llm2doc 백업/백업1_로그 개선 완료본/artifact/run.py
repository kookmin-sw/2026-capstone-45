import asyncio
import logging
import os

from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence, Type, TypeVar
from beartype import beartype
from pydantic import BaseModel
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.artifact.ocr import OCRArtifactPipeline
from llm2doc.artifact.style import StyleArtifactPipeline
from llm2doc.artifact.semantic import SemanticArtifactPipeline
from llm2doc.context.document import DocumentContext
from llm2doc.context.pipeline import PipelineContext
from llm2doc.entity import Document
from llm2doc.entity.document import DocumentStatus
from llm2doc.repository.artifact import load_artifact, save_artifact
from llm2doc.util import join_thread_async


PIPELINES: Sequence[Type[ArtifactPipeline]] = [
    OCRArtifactPipeline,
    StyleArtifactPipeline,
    SemanticArtifactPipeline,
]


async def _update_log_status(db: AsyncSession, doc_id: int, status: DocumentStatus, log: str):
    doc = await db.get_one(Document, doc_id)

    doc.process_status = status
    doc.process_log += f"{log}\n"


@beartype
def _build_artifact_inner(
    pipeline_ctx: PipelineContext,
    doc_ids: Sequence[int],
    file_paths: Sequence[Sequence[str]],
    artifacts: Sequence[dict[str, BaseModel]],
):
    images = [[Image.open(x) for x in pages] for pages in file_paths]

    for pipeline in PIPELINES:
        if all(pipeline.ARTIFACT_NAME in doc_artifacts for doc_artifacts in artifacts):
            continue

        now = pipeline(pipeline_ctx)
        try:
            for doc_id, pages, doc_artifacts in zip(doc_ids, images, artifacts):
                if any(x not in doc_artifacts for x in pipeline.INPUT_ARTIFACTS):
                    raise ValueError("PIPELINES order is invalid")

                if pipeline.ARTIFACT_NAME in doc_artifacts:
                    continue

                doc = DocumentContext(
                    doc_id=doc_id,
                    images=pages,
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

        async with pipeline_ctx.with_db() as db:
            for doc_id in doc_ids:
                await _update_log_status(db, doc_id, DocumentStatus.PROCESSING, "Starting artifact build...")

        existing_artifacts: list[set[str]] = []
        artifacts: list[dict[str, BaseModel]] = []
        file_paths: list[list[str]] = []

        async with pipeline_ctx.with_db() as db:
            for i, doc_id in enumerate(doc_ids):
                doc = await db.get_one(Document, doc_id)
                image_rows = (await db.execute(doc.images.select())).scalars().all()
                file_ids = [x.file_id for x in image_rows]

                artifacts.append(dict())
                existing_artifacts.append(set())
                file_paths.append([f"file/{x}" for x in file_ids])

                for pipeline in PIPELINES:
                    loaded = await load_artifact(db, doc_id, pipeline)
                    if loaded is not None:
                        artifacts[i][pipeline.ARTIFACT_NAME] = loaded
                        existing_artifacts[i].add(pipeline.ARTIFACT_NAME)

        build_errors: list[BaseException] = []

        def run_inner():
            try:
                _build_artifact_inner(pipeline_ctx, doc_ids, file_paths, artifacts)
            except BaseException as exc:
                logging.exception("Failed to build artifacts")
                build_errors.append(exc)

        thread = Thread(target=run_inner)
        thread.start()

        await join_thread_async(thread)

        if build_errors:
            async with pipeline_ctx.with_db() as db:
                for doc_id in doc_ids:
                    await _update_log_status(db, doc_id, DocumentStatus.ERROR, repr(build_errors[0]))
            raise build_errors[0]

        async with pipeline_ctx.with_db() as db:
            for i, doc_id in enumerate(doc_ids):
                for name, value in artifacts[i].items():
                    # 새로운 아티팩트가 있으면 저장
                    if name not in existing_artifacts[i]:
                        await save_artifact(db, doc_id, name, value)

        async with pipeline_ctx.with_db() as db:
            for i, doc_id in enumerate(doc_ids):
                if len(artifacts[i]) == len(PIPELINES):
                    await _update_log_status(db, doc_id, DocumentStatus.COMPLETED, "Completed artifact build.")
                else:
                    await _update_log_status(db, doc_id, DocumentStatus.ERROR, "Failed to build artifact")


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
