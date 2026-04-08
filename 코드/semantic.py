from collections import Counter
from statistics import mean
from typing import Dict, List, Optional, Tuple

from tqdm import tqdm

from .semantic_backends.qwen_transformers import QwenTransformersBackend
from .semantic_context import build_block_context
from .semantic_engine import resolve_block_decision
from .semantic_rules import compute_financial_rule_decisions, compute_financial_safety_rules, make_unknown_decision
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


def _safety_rules_enabled(config: SemanticConfig) -> bool:
    if config.mode == "rule":
        return True
    return "qwen" not in (config.model_name or "").lower()


def apply_financial_semantic_overlay(
    pages: List[FusedPage],
    analyses: List[PageAnalysis],
    config: Optional[SemanticConfig] = None,
    backend: Optional[QwenTransformersBackend] = None,
    document_family: str = "financial_report",
) -> SemanticRunSummary:
    config = config or SemanticConfig()
    analysis_map: Dict[int, PageAnalysis] = {analysis.page: analysis for analysis in analyses}
    summary_backend = "heuristic" if config.mode == "rule" else "qwen_transformers"
    fallback_reasons: Counter = Counter()
    applied_source_counts: Counter = Counter()
    confidence_values: List[float] = []
    trace_entries = []
    attempted_count = 0
    accepted_count = 0
    fallback_count = 0
    shadow_disagreement_count = 0
    safety_rules_enabled = _safety_rules_enabled(config)

    for page in pages:
        analysis = analysis_map[page.page]
        legacy_rule_decisions = compute_financial_rule_decisions(page, analysis) if document_family == "financial_report" else {}
        safety_rule_decisions = (
            compute_financial_safety_rules(page, analysis)
            if safety_rules_enabled
            else {}
        )
        blocks = sorted(page.blocks, key=lambda block: (block.reading_order, block.bbox_px[1], block.bbox_px[0]))

        progress_bar = None
        if config.mode != "rule":
            progress_bar = tqdm(total=len(blocks), desc=f"Processing Page {page.page}", unit="block")

        for block in blocks:
            _reset_semantic_fields(block)
            actual_rule_decision = legacy_rule_decisions.get(block.block_id)
            safety_rule_decision = safety_rule_decisions.get(block.block_id)
            fallback_decision = safety_rule_decision or make_unknown_decision(block)

            if config.mode == "rule":
                if actual_rule_decision is None:
                    continue
                _apply_decision_to_block(
                    block,
                    actual_rule_decision,
                    source="rule",
                    backend_name="heuristic",
                    config=config,
                )
                applied_source_counts["rule"] += 1
                confidence_values.append(actual_rule_decision.role_confidence)
                continue

            if not _eligible_for_qwen(block):
                if safety_rule_decision is not None:
                    _apply_decision_to_block(
                        block,
                        safety_rule_decision,
                        source="safety_rule",
                        backend_name="heuristic",
                        config=config,
                    )
                    applied_source_counts["safety_rule"] += 1
                    confidence_values.append(safety_rule_decision.role_confidence)
                if progress_bar:
                    progress_bar.update(1)
                continue

            payload = build_block_context(
                page=page,
                analysis=analysis,
                block=block,
                config=config,
                document_family=document_family,
            )
            final_decision, trace_entry, fallback_reason, qwen_accepted = resolve_block_decision(
                payload=payload,
                fallback_decision=fallback_decision,
                config=config,
                backend=backend,
            )
            if trace_entry is not None:
                trace_entries.append(trace_entry)
                if trace_entry.raw_response is not None or trace_entry.fallback_reason in {"backend_error", "invalid_json", "schema_mismatch"}:
                    attempted_count += 1
            if fallback_reason:
                fallback_reasons[fallback_reason] += 1
                fallback_count += 1

            if config.mode == "shadow":
                if actual_rule_decision is not None:
                    _apply_decision_to_block(
                        block,
                        actual_rule_decision,
                        source="rule",
                        backend_name="heuristic",
                        config=config,
                    )
                    applied_source_counts["rule"] += 1
                    confidence_values.append(actual_rule_decision.role_confidence)
                elif qwen_accepted and final_decision.generic_role != "unknown":
                    shadow_disagreement_count += 1
                if qwen_accepted and actual_rule_decision is not None and trace_entry and trace_entry.parsed_decision is not None:
                    if (actual_rule_decision.generic_role, actual_rule_decision.domain_role) != (
                        trace_entry.parsed_decision["generic_role"],
                        trace_entry.parsed_decision["domain_role"],
                    ):
                        shadow_disagreement_count += 1
                if progress_bar:
                    progress_bar.update(1)
                continue

            if qwen_accepted:
                accepted_count += 1
                source = "qwen"
                backend_name = "qwen_transformers"
            else:
                source = "safety_rule" if safety_rule_decision is not None else "unknown_fallback"
                backend_name = "heuristic"

            _apply_decision_to_block(
                block,
                final_decision,
                source=source,
                backend_name=backend_name,
                config=config,
                fallback_reason=fallback_reason,
            )
            applied_source_counts[source] += 1
            confidence_values.append(final_decision.role_confidence)
            if progress_bar:
                progress_bar.update(1)

        if progress_bar:
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
        backend=summary_backend,
        model_name=config.model_name if config.mode != "rule" else None,
        prompt_version=config.prompt_version if config.mode != "rule" else None,
        page_count=len(pages),
        block_count=sum(len(page.blocks) for page in pages),
        attempted_count=attempted_count,
        accepted_count=accepted_count,
        fallback_count=fallback_count,
        needs_review_count=needs_review_count,
        avg_role_confidence=round(mean(confidence_values), 4) if confidence_values else 0.0,
        fallback_reasons=dict(fallback_reasons),
        applied_source_counts=dict(applied_source_counts),
        shadow_disagreement_count=shadow_disagreement_count,
        trace=trace_entries,
    )
