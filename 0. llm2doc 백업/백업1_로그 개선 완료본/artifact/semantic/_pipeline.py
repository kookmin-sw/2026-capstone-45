import asyncio
from typing import List, Dict, Any

from llm2doc.artifact.base import ArtifactPipeline
from llm2doc.artifact.ocr import OCRArtifact, OCRArtifactPipeline
from llm2doc.artifact.semantic._artifact import SemanticArtifact
from llm2doc.context.document import DocumentContext
from llm2doc.context.pipeline import PipelineContext

# Internal imports from the moved semantic_pipeline
from .semantic_pipeline.common.types import EnginePage, RawEngineBlock, PageSource, dataclass_to_dict
from .semantic_pipeline.common.utils import normalize_bbox
from .semantic_pipeline.parsing.canonicalize import build_canonical_page
from .semantic_pipeline.pipeline.reference_pipeline import build_reference_outputs
from .semantic_pipeline.semantic.semantic_types import SemanticConfig


class SemanticArtifactPipeline(ArtifactPipeline[SemanticArtifact]):
    """
    OCRArtifact를 입력으로 받아 의미론적 분석(Semantic Pipeline)을 수행한다.
    """

    ARTIFACT = SemanticArtifact
    ARTIFACT_NAME = "SemanticArtifact"
    INPUT_ARTIFACTS = ["OCRArtifact"]

    def __init__(self, ctx: PipelineContext):
        super().__init__(ctx)

    def process(self, document: DocumentContext) -> SemanticArtifact:
        ocr_artifact = document.get_artifact(OCRArtifactPipeline)
        
        engine_pages: List[EnginePage] = []
        for i, ocr_page in enumerate(ocr_artifact.pages):
            page_num = i + 1
            sample_id = f"{document.doc_id}-{i:02d}"
            
            raw_blocks: List[RawEngineBlock] = []
            for j, ocr_block in enumerate(ocr_page.blocks):
                raw_blocks.append(
                    RawEngineBlock(
                        engine="paddle",
                        page=page_num,
                        raw_label=ocr_block.label,
                        text=ocr_block.content or "",
                        bbox_px=list(ocr_block.bbox),
                        bbox_norm=normalize_bbox(ocr_block.bbox, ocr_page.width, ocr_page.height),
                        reading_order=j,
                        polygon=[],
                        tags=[],
                        raw_confidence=None,
                    )
                )
            
            engine_pages.append(
                EnginePage(
                    engine="paddle",
                    page=page_num,
                    sample_id=sample_id,
                    width=ocr_page.width,
                    height=ocr_page.height,
                    raw_blocks=raw_blocks,
                    source_paths={},
                    metadata={
                        "json": ocr_page.content_json,
                        "markdown": ocr_page.content_markdown,
                    },
                )
            )
            
        canonical_pages = [build_canonical_page(page) for page in engine_pages]
        
        # ReferencePipeline에서 요구하는 source_bundle 형태를 맞춘다.
        source_bundle: Dict[str, Any] = {
            "ocr_source": "llm2doc",
            "resolved_reference_path": str(document.doc_id), # 실제 경로는 아니지만 ID로 식별
            "page_sources": [
                PageSource(
                    page_number=p.page,
                    sample_id=p.sample_id,
                    source_type="llm2doc",
                    reference_doc_id=str(document.doc_id),
                    document_dir="",
                    image_path=None,
                )
                for p in engine_pages
            ],
            "llm2doc_pages": engine_pages,
        }
        
        template_dc, diagnostics, canonical_payload = build_reference_outputs(
            job_id=str(document.doc_id),
            canonical_pages=canonical_pages,
            source_bundle=source_bundle,
            semantic_config=SemanticConfig(mode="qwen", runtime="api"),
        )
        
        return SemanticArtifact.model_validate({
            "template": dataclass_to_dict(template_dc),
            "diagnostics": diagnostics,
            "canonical_pages": canonical_payload,
        })
