from collections import Counter
from statistics import mean
from typing import Dict, List, Optional, Tuple

from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from .semantic_backends.qwen_transformers import QwenTransformersBackend
from .semantic_context import build_block_context
from .semantic_engine import resolve_block_decision
from .semantic_schema import enrich_generated_role
from .semantic_types import RoleDecision, SemanticConfig, SemanticRunSummary
from .types import CanonicalBlock, FusedPage, PageAnalysis


def _reset_semantic_fields(block: CanonicalBlock) -> None:
    block.generic_role = None
    block.domain_role = None
    block.role_confidence = None
    block.section_id = None
    block.section_purpose = None
    block.used_for_generation = None
    block.semantic_source = None
    block.semantic_reason = None
    block.semantic_needs_review = None
    block.semantic_backend = None
    block.semantic_model_name = None
    block.semantic_prompt_version = None
    block.semantic_fallback_reason = None
    block.generated_role_name = None
    block.generated_role_description = None
    block.generated_parent_role_name = None
    block.generated_role_level = None


def _normalize_generation_policy(decision: RoleDecision) -> Tuple[bool, Optional[str]]:
    if decision.domain_role == "report_title":
        return True, "main_argument"
    if decision.domain_role == "thesis_heading":
        return True, "thesis"
    if decision.domain_role == "supporting_argument":
        return True, "supporting_argument"
    if decision.domain_role == "investment_opinion_box":
        return True, "investment_summary"
    if decision.domain_role in {"key_data_box", "consensus_box", "price_chart_block"}:
        if decision.generic_role == "section_heading":
            return True, "evidence_panel"
        return False, "evidence_panel"
    if decision.domain_role in {"financial_table_block", "unsupported_evidence"}:
        return False, "evidence_panel"
    if decision.domain_role == "disclaimer_block":
        return True, "disclaimer"
    if decision.domain_role in {"report_header_meta", "research_center_meta", "analyst_info"}:
        return True, None
    if decision.generic_role == "metadata":
        return False, None
    if decision.generic_role == "author_info":
        return True, None
    if decision.generic_role == "disclaimer":
        return True, "disclaimer"
    if decision.generic_role == "summary":
        return True, decision.section_purpose or "investment_summary"
    if decision.generic_role == "body":
        return True, "supporting_argument"
    if decision.generic_role == "main_title":
        return True, "main_argument"
    if decision.generic_role == "section_heading":
        return True, decision.section_purpose
    if decision.generic_role == "evidence":
        return False, decision.section_purpose or "evidence_panel"
    return False, decision.section_purpose


def _apply_decision_to_block(
    block: CanonicalBlock,
    decision: RoleDecision,
    *,
    source: str,
    backend_name: str,
    config: SemanticConfig,
    fallback_reason: Optional[str] = None,
) -> None:
    decision = enrich_generated_role(decision)
    used_for_generation, section_purpose = _normalize_generation_policy(decision)
    block.generic_role = decision.generic_role
    block.domain_role = decision.domain_role
    block.role_confidence = round(decision.role_confidence, 4)
    block.section_purpose = section_purpose
    block.used_for_generation = used_for_generation
    block.semantic_source = source
    block.semantic_reason = decision.reason if source == "qwen" else None
    block.semantic_needs_review = bool(decision.needs_review)
    block.semantic_backend = backend_name
    block.semantic_model_name = config.model_name if backend_name != "heuristic" else None
    block.semantic_prompt_version = config.prompt_version if backend_name != "heuristic" else None
    block.semantic_fallback_reason = fallback_reason if source != "qwen" and fallback_reason else None
    block.generated_role_name = decision.generated_role_name
    block.generated_role_description = decision.generated_role_description
    block.generated_parent_role_name = decision.generated_parent_role_name
    block.generated_role_level = decision.generated_role_level


def _assign_section_ids(pages: List[FusedPage]) -> None:
    section_counter = 0
    for page in pages:
        current_section_id: Optional[str] = None
        blocks = sorted(page.blocks, key=lambda block: (block.reading_order, block.bbox_px[1], block.bbox_px[0]))
        for block in blocks:
            block.section_id = None
            if block.domain_role == "report_title":
                section_counter += 1
                current_section_id = "sec-%03d" % section_counter
                block.section_id = current_section_id
                continue
            if block.domain_role == "thesis_heading":
                section_counter += 1
                current_section_id = "sec-%03d" % section_counter
                block.section_id = current_section_id
                continue
            if block.domain_role == "supporting_argument":
                if current_section_id:
                    block.section_id = current_section_id
                else:
                    block.semantic_needs_review = True


def _eligible_for_qwen(block: CanonicalBlock) -> bool:
    return bool(block.text) or block.canonical_label in {"table", "chart", "image"}


def _make_unknown_decision(block: CanonicalBlock, reason: str) -> RoleDecision:
    return RoleDecision(
        block_id=block.block_id,
        generic_role="unknown",
        domain_role=None,
        role_confidence=0.0,
        section_purpose=None,
        used_for_generation=False,
        reason=reason,
        needs_review=True,
    )


def apply_financial_semantic_overlay(
    pages: List[FusedPage],
    analyses: List[PageAnalysis],
    config: Optional[SemanticConfig] = None,
    backend: Optional[QwenTransformersBackend] = None,
    document_family: str = "financial_report",
) -> SemanticRunSummary:
    config = config or SemanticConfig()
    analysis_map: Dict[int, PageAnalysis] = {analysis.page: analysis for analysis in analyses}
    backend_name_str = (
        backend.backend_name if backend else ("qwen_api" if config.runtime == "api" else "qwen_transformers")
    )
    fallback_reasons: Counter = Counter()
    applied_source_counts: Counter = Counter()
    confidence_values: List[float] = []
    trace_entries = []
    attempted_count = 0
    accepted_count = 0
    fallback_count = 0

    for page in pages:
        analysis = analysis_map[page.page]
        blocks = sorted(page.blocks, key=lambda block: (block.reading_order, block.bbox_px[1], block.bbox_px[0]))
        progress_bar = tqdm(total=len(blocks), desc=f"Processing Page {page.page}", unit="block")
        tasks = []

        for block in blocks:
            _reset_semantic_fields(block)
            fallback_decision = _make_unknown_decision(
                block,
                reason="Qwen semantic classification failed or returned unusable output.",
            )

            if not _eligible_for_qwen(block):
                _apply_decision_to_block(
                    block,
                    fallback_decision,
                    source="unknown_fallback",
                    backend_name="heuristic",
                    config=config,
                    fallback_reason="ineligible_block",
                )
                applied_source_counts["unknown_fallback"] += 1
                confidence_values.append(fallback_decision.role_confidence)
                progress_bar.update(1)
                continue

            payload = build_block_context(
                page=page,
                analysis=analysis,
                block=block,
                config=config,
                document_family=document_family,
            )
            tasks.append((block, payload, fallback_decision))

        if tasks:
            max_workers = 10 if config.runtime == "api" else 1
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_block = {
                    executor.submit(
                        resolve_block_decision,
                        payload=payload,
                        fallback_decision=fallback_decision,
                        config=config,
                        backend=backend,
                    ): block
                    for block, payload, fallback_decision in tasks
                }
                for future in as_completed(future_to_block):
                    block = future_to_block[future]
                    final_decision, trace_entry, fallback_reason, qwen_accepted = future.result()

                    if trace_entry is not None:
                        trace_entries.append(trace_entry)
                        if trace_entry.raw_response is not None or trace_entry.fallback_reason in {
                            "backend_error",
                            "invalid_json",
                            "schema_mismatch",
                        }:
                            attempted_count += 1
                    if fallback_reason:
                        fallback_reasons[fallback_reason] += 1
                        fallback_count += 1

                    if qwen_accepted:
                        accepted_count += 1
                        source = "qwen"
                        backend_name_for_block = backend_name_str
                    else:
                        source = "unknown_fallback"
                        backend_name_for_block = "heuristic"

                    _apply_decision_to_block(
                        block,
                        final_decision,
                        source=source,
                        backend_name=backend_name_for_block,
                        config=config,
                        fallback_reason=fallback_reason,
                    )
                    applied_source_counts[source] += 1
                    confidence_values.append(final_decision.role_confidence)
                    progress_bar.update(1)

        progress_bar.close()

    _assign_section_ids(pages)
    needs_review_count = sum(
        1
        for page in pages
        for block in page.blocks
        if block.semantic_needs_review
    )
    return SemanticRunSummary(
        mode=config.mode,
        backend=backend_name_str,
        model_name=config.model_name,
        prompt_version=config.prompt_version,
        page_count=len(pages),
        block_count=sum(len(page.blocks) for page in pages),
        attempted_count=attempted_count,
        accepted_count=accepted_count,
        fallback_count=fallback_count,
        needs_review_count=needs_review_count,
        avg_role_confidence=round(mean(confidence_values), 4) if confidence_values else 0.0,
        fallback_reasons=dict(fallback_reasons),
        applied_source_counts=dict(applied_source_counts),
        trace=trace_entries,
    )
