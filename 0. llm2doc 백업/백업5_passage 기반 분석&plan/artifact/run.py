import asyncio
import logging
import os
import threading
from queue import Queue
from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple, Sequence, Type, TypeVar
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


class PipelineTask(NamedTuple):
    pipeline_ctx: PipelineContext
    doc_id: int
    images: Sequence[Image.Image]
    doc_artifacts: dict[str, BaseModel]
    events: dict[tuple[int, str], threading.Event]
    error_state: dict[str, Exception]
    done_event: threading.Event


_pipeline_queues: dict[str, Queue[PipelineTask | None]] = {}
_pipeline_threads: list[Thread] = []
_pipeline_lock = threading.Lock()


async def _update_log_status(db: AsyncSession, doc_id: int, status: DocumentStatus, log: str):
    doc = await db.get_one(Document, doc_id)

    doc.process_status = status
    doc.process_log += f"{log}\n"


def _worker(pipeline_cls: Type[ArtifactPipeline], q: Queue[PipelineTask | None]):
    now = None
    while True:
        task = q.get()
        if task is None:
            if now:
                try:
                    now.dispose()
                except Exception:
                    pass
            q.task_done()
            break

        try:
            if now is None:
                now = pipeline_cls(task.pipeline_ctx)
            else:
                now.ctx = task.pipeline_ctx

            # Wait for inputs
            for req in pipeline_cls.INPUT_ARTIFACTS:
                while not task.events[(task.doc_id, req)].is_set():
                    if "error" in task.error_state:
                        raise StopIteration()
                    task.events[(task.doc_id, req)].wait(timeout=0.1)

            if "error" in task.error_state:
                raise StopIteration()

            if pipeline_cls.ARTIFACT_NAME not in task.doc_artifacts:
                doc = DocumentContext(
                    doc_id=task.doc_id,
                    images=task.images,
                    artifacts=task.doc_artifacts,
                )
                result = now.process(doc)
                task.doc_artifacts[now.ARTIFACT_NAME] = result

            task.events[(task.doc_id, pipeline_cls.ARTIFACT_NAME)].set()
        except StopIteration:
            pass
        except Exception as e:
            if "error" not in task.error_state:
                task.error_state["error"] = e
        finally:
            # Unblock this specific event to avoid deadlocks
            task.events[(task.doc_id, pipeline_cls.ARTIFACT_NAME)].set()
            task.done_event.set()
            q.task_done()


def _ensure_daemon_threads():
    with _pipeline_lock:
        if _pipeline_threads:
            return

        for pipeline in PIPELINES:
            q: Queue[PipelineTask | None] = Queue()
            _pipeline_queues[pipeline.ARTIFACT_NAME] = q
            t = Thread(target=_worker, args=(pipeline, q), daemon=True)
            t.start()
            _pipeline_threads.append(t)


@beartype
def _build_artifact_inner(
    pipeline_ctx: PipelineContext,
    doc_ids: Sequence[int],
    file_paths: Sequence[Sequence[str]],
    artifacts: Sequence[dict[str, BaseModel]],
):
    _ensure_daemon_threads()

    images = [[Image.open(x) for x in pages] for pages in file_paths]

    events: dict[tuple[int, str], threading.Event] = {}
    for doc_id in doc_ids:
        for p in PIPELINES:
            events[(doc_id, p.ARTIFACT_NAME)] = threading.Event()

    for doc_id, doc_artifacts in zip(doc_ids, artifacts):
        for name in doc_artifacts:
            if (doc_id, name) in events:
                events[(doc_id, name)].set()

    error_state: dict[str, Exception] = {}
    done_events: list[threading.Event] = []

    for i, doc_id in enumerate(doc_ids):
        for p in PIPELINES:
            done_event = threading.Event()
            done_events.append(done_event)

            task = PipelineTask(
                pipeline_ctx=pipeline_ctx,
                doc_id=doc_id,
                images=images[i],
                doc_artifacts=artifacts[i],
                events=events,
                error_state=error_state,
                done_event=done_event,
            )
            _pipeline_queues[p.ARTIFACT_NAME].put(task)

    for ev in done_events:
        ev.wait()

    if "error" in error_state:
        raise error_state["error"]


async def build_artifact(engine: AsyncEngine, doc_ids: Sequence[int]):
    loop = asyncio.get_running_loop()

    cpu_count = os.cpu_count() or 4

    with ThreadPoolExecutor(max_workers=cpu_count) as exe:
        pipeline_ctx = PipelineContext(
            loop=loop,
            engine=engine,
            thread_pool=exe,
        )

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

        required_artifacts = {pipeline.ARTIFACT_NAME for pipeline in PIPELINES}
        docs_missing_artifacts = [
            doc_id
            for doc_id, existing in zip(doc_ids, existing_artifacts)
            if not required_artifacts.issubset(existing)
        ]

        async with pipeline_ctx.with_db() as db:
            for doc_id in docs_missing_artifacts:
                await _update_log_status(db, doc_id, DocumentStatus.PROCESSING, "Starting artifact build...")

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
