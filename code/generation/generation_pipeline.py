import json
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence, Tuple

from ..generation_backends import QwenGenerationAPIBackend, QwenGenerationBackend
from ..types import dataclass_to_dict
from ..utils import clean_text, ensure_dir, save_json
from .generation_schema import parse_slot_draft_response
from .generation_types import (
    GenerationConfig,
    GenerationRunSummary,
    GenerationTraceEntry,
    ReferenceSlot,
    SlotAssignment,
    SlotDraft,
    SlotWritePayload,
    SourceFact,
)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_reference_dir(path: str) -> Path:
    base = Path(path)
    if (base / "reference_template.json").exists():
        return base
    candidate = base / "01_reference"
    if (candidate / "reference_template.json").exists():
        return candidate
    raise FileNotFoundError(path)


def _token_count(text: str) -> int:
    return len(re.findall(r"\S+", clean_text(text)))


def _render_as_for_block(block: Dict[str, object]) -> str:
    generic_role = block.get("generic_role")
    if generic_role == "main_title":
        return "title"
    if generic_role == "section_heading":
        return "heading"
    if generic_role in {"metadata", "author_info"}:
        return "plain"
    return "paragraph"


def _should_preserve_reference_text(block: Dict[str, object]) -> bool:
    generic_role = block.get("generic_role")
    generated_role_name = block.get("generated_role_name") or ""
    if generic_role == "section_heading":
        return True
    if generic_role == "metadata" and generated_role_name in {
        "firm_branding_header",
        "research_brand_identifier",
        "sidebar_section_header",
    }:
        return True
    return False


def _reference_section_map(section_order: Sequence[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    mapping = {}
    for section in section_order or []:
        for block_id in section.get("block_ids", []):
            mapping[block_id] = section
    return mapping


def build_reference_blueprint(reference_artifact_dir: str) -> Dict[str, object]:
    artifact_dir = _resolve_reference_dir(reference_artifact_dir)
    template = _read_json(artifact_dir / "reference_template.json")
    section_map = _reference_section_map(template.get("section_order", []))
    blocks = sorted(
        template.get("blocks", []),
        key=lambda block: (block.get("page", 0), block.get("reading_order", 0)),
    )
    slots: List[ReferenceSlot] = []
    order_index = 0
    for block in blocks:
        if not block.get("used_for_generation"):
            continue
        if block.get("generic_role") == "disclaimer":
            continue
        text = clean_text(block.get("text", ""))
        if not text and not _should_preserve_reference_text(block):
            continue
        section = section_map.get(block.get("block_id"))
        slots.append(
            ReferenceSlot(
                slot_id="slot-%03d" % (order_index + 1),
                page=block.get("page", 1),
                order_index=order_index,
                block_id=block.get("block_id"),
                generic_role=block.get("generic_role"),
                domain_role=block.get("domain_role"),
                generated_role_name=block.get("generated_role_name"),
                generated_role_description=block.get("generated_role_description"),
                reference_text=text,
                render_as=_render_as_for_block(block),
                preserve_reference_text=_should_preserve_reference_text(block),
                section_id=section.get("section_id") if section else None,
                section_title=section.get("title") if section else None,
                target_word_count=max(3, _token_count(text)),
                prompt_hint=block.get("generated_role_description") or block.get("semantic_reason"),
            )
        )
        order_index += 1
    return {
        "reference_template_id": template.get("template_id"),
        "document_family": template.get("document_family"),
        "language": template.get("language"),
        "style_tokens": template.get("style_tokens", {}),
        "page_specs": template.get("page_specs", []),
        "slots": slots,
    }


def _strip_tags(value: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", value or ""))


def _extract_table_row_facts(block: Dict[str, object], quality_threshold: float) -> List[SourceFact]:
    text = block.get("text", "")
    rows = re.findall(r"<tr>(.*?)</tr>", text or "", re.IGNORECASE | re.DOTALL)
    if not rows:
        return []
    parsed_rows = []
    for row in rows:
        cells = re.findall(r"<t[dh]>(.*?)</t[dh]>", row, re.IGNORECASE | re.DOTALL)
        cleaned = [_strip_tags(cell) for cell in cells]
        cleaned = [cell for cell in cleaned if cell]
        if cleaned:
            parsed_rows.append(cleaned)
    if not parsed_rows:
        return []

    header = parsed_rows[0] if len(parsed_rows[0]) >= 3 else None
    facts: List[SourceFact] = []
    for index, cells in enumerate(parsed_rows):
        if index == 0 and header is not None:
            continue
        if len(cells) == 2:
            rendered = "%s: %s" % (cells[0], cells[1])
        elif len(cells) >= 3 and header is not None and len(header) == len(cells):
            metric_chunks = []
            for column_index in range(1, len(cells)):
                if not cells[column_index]:
                    continue
                metric_chunks.append("%s %s" % (header[column_index], cells[column_index]))
            rendered = "%s: %s" % (cells[0], ", ".join(metric_chunks))
        else:
            rendered = " | ".join(cells)
        if not rendered:
            continue
        facts.append(
            SourceFact(
                fact_id="%s-row-%02d" % (block.get("block_id"), index),
                kind="table_row",
                page=block.get("page", 1),
                block_ids=[block.get("block_id")],
                text=rendered,
                generic_role=block.get("generic_role"),
                domain_role=block.get("domain_role"),
                generated_role_name=block.get("generated_role_name"),
                section_id=None,
                section_title=None,
                used_for_generation=True,
                quality_score=max(float(block.get("text_quality_score") or 0.0), quality_threshold),
                metadata={"source_block_id": block.get("block_id")},
            )
        )
    return facts


def build_source_fact_pack(source_artifact_dir: str, quality_threshold: float = 0.55) -> Dict[str, object]:
    artifact_dir = _resolve_reference_dir(source_artifact_dir)
    template = _read_json(artifact_dir / "reference_template.json")
    section_map = _reference_section_map(template.get("section_order", []))
    blocks = sorted(
        template.get("blocks", []),
        key=lambda block: (block.get("page", 0), block.get("reading_order", 0)),
    )
    facts: List[SourceFact] = []
    for block in blocks:
        text = clean_text(block.get("text", ""))
        quality_score = float(block.get("text_quality_score") or 0.0)
        if text and quality_score >= quality_threshold and block.get("generic_role") != "disclaimer":
            section = section_map.get(block.get("block_id"))
            facts.append(
                SourceFact(
                    fact_id=block.get("block_id"),
                    kind="block",
                    page=block.get("page", 1),
                    block_ids=[block.get("block_id")],
                    text=text,
                    generic_role=block.get("generic_role"),
                    domain_role=block.get("domain_role"),
                    generated_role_name=block.get("generated_role_name"),
                    section_id=section.get("section_id") if section else None,
                    section_title=section.get("title") if section else None,
                    used_for_generation=block.get("used_for_generation"),
                    quality_score=quality_score,
                )
            )
        facts.extend(_extract_table_row_facts(block, quality_threshold))

    block_lookup = {block.get("block_id"): block for block in blocks}
    for section in template.get("section_order", []):
        chunk_texts = []
        for block_id in section.get("block_ids", []):
            text = clean_text(block_lookup.get(block_id, {}).get("text", ""))
            quality_score = float(block_lookup.get(block_id, {}).get("text_quality_score") or 0.0)
            if text and quality_score >= quality_threshold:
                chunk_texts.append(text)
        joined = clean_text("\n".join(chunk_texts))
        if not joined:
            continue
        first_block_id = section.get("block_ids", [None])[0]
        first_block = block_lookup.get(first_block_id, {})
        quality_values = [
            float(block_lookup.get(block_id, {}).get("text_quality_score") or 0.0)
            for block_id in section.get("block_ids", [])
        ]
        facts.append(
            SourceFact(
                fact_id=section.get("section_id"),
                kind="section",
                page=section.get("page", 1),
                block_ids=list(section.get("block_ids", [])),
                text=joined,
                generic_role=first_block.get("generic_role"),
                domain_role=first_block.get("domain_role"),
                generated_role_name=first_block.get("generated_role_name"),
                section_id=section.get("section_id"),
                section_title=section.get("title"),
                used_for_generation=True,
                quality_score=max(quality_values or [quality_threshold]),
                metadata={"purpose": section.get("purpose")},
            )
        )
    facts.sort(key=_fact_sort_key)
    return {
        "source_template_id": template.get("template_id"),
        "document_family": template.get("document_family"),
        "language": template.get("language"),
        "facts": facts,
    }


def _fact_sort_key(fact: SourceFact) -> Tuple[int, Tuple[int, ...], str]:
    return fact.page, _numeric_key(fact.fact_id), fact.fact_id


def _numeric_key(value: Optional[str]) -> Tuple[int, ...]:
    numbers = tuple(int(token) for token in re.findall(r"\d+", value or ""))
    return numbers or (0,)


def _unique_facts(facts: Sequence[SourceFact]) -> List[SourceFact]:
    unique: List[SourceFact] = []
    seen = set()
    for fact in facts:
        if not fact or fact.fact_id in seen:
            continue
        unique.append(fact)
        seen.add(fact.fact_id)
    return unique


def _pick_facts_by_keyword(facts: Sequence[SourceFact], keywords: Sequence[str], limit: int) -> List[SourceFact]:
    selected: List[SourceFact] = []
    seen = set()
    for keyword in keywords:
        for fact in facts:
            if fact.fact_id in seen:
                continue
            if keyword in fact.text:
                selected.append(fact)
                seen.add(fact.fact_id)
                break
    for fact in facts:
        if len(selected) >= limit:
            break
        if fact.fact_id in seen:
            continue
        selected.append(fact)
        seen.add(fact.fact_id)
    return selected[:limit]


def _build_source_groups(facts: Sequence[SourceFact]) -> Dict[str, object]:
    ordered = sorted(facts, key=_fact_sort_key)
    metadata_facts = [fact for fact in ordered if fact.generic_role == "metadata"]
    date_facts = [fact for fact in metadata_facts if re.search(r"\d{4}.*\d{1,2}.*\d{1,2}", fact.text)]
    research_facts = [fact for fact in metadata_facts if fact.domain_role == "research_center_meta"]
    author_facts = [fact for fact in ordered if fact.generic_role == "author_info" or fact.domain_role == "analyst_info"]
    opinion_facts = [
        fact
        for fact in ordered
        if fact.domain_role == "investment_opinion_box" and fact.kind == "block"
    ]
    price_rows = [
        fact
        for fact in ordered
        if fact.kind == "table_row" and ("목표주가" in fact.text or "현재주가" in fact.text)
    ]
    market_snapshot = [
        fact
        for fact in ordered
        if fact.kind == "table_row"
        and any(
            keyword in fact.text
            for keyword in [
                "KOSDAQ",
                "52주 최고/최저",
                "시가총액(",
                "외국인지분율",
                "주요주주",
                "김덕용",
                "60일 평균 거래량",
                "60일 평균 거래대금",
            ]
        )
    ]
    financial_rows = [
        fact for fact in ordered if fact.kind == "table_row" and fact.domain_role == "financial_table_block"
    ]
    financial_snapshot = _pick_facts_by_keyword(
        financial_rows,
        ["매출액", "영업이익", "증감율", "EPS"],
        4,
    )

    thesis_sections: Dict[str, Dict[str, object]] = {}
    for fact in ordered:
        if not fact.section_id:
            continue
        entry = thesis_sections.setdefault(
            fact.section_id,
            {"section_id": fact.section_id, "heading": None, "body": None, "section": None},
        )
        if fact.kind == "section" and fact.metadata.get("purpose") == "thesis":
            entry["section"] = fact
        if fact.kind == "block" and fact.generic_role == "section_heading" and (
            fact.domain_role == "thesis_heading" or _numeric_key(fact.section_id) >= (5,)
        ):
            entry["heading"] = fact
        if fact.generic_role == "body" and fact.domain_role == "supporting_argument":
            entry["body"] = fact

    ordered_sections = [thesis_sections[key] for key in sorted(thesis_sections, key=_numeric_key)]
    title_heading = None
    thesis_pairs = []
    headings_by_section: Dict[str, SourceFact] = {}
    for entry in ordered_sections:
        heading = entry.get("heading")
        body = entry.get("body")
        section_id = entry.get("section_id")
        if heading is not None and section_id:
            headings_by_section[section_id] = heading
        if heading is not None and body is None and title_heading is None:
            title_heading = heading
            continue
        if body is not None:
            thesis_pairs.append(entry)
    if title_heading is None:
        for entry in ordered_sections:
            if entry.get("heading") is not None:
                title_heading = entry.get("heading")
                break

    data_narrative = _unique_facts(opinion_facts[:1] + price_rows[:2] + financial_snapshot[:3])
    summary_snapshot = _unique_facts(opinion_facts[:1] + price_rows[:2])

    return {
        "date_facts": date_facts,
        "metadata_facts": metadata_facts,
        "research_facts": research_facts,
        "author_facts": author_facts,
        "opinion_facts": opinion_facts,
        "price_rows": price_rows,
        "summary_snapshot": summary_snapshot,
        "market_snapshot": market_snapshot,
        "financial_snapshot": financial_snapshot,
        "data_narrative": data_narrative,
        "title_heading": title_heading,
        "thesis_pairs": thesis_pairs,
        "headings_by_section": headings_by_section,
    }


def _score_fact_for_slot(slot: ReferenceSlot, fact: SourceFact, usage_counts: Dict[str, int]) -> float:
    score = 0.0
    if slot.preserve_reference_text:
        return -1.0
    if fact.quality_score is not None:
        score += max(0.0, min(1.0, fact.quality_score))
    if fact.used_for_generation:
        score += 0.4
    if slot.generic_role == fact.generic_role and slot.generic_role is not None:
        score += 1.4
    if slot.domain_role and slot.domain_role == fact.domain_role:
        score += 2.2
    if fact.metadata.get("purpose") == "evidence_panel" and slot.generic_role in {"main_title", "summary", "body"}:
        score -= 2.2
    if slot.generic_role == "main_title":
        if fact.domain_role == "thesis_heading":
            score += 2.0
        if fact.generic_role == "section_heading":
            score += 1.2
    elif slot.generic_role == "summary":
        if fact.domain_role == "investment_opinion_box":
            score += 2.0
        if fact.kind == "table_row":
            score += 1.0
    elif slot.generic_role == "body":
        if fact.domain_role == "supporting_argument":
            score += 2.1
        if fact.kind == "section":
            score += 1.6
        if fact.kind == "table_row":
            score += 0.8
    elif slot.generic_role in {"metadata", "author_info"}:
        if fact.generic_role in {"metadata", "author_info"}:
            score += 1.8
        if slot.generated_role_name and "date" in slot.generated_role_name and re.search(r"[0-9]{4}", fact.text):
            score += 1.2
    score -= usage_counts.get(fact.fact_id, 0) * 0.7
    return round(score, 4)


def _assignment_strategy(slot: ReferenceSlot, selected_facts: Sequence[SourceFact]) -> str:
    if slot.preserve_reference_text:
        return "preserve_reference"
    if slot.generic_role == "main_title":
        return "rewrite_title"
    if slot.generic_role == "summary":
        return "summary_from_source"
    if slot.generic_role == "body":
        return "narrative_from_source"
    if slot.generic_role in {"metadata", "author_info"}:
        return "metadata_fill"
    if slot.generic_role == "section_heading":
        return "preserve_reference"
    if not selected_facts:
        return "fallback_reference"
    return "source_fill"


def _make_assignment(
    slot: ReferenceSlot,
    selected: Sequence[SourceFact],
    *,
    strategy: str,
    rationale: str,
    confidence: float = 0.9,
    preserve_reference_text: bool = False,
) -> SlotAssignment:
    return SlotAssignment(
        slot_id=slot.slot_id,
        strategy=strategy,
        selected_fact_ids=[fact.fact_id for fact in _unique_facts(selected)],
        rationale=rationale,
        confidence=round(confidence, 4),
        preserve_reference_text=preserve_reference_text,
    )


def _planned_slot_assignment(
    slot: ReferenceSlot,
    groups: Dict[str, object],
    state: Dict[str, object],
    config: GenerationConfig,
) -> Optional[SlotAssignment]:
    role_name = slot.generated_role_name or ""

    if slot.preserve_reference_text:
        return _make_assignment(
            slot,
            [],
            strategy="preserve_reference",
            rationale="This slot carries stable template text, so the reference wording is preserved.",
            confidence=1.0,
            preserve_reference_text=True,
        )

    if slot.render_as == "title" or slot.generic_role == "main_title":
        title_fact = groups.get("title_heading")
        if title_fact is not None:
            return _make_assignment(
                slot,
                [title_fact],
                strategy="rewrite_title",
                rationale="Used the source report's primary thesis heading for the main title box.",
                confidence=0.96,
            )

    if slot.generic_role in {"metadata", "author_info"}:
        if "date" in role_name and groups.get("date_facts"):
            return _make_assignment(
                slot,
                [groups["date_facts"][0]],
                strategy="metadata_fill",
                rationale="Filled the date box with the publication date from the source report header.",
                confidence=0.95,
            )
        if slot.generic_role == "author_info" and groups.get("author_facts"):
            return _make_assignment(
                slot,
                [groups["author_facts"][0]],
                strategy="metadata_fill",
                rationale="Filled the analyst box with the source analyst metadata.",
                confidence=0.9,
            )
        if "research" in role_name and groups.get("research_facts"):
            return _make_assignment(
                slot,
                [groups["research_facts"][0]],
                strategy="metadata_fill",
                rationale="Filled the research-brand box with the source research center metadata.",
                confidence=0.9,
            )
        if groups.get("metadata_facts"):
            return _make_assignment(
                slot,
                [groups["metadata_facts"][0]],
                strategy="metadata_fill",
                rationale="Filled the metadata box with the closest source header metadata.",
                confidence=0.82,
            )

    if slot.generic_role == "summary":
        snapshot = groups.get("summary_snapshot") or []
        if snapshot:
            return _make_assignment(
                slot,
                snapshot[: config.max_facts_per_slot],
                strategy="summary_snapshot",
                rationale="Filled the short summary box with the investment opinion and price snapshot.",
                confidence=0.94,
            )

    if slot.generic_role == "body":
        if slot.target_word_count >= 35:
            thesis_pairs = groups.get("thesis_pairs") or []
            thesis_index = int(state.get("thesis_index", 0))
            if thesis_index < len(thesis_pairs):
                pair = thesis_pairs[thesis_index]
                state["thesis_index"] = thesis_index + 1
                state["last_thesis_section_id"] = pair.get("section_id")
                return _make_assignment(
                    slot,
                    [pair["body"]],
                    strategy="thesis_body_fill",
                    rationale="Filled the long narrative box with the next source thesis body in reading order.",
                    confidence=0.93,
                )
            if not state.get("used_data_narrative") and groups.get("data_narrative"):
                state["used_data_narrative"] = True
                state["last_thesis_section_id"] = None
                return _make_assignment(
                    slot,
                    groups["data_narrative"][: config.max_facts_per_slot],
                    strategy="data_snapshot_fill",
                    rationale="Filled the remaining long box with price and financial data from the source side panels.",
                    confidence=0.86,
                )
        if role_name == "market_movement_summary" and groups.get("summary_snapshot"):
            return _make_assignment(
                slot,
                groups["summary_snapshot"][: config.max_facts_per_slot],
                strategy="summary_snapshot",
                rationale="Filled the short summary line with the source opinion and price box.",
                confidence=0.92,
            )
        last_section_id = state.get("last_thesis_section_id")
        used_heading_sections = state.setdefault("used_heading_sections", set())
        if last_section_id:
            heading = (groups.get("headings_by_section") or {}).get(last_section_id)
            if heading is not None and last_section_id not in used_heading_sections:
                used_heading_sections.add(last_section_id)
                return _make_assignment(
                    slot,
                    [heading],
                    strategy="thesis_heading_fill",
                    rationale="Filled the short emphasis box with the heading for the preceding thesis section.",
                    confidence=0.91,
                )
        if not state.get("used_market_snapshot") and groups.get("market_snapshot"):
            state["used_market_snapshot"] = True
            return _make_assignment(
                slot,
                groups["market_snapshot"][: config.max_facts_per_slot],
                strategy="market_snapshot_fill",
                rationale="Filled the short data box with key market and ownership metrics from the source sidebar.",
                confidence=0.84,
            )
        if groups.get("financial_snapshot"):
            return _make_assignment(
                slot,
                groups["financial_snapshot"][: config.max_facts_per_slot],
                strategy="financial_snapshot_fill",
                rationale="Filled the remaining short box with compact financial metrics from the source tables.",
                confidence=0.8,
            )

    return None


def build_generation_plan(
    blueprint: Dict[str, object],
    fact_pack: Dict[str, object],
    config: Optional[GenerationConfig] = None,
) -> List[SlotAssignment]:
    config = config or GenerationConfig()
    slots = blueprint.get("slots", [])
    facts = fact_pack.get("facts", [])
    groups = _build_source_groups(facts)
    usage_counts: Dict[str, int] = {}
    state: Dict[str, object] = {
        "thesis_index": 0,
        "last_thesis_section_id": None,
        "used_data_narrative": False,
        "used_market_snapshot": False,
        "used_heading_sections": set(),
    }
    assignments: List[SlotAssignment] = []
    for slot in slots:
        planned = _planned_slot_assignment(slot, groups, state, config)
        if planned is not None:
            for fact_id in planned.selected_fact_ids:
                usage_counts[fact_id] = usage_counts.get(fact_id, 0) + 1
            assignments.append(planned)
            continue

        scored = []
        for fact in facts:
            score = _score_fact_for_slot(slot, fact, usage_counts)
            if score < config.min_fact_score:
                continue
            scored.append((score, fact))
        scored.sort(key=lambda item: (-item[0], item[1].fact_id))
        selected = [fact for _, fact in scored[: config.max_facts_per_slot]]
        if not selected and slot.generic_role in {"metadata", "author_info"}:
            assignments.append(
                _make_assignment(
                    slot,
                    [],
                    strategy="fallback_reference",
                    rationale="No reliable source metadata matched this slot, so the reference text is reused conservatively.",
                    confidence=0.4,
                    preserve_reference_text=True,
                )
            )
            continue
        for fact in selected:
            usage_counts[fact.fact_id] = usage_counts.get(fact.fact_id, 0) + 1
        top_score = scored[0][0] if scored else 0.45
        assignments.append(
            _make_assignment(
                slot,
                selected,
                strategy=_assignment_strategy(slot, selected),
                rationale="Selected the highest-scoring source facts for the slot role and order position.",
                confidence=min(1.0, top_score / 6.0),
            )
        )
    return assignments


def _truncate_text(text: str, target_word_count: int) -> str:
    text = clean_text(text)
    if not text or not target_word_count:
        return text
    if _token_count(text) <= target_word_count * 2:
        return text
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    kept = []
    current = 0
    for sentence in sentences:
        sentence = clean_text(sentence)
        if not sentence:
            continue
        kept.append(sentence)
        current += _token_count(sentence)
        if current >= target_word_count:
            break
    return clean_text(" ".join(kept)) or text


def _split_clean_lines(text: str) -> List[str]:
    return [clean_text(line) for line in (text or "").splitlines() if clean_text(line)]


def _title_text(text: str) -> str:
    lines = _split_clean_lines(text)
    if not lines:
        return clean_text(text)
    if len(lines) >= 2:
        return "%s: %s" % (lines[0], lines[1])
    return lines[0]


def _extract_display_date(text: str) -> str:
    cleaned = clean_text(text)
    year_month_day = re.search(r"(\d{4})\s*년\s*0?(\d{1,2})\s*월\s*0?(\d{1,2})\s*일", cleaned)
    if year_month_day:
        return "%s.%d.%d" % (
            year_month_day.group(1),
            int(year_month_day.group(2)),
            int(year_month_day.group(3)),
        )
    iso_date = re.search(r"(\d{4})[./-]\s*0?(\d{1,2})[./-]\s*0?(\d{1,2})", cleaned)
    if iso_date:
        return "%s.%d.%d" % (
            iso_date.group(1),
            int(iso_date.group(2)),
            int(iso_date.group(3)),
        )
    return cleaned.split("|")[0].strip() if "|" in cleaned else cleaned


def _parse_metric_text(text: str) -> Tuple[str, str]:
    cleaned = clean_text(text)
    if ":" in cleaned:
        label, value = cleaned.split(":", 1)
        return clean_text(label), clean_text(value)
    if "|" in cleaned:
        parts = [clean_text(part) for part in cleaned.split("|") if clean_text(part)]
        if len(parts) >= 2:
            return parts[0], ", ".join(parts[1:])
    return cleaned, ""


def _topic_particle(label: str) -> str:
    cleaned = clean_text(label)
    if not cleaned:
        return "은"
    last = cleaned[-1]
    if "가" <= last <= "힣":
        return "은" if (ord(last) - ord("가")) % 28 else "는"
    return "는"


def _render_metric_sentence(text: str) -> str:
    label, value = _parse_metric_text(text)
    base_label = clean_text(re.sub(r"\([^)]*\)", "", label)) or label
    particle = _topic_particle(base_label)
    if not value:
        return clean_text(text)
    if "목표주가" in label:
        return "목표주가%s %s이다." % (_topic_particle("목표주가"), value)
    if "현재주가" in label:
        return "현재주가%s %s이다." % (_topic_particle("현재주가"), value)
    if "|" in text:
        pipe_parts = [clean_text(part) for part in clean_text(text).split("|") if clean_text(part)]
        if len(pipe_parts) >= 3:
            return "%s%s 2025년 %s, 2026년 %s이다." % (
                base_label,
                particle,
                pipe_parts[1],
                pipe_parts[2],
            )
    if "매출액" in label and "2026F" in value:
        match = re.search(r"2026F\s*([^,\s]+)", value)
        if match:
            return "2026년 예상 매출액은 %s이다." % match.group(1)
    if "영업이익" in label and "2026F" in value:
        match = re.search(r"2026F\s*([^,\s]+)", value)
        if match:
            return "2026년 예상 영업이익은 %s로 흑자 전환이 예상된다." % match.group(1)
    if "증감율" in label and "흑전" in value:
        return "2026년에는 흑자 전환이 예상된다."
    if "영업이익" in label and "," in value:
        parts = [chunk.strip() for chunk in value.split(",") if chunk.strip()]
        if len(parts) >= 2:
            return "%s%s %s에서 %s로 개선될 전망이다." % (base_label, particle, parts[0], parts[-1])
    if "52주 최고/최저" in label:
        return "52주 최고/최저는 %s이다." % value
    if "시가총액" in label and "비중" not in label:
        return "%s%s %s이다." % (base_label, particle, value)
    if "외국인지분율" in label and not value.endswith("%"):
        return "%s%s %s%%다." % (base_label, particle, value)
    return "%s%s %s이다." % (base_label, particle, value)


def _compose_summary_text(facts: Sequence[SourceFact], target_word_count: int) -> str:
    rating = next((clean_text(fact.text) for fact in facts if fact.domain_role == "investment_opinion_box"), "")
    target_value = ""
    current_value = ""
    for fact in facts:
        label, value = _parse_metric_text(fact.text)
        if "목표주가" in label:
            target_value = value
        elif "현재주가" in label:
            current_value = value
    if target_word_count <= 14:
        parts = []
        if rating:
            parts.append(rating)
        compact = []
        if target_value:
            compact.append("목표주가 %s" % target_value)
        if current_value:
            compact.append("현재주가 %s" % current_value)
        if compact:
            parts.append(", ".join(compact))
        return clean_text(". ".join(parts) + ".")
    sentences = []
    if rating:
        sentences.append("%s 의견을 유지한다." % rating)
    if target_value:
        sentences.append("목표주가는 %s이다." % target_value)
    if current_value:
        sentences.append("현재주가는 %s이다." % current_value)
    return clean_text(" ".join(sentences))


def _compose_metric_block(facts: Sequence[SourceFact], target_word_count: int) -> str:
    sentences = [_render_metric_sentence(fact.text) for fact in facts if clean_text(fact.text)]
    sentences = [clean_text(sentence) for sentence in sentences if clean_text(sentence)]
    if not sentences:
        return clean_text(" ".join(fact.text for fact in facts))
    if target_word_count <= 12:
        return clean_text(" / ".join(sentence.rstrip(".") for sentence in sentences[:2]))
    if target_word_count <= 28:
        return clean_text(" ".join(sentences[:2]))
    return clean_text(" ".join(sentences[: min(4, len(sentences))]))


def _rule_slot_text(slot: ReferenceSlot, assignment: SlotAssignment, fact_lookup: Dict[str, SourceFact]) -> SlotDraft:
    if assignment.preserve_reference_text or not assignment.selected_fact_ids:
        return SlotDraft(
            slot_id=slot.slot_id,
            text=slot.reference_text,
            source_fact_ids=list(assignment.selected_fact_ids),
            citations=list(assignment.selected_fact_ids),
            rationale=assignment.rationale,
            needs_review=not bool(slot.reference_text),
            render_as=slot.render_as,
            section_id=slot.section_id,
            used_reference_text=True,
        )

    facts = [fact_lookup[fact_id] for fact_id in assignment.selected_fact_ids if fact_id in fact_lookup]
    snippets = [fact.text for fact in facts if fact.text]
    if slot.render_as == "title":
        text = _title_text(snippets[0])
    elif slot.render_as == "plain":
        if slot.generated_role_name and "date" in slot.generated_role_name:
            text = _extract_display_date(snippets[0])
        else:
            text = clean_text(snippets[0])
    elif slot.generic_role == "summary" and any(fact.domain_role == "investment_opinion_box" for fact in facts):
        text = _compose_summary_text(facts, slot.target_word_count)
    elif all(fact.kind == "table_row" for fact in facts):
        text = _compose_metric_block(facts, slot.target_word_count)
    elif len(facts) == 1 and facts[0].generic_role == "section_heading":
        text = clean_text(facts[0].text)
    else:
        rendered_parts = []
        for fact in facts:
            if fact.kind == "table_row":
                rendered_parts.append(_render_metric_sentence(fact.text))
            else:
                rendered_parts.append(fact.text)
        text = _truncate_text(clean_text(" ".join(rendered_parts)), slot.target_word_count)
    if slot.target_word_count and slot.render_as == "paragraph":
        text = _truncate_text(text, slot.target_word_count)
    return SlotDraft(
        slot_id=slot.slot_id,
        text=text,
        source_fact_ids=list(assignment.selected_fact_ids),
        citations=list(assignment.selected_fact_ids),
        rationale=assignment.rationale,
        needs_review=False,
        render_as=slot.render_as,
        section_id=slot.section_id,
        used_reference_text=False,
    )


def _build_trace(
    *,
    stage: str,
    slot: ReferenceSlot,
    payload: Dict[str, object],
    raw_response: Optional[str],
    parsed_payload: Optional[Dict[str, object]],
    applied_payload: Dict[str, object],
    fallback_reason: Optional[str],
    latency_ms: int,
) -> GenerationTraceEntry:
    return GenerationTraceEntry(
        stage=stage,
        slot_id=slot.slot_id,
        input_payload=payload,
        raw_response=raw_response[:4000] if raw_response else None,
        parsed_payload=parsed_payload,
        applied_payload=applied_payload,
        fallback_reason=fallback_reason,
        latency_ms=latency_ms,
    )


def _resolve_slot_draft(
    *,
    slot: ReferenceSlot,
    assignment: SlotAssignment,
    fact_lookup: Dict[str, SourceFact],
    blueprint: Dict[str, object],
    fact_pack: Dict[str, object],
    config: GenerationConfig,
    backend: Optional[QwenGenerationAPIBackend] = None,
) -> Tuple[SlotDraft, Optional[GenerationTraceEntry], bool]:
    fallback_draft = _rule_slot_text(slot, assignment, fact_lookup)
    if slot.preserve_reference_text or assignment.preserve_reference_text or config.mode == "rule":
        return fallback_draft, None, False

    selected_facts = [fact_lookup[fact_id] for fact_id in assignment.selected_fact_ids if fact_id in fact_lookup]
    payload = SlotWritePayload(
        slot_id=slot.slot_id,
        document_family=blueprint.get("document_family"),
        source_language=fact_pack.get("language") or blueprint.get("language") or "unknown",
        slot={
            "slot_id": slot.slot_id,
            "render_as": slot.render_as,
            "generic_role": slot.generic_role,
            "domain_role": slot.domain_role,
            "generated_role_name": slot.generated_role_name,
            "generated_role_description": slot.generated_role_description,
            "reference_text": slot.reference_text,
            "section_title": slot.section_title,
            "target_word_count": slot.target_word_count,
            "prompt_hint": slot.prompt_hint,
        },
        selected_facts=[
            {
                "fact_id": fact.fact_id,
                "kind": fact.kind,
                "text": fact.text,
                "generic_role": fact.generic_role,
                "domain_role": fact.domain_role,
                "generated_role_name": fact.generated_role_name,
                "section_title": fact.section_title,
            }
            for fact in selected_facts
        ],
        style_tokens=blueprint.get("style_tokens", {}),
    )
    payload_dict = dataclass_to_dict(payload)
    runtime_backend = backend or QwenGenerationAPIBackend()
    raw_response = None
    latency_ms = 0
    try:
        raw_response, latency_ms = runtime_backend.write_slot(payload, config)
        parsed = parse_slot_draft_response(raw_response, slot.slot_id)
        parsed.source_fact_ids = list(assignment.selected_fact_ids)
        parsed.render_as = slot.render_as
        parsed.section_id = slot.section_id
        parsed.used_reference_text = False
        trace = _build_trace(
            stage="write_slot",
            slot=slot,
            payload=payload_dict,
            raw_response=raw_response,
            parsed_payload=dataclass_to_dict(parsed),
            applied_payload=dataclass_to_dict(parsed),
            fallback_reason=None,
            latency_ms=latency_ms,
        )
        return parsed, trace, True
    except Exception as exc:
        trace = _build_trace(
            stage="write_slot",
            slot=slot,
            payload=payload_dict,
            raw_response=raw_response,
            parsed_payload=None,
            applied_payload=dataclass_to_dict(fallback_draft),
            fallback_reason=str(exc) or "backend_error",
            latency_ms=latency_ms,
        )
        fallback_draft.needs_review = True
        return fallback_draft, trace, False


def _render_markdown(drafts: Sequence[SlotDraft]) -> str:
    lines: List[str] = []
    for draft in drafts:
        text = clean_text(draft.text)
        if not text:
            continue
        if draft.render_as == "title":
            lines.append("# %s" % text)
        elif draft.render_as == "heading":
            lines.append("## %s" % text)
        else:
            lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _section_groups(drafts: Sequence[SlotDraft]) -> List[List[SlotDraft]]:
    groups: List[List[SlotDraft]] = []
    current_items: List[SlotDraft] = []
    for draft in drafts:
        if current_items and draft.render_as in {"heading", "title"}:
            groups.append(current_items)
            current_items = []
        current_items.append(draft)
    if current_items:
        groups.append(current_items)
    return groups


def _render_html(blueprint: Dict[str, object], drafts: Sequence[SlotDraft]) -> str:
    style_tokens = blueprint.get("style_tokens", {})
    body_px = max(15, int(round(float(style_tokens.get("body_font_scale", 0.028)) * 580)))
    title_px = max(body_px + 8, int(round(body_px * float(style_tokens.get("title_font_scale", 1.8)))))
    subtitle_scale = float(style_tokens.get("subtitle_font_scale", 1.25))
    heading_px = max(body_px + 2, int(round(body_px * max(1.1, subtitle_scale))))
    column_count = max(1, int(style_tokens.get("column_count", 1) or 1))
    body_chunks = []
    for items in _section_groups(drafts):
        html_lines = ['<section class="doc-section">']
        for draft in items:
            text = clean_text(draft.text)
            if not text:
                continue
            escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if draft.render_as == "title":
                html_lines.append("<h1>%s</h1>" % escaped)
            elif draft.render_as == "heading":
                html_lines.append("<h2>%s</h2>" % escaped)
            else:
                klass = "meta" if draft.render_as == "plain" else "body"
                html_lines.append('<p class="%s">%s</p>' % (klass, escaped))
        html_lines.append("</section>")
        body_chunks.append("\n".join(html_lines))
    return """<!doctype html>
<html lang=\"ko\">
  <head>
    <meta charset=\"utf-8\" />
    <title>Generated Document</title>
    <style>
      :root {
        --body-size: %dpx;
        --title-size: %dpx;
        --heading-size: %dpx;
        --column-count: %d;
      }
      body {
        margin: 0;
        background: #f5f1e8;
        color: #1b1b1b;
        font-family: \"Georgia\", \"Times New Roman\", serif;
      }
      .page {
        max-width: 980px;
        margin: 32px auto;
        background: #fffdf8;
        padding: 48px 54px 64px;
        box-shadow: 0 16px 40px rgba(34, 28, 18, 0.10);
      }
      .content {
        column-count: var(--column-count);
        column-gap: 40px;
      }
      .doc-section {
        break-inside: avoid;
        margin-bottom: 22px;
      }
      h1 {
        font-size: var(--title-size);
        line-height: 1.15;
        margin: 0 0 18px;
      }
      h2 {
        font-size: var(--heading-size);
        line-height: 1.25;
        margin: 0 0 12px;
      }
      p {
        font-size: var(--body-size);
        line-height: 1.55;
        margin: 0 0 12px;
      }
      .meta {
        font-size: max(13px, calc(var(--body-size) * 0.92));
        color: #5c564b;
      }
      @media (max-width: 820px) {
        .page {
          margin: 0;
          padding: 28px 22px 40px;
          box-shadow: none;
        }
        .content {
          column-count: 1;
        }
      }
    </style>
  </head>
  <body>
    <main class=\"page\">
      <div class=\"content\">
        %s
      </div>
    </main>
  </body>
</html>
""" % (
        body_px,
        title_px,
        heading_px,
        column_count,
        "\n".join(body_chunks),
    )


def build_generated_document(
    reference_artifact_dir: str,
    source_artifact_dir: str,
    generation_config: Optional[GenerationConfig] = None,
) -> Tuple[Dict[str, object], Dict[str, object], List[SlotAssignment], List[SlotDraft], Dict[str, object], str, str]:
    generation_config = generation_config or GenerationConfig()
    blueprint = build_reference_blueprint(reference_artifact_dir)
    fact_pack = build_source_fact_pack(source_artifact_dir, quality_threshold=generation_config.quality_threshold)
    plan = build_generation_plan(blueprint, fact_pack, config=generation_config)
    slots = blueprint.get("slots", [])
    fact_lookup = {fact.fact_id: fact for fact in fact_pack.get("facts", [])}
    plan_lookup = {item.slot_id: item for item in plan}
    drafts: List[SlotDraft] = []
    traces: List[GenerationTraceEntry] = []
    generated_count = 0
    preserved_count = 0
    fallback_count = 0
    needs_review_count = 0

    def process_slot(slot):
        assignment = plan_lookup[slot.slot_id]
        return _resolve_slot_draft(
            slot=slot,
            assignment=assignment,
            fact_lookup=fact_lookup,
            blueprint=blueprint,
            fact_pack=fact_pack,
            config=generation_config,
        )

    from tqdm import tqdm
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(tqdm(executor.map(process_slot, slots), total=len(slots), desc="Generating slots"))

    for draft, trace, used_model in results:
        drafts.append(draft)
        if trace is not None:
            traces.append(trace)
            if trace.fallback_reason:
                fallback_count += 1
        if used_model:
            generated_count += 1
        if draft.used_reference_text:
            preserved_count += 1
        if draft.needs_review:
            needs_review_count += 1

    markdown = _render_markdown(drafts)
    html_output = _render_html(blueprint, drafts)
    
    backend_name = "rule"
    if generation_config.mode == "qwen":
        backend_name = "qwen_generation_api" if generation_config.runtime == "api" else "qwen_generation_transformers"

    summary = GenerationRunSummary(
        mode=generation_config.mode,
        backend=backend_name,
        model_name=generation_config.model_name if generation_config.mode == "qwen" else None,
        prompt_version=generation_config.prompt_version if generation_config.mode == "qwen" else None,
        slot_count=len(slots),
        generated_slot_count=generated_count,
        preserved_slot_count=preserved_count,
        fallback_count=fallback_count,
        needs_review_count=needs_review_count,
        trace=traces,
    )
    diagnostics = {
        "reference_artifact_dir": str(_resolve_reference_dir(reference_artifact_dir)),
        "source_artifact_dir": str(_resolve_reference_dir(source_artifact_dir)),
        "summary": summary,
    }
    return blueprint, fact_pack, plan, drafts, diagnostics, markdown, html_output


def generate_document(
    job_id: str,
    reference_artifact_dir: str,
    source_artifact_dir: str,
    artifacts_root: str = "artifacts",
    generation_config: Optional[GenerationConfig] = None,
) -> Dict[str, str]:
    blueprint, fact_pack, plan, drafts, diagnostics, markdown, html_output = build_generated_document(
        reference_artifact_dir=reference_artifact_dir,
        source_artifact_dir=source_artifact_dir,
        generation_config=generation_config,
    )
    artifact_root = Path(artifacts_root) / job_id
    generation_dir = ensure_dir(artifact_root / "02_generation")
    render_dir = ensure_dir(artifact_root / "03_render")

    blueprint_path = generation_dir / "reference_blueprint.json"
    fact_pack_path = generation_dir / "source_fact_pack.json"
    plan_path = generation_dir / "generation_plan.json"
    drafts_path = generation_dir / "slot_drafts.json"
    diagnostics_path = generation_dir / "generation_diagnostics.json"
    trace_path = generation_dir / "generation_trace.json"
    markdown_path = render_dir / "generated_document.md"
    html_path = render_dir / "generated_document.html"

    save_json(blueprint_path, dataclass_to_dict(blueprint))
    save_json(fact_pack_path, dataclass_to_dict(fact_pack))
    save_json(plan_path, dataclass_to_dict(plan))
    save_json(drafts_path, dataclass_to_dict(drafts))
    save_json(diagnostics_path, dataclass_to_dict(diagnostics))
    summary_dict = dataclass_to_dict(diagnostics["summary"])
    trace = summary_dict.get("trace", [])
    if trace:
        save_json(trace_path, trace)
    markdown_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html_output, encoding="utf-8")

    result = {
        "artifact_dir": str(artifact_root),
        "reference_blueprint": str(blueprint_path),
        "source_fact_pack": str(fact_pack_path),
        "generation_plan": str(plan_path),
        "slot_drafts": str(drafts_path),
        "generation_diagnostics": str(diagnostics_path),
        "markdown": str(markdown_path),
        "html": str(html_path),
    }
    if trace:
        result["generation_trace"] = str(trace_path)
    return result
