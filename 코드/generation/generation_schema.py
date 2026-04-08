import json
import re
from typing import List

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .generation_types import SlotDraft
from ..utils import clean_text


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


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


class SlotDraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str
    text: str
    citations: List[str]
    rationale: str
    needs_review: bool

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        cleaned = clean_text(value)
        if not cleaned:
            raise ValueError("text must be non-empty")
        return cleaned

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str) -> str:
        cleaned = clean_text(value)
        if not cleaned:
            raise ValueError("rationale must be non-empty")
        return cleaned.splitlines()[0]

    @field_validator("citations")
    @classmethod
    def _validate_citations(cls, value: List[str]) -> List[str]:
        cleaned = []
        seen = set()
        for item in value or []:
            current = (item or "").strip()
            if not current or current in seen:
                continue
            cleaned.append(current)
            seen.add(current)
        return cleaned


def normalize_slot_draft(draft: SlotDraft) -> SlotDraft:
    return SlotDraft(
        slot_id=draft.slot_id,
        text=clean_text(draft.text),
        source_fact_ids=list(draft.source_fact_ids),
        citations=list(dict.fromkeys(draft.citations)),
        rationale=(clean_text(draft.rationale or "") or None),
        needs_review=bool(draft.needs_review),
        render_as=draft.render_as,
        section_id=draft.section_id,
        used_reference_text=bool(draft.used_reference_text),
    )


def parse_slot_draft_response(raw_text: str, expected_slot_id: str) -> SlotDraft:
    try:
        payload = json.loads(_extract_json_text(raw_text))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    except ValueError:
        raise
    try:
        model = SlotDraftModel.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("schema_mismatch") from exc
    if model.slot_id != expected_slot_id:
        raise ValueError("schema_mismatch")
    return normalize_slot_draft(
        SlotDraft(
            slot_id=model.slot_id,
            text=model.text,
            source_fact_ids=[],
            citations=model.citations,
            rationale=model.rationale,
            needs_review=model.needs_review,
        )
    )
