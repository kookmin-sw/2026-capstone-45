from typing import Mapping, Sequence, TypeVar, Type, cast
from dataclasses import dataclass
from pydantic import BaseModel
from PIL import Image

from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.util import validate_type


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class DocumentContext:
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
