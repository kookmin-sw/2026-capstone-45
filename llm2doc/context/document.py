import asyncio
import logging

from typing import Mapping, Sequence, TypeVar, Type, cast
from dataclasses import dataclass
from pydantic import BaseModel
from PIL import Image

from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.context.pipeline import PipelineContext
from llm2doc.repository.document import append_document_log
from llm2doc.util import validate_type


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class DocumentContext:
    pipeline_ctx: PipelineContext
    doc_id: int
    images: Sequence[Image.Image]
    artifacts: Mapping[str, BaseModel]

    def get_artifact(self, pipeline: Type[ArtifactPipeline[T]]) -> T:
        try:
            value = self.artifacts[pipeline.ARTIFACT_NAME]
        except KeyError:
            raise ValueError(f"{pipeline.ARTIFACT_NAME}를 찾을 수 없습니다. INPUT_ARTIFACTS를 확인하세요.")

        validate_type(value, pipeline.ARTIFACT)
        return cast(T, value)

    async def append_log(self, message: str):
        logging.info(message)
        async with self.pipeline_ctx.with_db() as db:
            await append_document_log(db, self.doc_id, message)

    def append_log_sync(self, message: str):
        asyncio.run_coroutine_threadsafe(self.append_log(message), loop=self.pipeline_ctx.loop)
