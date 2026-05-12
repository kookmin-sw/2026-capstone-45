from typing import Any, Sequence

from llm2doc.artifact.semantic.semantic_pipeline.common.types import (
    CanonicalPage,
    ExcludedBlock,
    PageAnalysis,
    PassageTraceEntry,
    SemanticPassage,
)
from llm2doc.artifact.semantic.semantic_pipeline.passage.passage_context import build_page_passage_payload
from llm2doc.artifact.semantic.semantic_pipeline.passage.passage_engine import PassageAPIBackend
from llm2doc.artifact.semantic.semantic_pipeline.passage.passage_repair import (
    fallback_passage_result,
    parse_passage_response,
    repair_passage_result,
)
from llm2doc.artifact.semantic.semantic_pipeline.semantic.semantic_types import SemanticConfig


def build_passage_semantics(
    *,
    pages: list[CanonicalPage],
    analyses: Sequence[PageAnalysis],
    repeating_elements: Sequence[dict[str, Any]],
    config: SemanticConfig | None = None,
    backend: PassageAPIBackend | None = None,
) -> tuple[list[SemanticPassage], list[ExcludedBlock], list[PassageTraceEntry]]:
    config = config or SemanticConfig()
    analysis_map = {analysis.page: analysis for analysis in analyses}
    runtime_backend = backend
    passages: list[SemanticPassage] = []
    excluded_blocks: list[ExcludedBlock] = []
    traces: list[PassageTraceEntry] = []
    next_passage_index = 1

    for page in pages:
        payload = build_page_passage_payload(
            page=page,
            analysis=analysis_map[page.page],
            repeating_elements=repeating_elements,
        )
        raw_response: str | None = None
        parsed_result: dict[str, Any] | None = None
        fallback_reason: str | None = None
        latency_ms = 0

        try:
            if runtime_backend is None:
                runtime_backend = PassageAPIBackend()
            raw_response, latency_ms = runtime_backend.group(payload, config)
            parsed_result = parse_passage_response(raw_response)
        except Exception as exc:
            fallback_reason = str(exc) or type(exc).__name__
            parsed_result = fallback_passage_result(page)

        page_passages, page_excluded, repaired_result, next_passage_index = repair_passage_result(
            page=page,
            parsed_result=parsed_result,
            passage_start_index=next_passage_index,
        )
        passages.extend(page_passages)
        excluded_blocks.extend(page_excluded)
        traces.append(
            PassageTraceEntry(
                page=page.page,
                mode=config.mode,
                input_payload=payload,
                raw_response=raw_response,
                parsed_result=parsed_result,
                repaired_result=repaired_result,
                fallback_reason=fallback_reason,
                latency_ms=latency_ms,
            )
        )

    return passages, excluded_blocks, traces
