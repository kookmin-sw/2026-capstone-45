import json
import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from llm2doc.artifact.semantic.semantic_pipeline.semantic.semantic_types import RoleDecision


GENERIC_ROLES = (
    "main_title",
    "section_heading",
    "summary",
    "body",
    "evidence",
    "metadata",
    "author_info",
    "disclaimer",
    "unknown",
)

DOMAIN_ROLES = (
    "report_header_meta",
    "investment_opinion_box",
    "key_data_box",
    "consensus_box",
    "price_chart_block",
    "financial_table_block",
    "report_title",
    "thesis_heading",
    "supporting_argument",
    "analyst_info",
    "research_center_meta",
    "disclaimer_block",
    "unsupported_evidence",
)

_DOMAIN_ROLE_BY_GENERIC = {
    "main_title": {"report_title"},
    "section_heading": {"key_data_box", "consensus_box", "price_chart_block", "thesis_heading"},
    "summary": {"investment_opinion_box"},
    "body": {"supporting_argument"},
    "evidence": {"key_data_box", "consensus_box", "price_chart_block", "financial_table_block", "unsupported_evidence"},
    "metadata": {"report_header_meta", "research_center_meta"},
    "author_info": {"analyst_info"},
    "disclaimer": {"disclaimer_block"},
    "unknown": set(),
}

_PARENT_ROLE_BY_GENERIC = {
    "main_title": "document_structure",
    "section_heading": "document_structure",
    "summary": "summary_panel",
    "body": "narrative",
    "evidence": "evidence_cluster",
    "metadata": "metadata",
    "author_info": "metadata",
    "disclaimer": "compliance",
    "unknown": None,
}

_GENERATED_ROLE_NAME_BY_GENERIC = {
    "main_title": "document_title_block",
    "section_heading": "section_heading_block",
    "summary": "summary_block",
    "body": "narrative_block",
    "evidence": "evidence_block",
    "metadata": "metadata_block",
    "author_info": "author_information_block",
    "disclaimer": "disclaimer_block",
    "unknown": "unknown_block",
}

_ROLE_DESCRIPTION_BY_DOMAIN = {
    "report_header_meta": "Metadata describing the report header, date, or publication context.",
    "investment_opinion_box": "A summary block presenting the recommendation or highlighted investment stance.",
    "key_data_box": "A panel title or evidence block for key data in a compact sidebar or summary area.",
    "consensus_box": "A panel title or evidence block for consensus data or comparable estimates.",
    "price_chart_block": "A chart title or visual evidence block about stock price movement.",
    "financial_table_block": "A table or evidence block containing financial metrics or projections.",
    "report_title": "The main report title or primary document headline.",
    "thesis_heading": "A heading introducing the main thesis or narrative section.",
    "supporting_argument": "Narrative body text that supports the thesis or main argument.",
    "analyst_info": "Author or analyst identity information for the report.",
    "research_center_meta": "Metadata about the organization, research center, or publisher.",
    "disclaimer_block": "Compliance, disclaimer, or legal notice content.",
    "unsupported_evidence": "Visual or tabular evidence that is not confidently linked to a supported semantic panel.",
}

_ROLE_DESCRIPTION_BY_GENERIC = {
    "main_title": "A block functioning as the document's main title or headline.",
    "section_heading": "A block functioning as a heading or title for a section or panel.",
    "summary": "A compact summary block highlighting the main takeaway.",
    "body": "Narrative body content that carries the main explanation.",
    "evidence": "A supporting evidence block such as a table, chart, or image.",
    "metadata": "Metadata about the document, publication, or organization.",
    "author_info": "Information identifying the author or analyst.",
    "disclaimer": "Disclaimer or compliance text.",
    "unknown": "A block whose semantic role remains uncertain.",
}

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_GENERATED_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _extract_json_text(raw_text: str) -> str:
    cleaned = (raw_text or "").strip()
    if not cleaned:
        raise ValueError("invalid_json")
    cleaned = _THINK_BLOCK_RE.sub("", cleaned).strip()
    fenced = _JSON_FENCE_RE.fullmatch(cleaned)
    if fenced:
        return fenced.group(1).strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("invalid_json")
    return cleaned[start : end + 1]


def _sanitize_generated_role_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return None
    if not cleaned[0].isalpha():
        cleaned = "role_%s" % cleaned
    if len(cleaned) < 3:
        cleaned = "%s_block" % cleaned
    return cleaned[:64]


def _normalize_generated_role_level(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if cleaned not in {"document", "section", "block"}:
        raise ValueError("invalid generated role level")
    return cleaned


def enrich_generated_role(decision: RoleDecision) -> RoleDecision:
    generated_role_name = _sanitize_generated_role_name(decision.generated_role_name)
    if generated_role_name is None:
        generated_role_name = decision.domain_role or _GENERATED_ROLE_NAME_BY_GENERIC.get(decision.generic_role, "unknown_block")
    generated_description = (decision.generated_role_description or "").strip()
    if not generated_description:
        generated_description = _ROLE_DESCRIPTION_BY_DOMAIN.get(decision.domain_role) or _ROLE_DESCRIPTION_BY_GENERIC.get(
            decision.generic_role,
            _ROLE_DESCRIPTION_BY_GENERIC["unknown"],
        )
    generated_parent = _sanitize_generated_role_name(decision.generated_parent_role_name)
    if generated_parent is None:
        generated_parent = _PARENT_ROLE_BY_GENERIC.get(decision.generic_role)
    generated_level = _normalize_generated_role_level(decision.generated_role_level) or "block"
    return RoleDecision(
        block_id=decision.block_id,
        generic_role=decision.generic_role,
        domain_role=decision.domain_role,
        role_confidence=decision.role_confidence,
        section_purpose=decision.section_purpose,
        used_for_generation=decision.used_for_generation,
        reason=decision.reason,
        needs_review=decision.needs_review,
        generated_role_name=generated_role_name,
        generated_role_description=generated_description,
        generated_parent_role_name=generated_parent,
        generated_role_level=generated_level,
    )


class RoleDecisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    generic_role: str
    domain_role: Optional[str]
    role_confidence: float
    section_purpose: Optional[str]
    used_for_generation: Optional[bool]
    reason: str
    needs_review: bool
    generated_role_name: Optional[str] = None
    generated_role_description: Optional[str] = None
    generated_parent_role_name: Optional[str] = None
    generated_role_level: Optional[str] = None

    @field_validator("generic_role")
    @classmethod
    def _validate_generic_role(cls, value: str) -> str:
        if value not in GENERIC_ROLES:
            raise ValueError("invalid generic role")
        return value

    @field_validator("domain_role")
    @classmethod
    def _validate_domain_role(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in DOMAIN_ROLES:
            raise ValueError("invalid domain role")
        return value

    @field_validator("role_confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("role_confidence must be between 0 and 1")
        return value

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason must be non-empty")
        return cleaned

    @field_validator("generated_role_name")
    @classmethod
    def _validate_generated_role_name(cls, value: Optional[str]) -> Optional[str]:
        cleaned = _sanitize_generated_role_name(value)
        if cleaned is None:
            return None
        if not _GENERATED_ROLE_RE.fullmatch(cleaned):
            raise ValueError("invalid generated role name")
        return cleaned

    @field_validator("generated_parent_role_name")
    @classmethod
    def _validate_generated_parent_role_name(cls, value: Optional[str]) -> Optional[str]:
        cleaned = _sanitize_generated_role_name(value)
        if cleaned is None:
            return None
        if not _GENERATED_ROLE_RE.fullmatch(cleaned):
            raise ValueError("invalid generated parent role name")
        return cleaned

    @field_validator("generated_role_description")
    @classmethod
    def _validate_generated_role_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("generated role description must be non-empty")
        return cleaned

    @field_validator("generated_role_level")
    @classmethod
    def _validate_generated_role_level(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_generated_role_level(value)


def validate_role_pair(generic_role: str, domain_role: Optional[str]) -> bool:
    if domain_role is None:
        return True
    return domain_role in _DOMAIN_ROLE_BY_GENERIC.get(generic_role, set())


def normalize_decision(decision: RoleDecision, allow_domain: bool = True) -> RoleDecision:
    reason = (decision.reason or "").strip()
    if reason:
        reason = reason.splitlines()[0].strip()
    normalized = RoleDecision(
        block_id=decision.block_id,
        generic_role=decision.generic_role,
        domain_role=decision.domain_role if allow_domain else None,
        role_confidence=round(max(0.0, min(1.0, decision.role_confidence)), 4),
        section_purpose=(decision.section_purpose or None),
        used_for_generation=decision.used_for_generation,
        reason=reason or None,
        needs_review=bool(decision.needs_review),
        generated_role_name=decision.generated_role_name,
        generated_role_description=decision.generated_role_description,
        generated_parent_role_name=decision.generated_parent_role_name,
        generated_role_level=decision.generated_role_level,
    )
    return enrich_generated_role(normalized)


def parse_role_decision(raw_text: str, expected_block_id: str) -> RoleDecision:
    try:
        payload = json.loads(_extract_json_text(raw_text))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    except ValueError:
        raise
    try:
        model = RoleDecisionModel.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("schema_mismatch") from exc
    if model.block_id != expected_block_id:
        raise ValueError("schema_mismatch")
    return normalize_decision(
        RoleDecision(
            block_id=model.block_id,
            generic_role=model.generic_role,
            domain_role=model.domain_role,
            role_confidence=model.role_confidence,
            section_purpose=model.section_purpose,
            used_for_generation=model.used_for_generation,
            reason=model.reason,
            needs_review=model.needs_review,
            generated_role_name=model.generated_role_name,
            generated_role_description=model.generated_role_description,
            generated_parent_role_name=model.generated_parent_role_name,
            generated_role_level=model.generated_role_level,
        )
    )
