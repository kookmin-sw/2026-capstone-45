from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from llm2doc.artifact.semantic import SemanticArtifact, SemanticArtifactPipeline
from llm2doc.debug_trace import GenerationTracer
from llm2doc.entity import Chat, ChatSource
from llm2doc.repository.artifact import load_artifact
from llm2doc.repository.document import load_document, load_document_image_all
from llm2doc.repository.file import get_file_path
from llm2doc.passage_visual_report import PassageVisualDocument, write_passage_visual_report


async def write_passage_visual_report_for_chat(engine: AsyncEngine, chat_id: int) -> list[str]:
    """Create passage visual report files for an existing chat without regenerating the chat."""
    async with AsyncSession(engine) as db:
        async with db.begin():
            chat = await db.get(Chat, chat_id)
            if chat is None:
                raise ValueError(f"chat not found: {chat_id}")

            source_doc_ids = list(
                (
                    await db.execute(
                        select(ChatSource.doc_id)
                        .where(ChatSource.chat_id == chat_id)
                        .order_by(ChatSource.doc_id)
                    )
                ).scalars()
            )
            doc_ids = [chat.target_doc_id, *source_doc_ids]
            doc_names: dict[int, str] = {}
            for doc_id in doc_ids:
                doc = await load_document(db, doc_id)
                doc_names[doc_id] = doc.display_name
            semantic_artifacts = {
                doc_id: await load_artifact(db, doc_id, SemanticArtifactPipeline)
                for doc_id in doc_ids
            }
            missing = [doc_id for doc_id, artifact in semantic_artifacts.items() if artifact is None]
            if missing:
                raise ValueError(f"missing SemanticArtifact for document ids: {missing}")

            image_paths_by_doc_id: dict[int, list[str]] = {}
            for doc_id in doc_ids:
                image_rows = await load_document_image_all(db, doc_id)
                image_paths_by_doc_id[doc_id] = [get_file_path(row.file_id) for row in image_rows]

    page_images_by_doc_id = {
        doc_id: await asyncio.to_thread(_load_images, paths)
        for doc_id, paths in image_paths_by_doc_id.items()
    }

    target_artifact = semantic_artifacts[doc_ids[0]]
    assert target_artifact is not None
    documents = [
        PassageVisualDocument(
            role="target",
            doc_id=doc_ids[0],
            display_name=doc_names[doc_ids[0]],
            semantic_artifact=target_artifact,
            page_images=page_images_by_doc_id.get(doc_ids[0], []),
        )
    ]

    for doc_id in source_doc_ids:
        artifact = semantic_artifacts[doc_id]
        assert artifact is not None
        documents.append(
            PassageVisualDocument(
                role="source",
                doc_id=doc_id,
                display_name=doc_names[doc_id],
                semantic_artifact=artifact,
                page_images=page_images_by_doc_id.get(doc_id, []),
            )
        )

    tracer = GenerationTracer.for_chat(chat_id)
    paths = await asyncio.to_thread(write_passage_visual_report, tracer.root, documents)
    tracer.update_summary(passage_visual_report=paths[0] if paths else None)
    tracer.event(
        "semantic_debug",
        "passage_visual_report_created",
        {
            "paths": paths,
            "backfilled": True,
        },
    )
    return paths


def write_passage_visual_report_for_chat_sync(engine: AsyncEngine, chat_id: int) -> list[str]:
    return asyncio.run(write_passage_visual_report_for_chat(engine, chat_id))


def _load_images(paths: list[str]) -> list[Image.Image]:
    images: list[Image.Image] = []
    for path in paths:
        with Image.open(Path(path)) as image:
            images.append(image.copy())
    return images
