from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.artifact.layout._artifact import LayoutArtifact
from llm2doc.context.pipeline import PipelineContext
from llm2doc.context.document import DocumentContext


class LayoutArtifactPipeline(ArtifactPipeline[LayoutArtifact]):
    ARTIFACT = LayoutArtifact
    ARTIFACT_NAME = "LayoutArtifact"
    INPUT_ARTIFACTS = []

    ctx: PipelineContext

    def __init__(self, ctx: PipelineContext):
        super().__init__(ctx)
        self.ctx = ctx

    def process(self, document: DocumentContext) -> LayoutArtifact:
        raise NotImplementedError()

    def dispose(self):
        return
