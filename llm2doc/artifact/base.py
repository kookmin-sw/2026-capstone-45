from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypeVar, Generic, Sequence, ClassVar, Type
from pydantic import BaseModel

if TYPE_CHECKING:
    from llm2doc.context.pipeline import PipelineContext
    from llm2doc.context.document import DocumentContext


OUT = TypeVar("OUT", bound=BaseModel, covariant=True)


class ArtifactPipeline(ABC, Generic[OUT]):
    """
    문서를 처리해 특정 아티팩트를 생성하는 파이프라인.
    아티팩트간의 의존성은 DAG로 나타낼 수 있어야 한다.
    """

    ARTIFACT: ClassVar[Type[BaseModel]]
    """아티팩트"""

    ARTIFACT_NAME: ClassVar[str]
    """아티팩트 이름"""

    INPUT_ARTIFACTS: ClassVar[Sequence[str]]
    """이 아티팩트를 생성하기 위해 입력으로 받는 아티팩트들의 이름"""

    ctx: PipelineContext

    def __init__(self, ctx: PipelineContext):
        super().__init__()
        self.ctx = ctx

    @abstractmethod
    def process(self, document: DocumentContext) -> OUT: ...

    def dispose(self):
        pass
