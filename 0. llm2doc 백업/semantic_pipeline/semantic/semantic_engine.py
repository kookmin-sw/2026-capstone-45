from dataclasses import asdict, replace
from typing import Optional, Tuple

from llm2doc.semantic_pipeline.semantic.semantic_backends.qwen_api import QwenAPIBackend
from llm2doc.semantic_pipeline.semantic.semantic_schema import (
    enrich_generated_role,
    normalize_decision,
    parse_role_decision,
    validate_role_pair,
)
from llm2doc.semantic_pipeline.semantic.semantic_types import (
    BlockContextPayload,
    RoleDecision,
    RoleTraceEntry,
    SemanticConfig,
)


def _truncate_response(raw_response: Optional[str]) -> Optional[str]:
    if raw_response is None:
        return None
    return raw_response[:4000]


def _build_trace(
    *,
    payload: BlockContextPayload,
    config: SemanticConfig,
    raw_response: Optional[str],
    parsed_decision: Optional[RoleDecision],
    applied_decision: RoleDecision,
    fallback_reason: Optional[str],
    latency_ms: int,
) -> RoleTraceEntry:
    return RoleTraceEntry(
        block_id=payload.block_id,
        page=payload.page,
        mode=config.mode,
        input_payload=asdict(payload),
        raw_response=_truncate_response(raw_response),
        parsed_decision=asdict(parsed_decision) if parsed_decision else None,
        applied_decision=asdict(applied_decision),
        fallback_reason=fallback_reason,
        latency_ms=latency_ms,
    )


def resolve_block_decision(
    *,
    payload: BlockContextPayload,
    fallback_decision: RoleDecision,
    config: SemanticConfig,
    backend: Optional[QwenAPIBackend] = None,
) -> Tuple[RoleDecision, Optional[RoleTraceEntry], Optional[str], bool]:
    fallback_decision = enrich_generated_role(fallback_decision)

    allow_domain = payload.page_quality_score >= config.quality_threshold
    if payload.page_quality_score < config.quality_threshold:
        trace = _build_trace(
            payload=payload,
            config=config,
            raw_response=None,
            parsed_decision=None,
            applied_decision=fallback_decision,
            fallback_reason="low_page_quality",
            latency_ms=0,
        )
        return fallback_decision, trace, "low_page_quality", False

    runtime_backend = backend or QwenAPIBackend()
    raw_response: Optional[str] = None
    parsed_decision: Optional[RoleDecision] = None
    latency_ms = 0

    for attempt in range(2):
        try:
            raw_response, current_latency = runtime_backend.assign(payload, config)
            latency_ms += current_latency
        except Exception:
            trace = _build_trace(
                payload=payload,
                config=config,
                raw_response=None,
                parsed_decision=None,
                applied_decision=fallback_decision,
                fallback_reason="backend_error",
                latency_ms=latency_ms,
            )
            return fallback_decision, trace, "backend_error", False

        try:
            parsed_decision = parse_role_decision(raw_response, payload.block_id)
            break
        except ValueError as exc:
            failure_code = str(exc)
            if attempt == 0:
                continue
            trace = _build_trace(
                payload=payload,
                config=config,
                raw_response=raw_response,
                parsed_decision=None,
                applied_decision=fallback_decision,
                fallback_reason=failure_code,
                latency_ms=latency_ms,
            )
            return fallback_decision, trace, failure_code, False

    if parsed_decision is None:
        trace = _build_trace(
            payload=payload,
            config=config,
            raw_response=raw_response,
            parsed_decision=None,
            applied_decision=fallback_decision,
            fallback_reason="invalid_json",
            latency_ms=latency_ms,
        )
        return fallback_decision, trace, "invalid_json", False

    parsed_decision = normalize_decision(parsed_decision, allow_domain=allow_domain)
    if not validate_role_pair(parsed_decision.generic_role, parsed_decision.domain_role):
        parsed_decision = replace(parsed_decision, domain_role=None, needs_review=True)

    if parsed_decision.role_confidence < config.confidence_generic_only_threshold:
        trace = _build_trace(
            payload=payload,
            config=config,
            raw_response=raw_response,
            parsed_decision=parsed_decision,
            applied_decision=fallback_decision,
            fallback_reason="low_role_confidence",
            latency_ms=latency_ms,
        )
        return fallback_decision, trace, "low_role_confidence", False

    if parsed_decision.role_confidence < config.confidence_accept_threshold:
        parsed_decision = replace(parsed_decision, domain_role=None, needs_review=True)

    trace = _build_trace(
        payload=payload,
        config=config,
        raw_response=raw_response,
        parsed_decision=parsed_decision,
        applied_decision=parsed_decision,
        fallback_reason=None,
        latency_ms=latency_ms,
    )
    return parsed_decision, trace, None, True
