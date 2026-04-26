from typing import Type, TypeVar, cast
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, ValidationError

from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.entity import Artifact


OUT = TypeVar("OUT", bound=BaseModel)


async def load_artifact(db: AsyncSession, doc_id: int, pipeline: Type[ArtifactPipeline[OUT]]) -> OUT | None:
    name = pipeline.ARTIFACT_NAME

    stmt = select(Artifact).where(Artifact.doc_id == doc_id, Artifact.artifact_name == name).limit(1)
    result = (await db.execute(stmt)).scalar_one_or_none()

    if result is None:
        return None

    try:
        data = pipeline.ARTIFACT.model_validate_json(result.content_json, strict=True)
    except ValidationError:
        # TODO: Add log
        await db.delete(result)
        return None

    return cast(OUT, data)


async def save_artifact(db: AsyncSession, doc_id: int, artifact_name: str, artifact: BaseModel):
    stmt = delete(Artifact).where(Artifact.doc_id == doc_id, Artifact.artifact_name == artifact_name)
    await db.execute(stmt)

    db.add(
        Artifact(
            doc_id=doc_id,
            artifact_name=artifact_name,
            content_json=artifact.model_dump_json(),
        )
    )


async def clear_artifacts(db: AsyncSession, doc_id: int):
    stmt = delete(Artifact).where(Artifact.doc_id == doc_id)
    await db.execute(stmt)
