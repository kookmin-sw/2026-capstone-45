import json
import re
from typing import Any, Sequence

from llm2doc.artifact.semantic.semantic_pipeline.common.types import (
    CanonicalBlock,
    CanonicalPage,
    ExcludedBlock,
    SemanticPassage,
)
from llm2doc.artifact.semantic.semantic_pipeline.common.utils import clean_text


REGEX_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
EVIDENCE_LABELS = {"table", "chart", "image"}
HEADING_LABELS = {"document_title", "section_heading", "subheading", "section_heading_or_panel_title"}


def parse_passage_response(raw_response: str) -> dict[str, Any]:
    stripped = raw_response.strip()
    fence_match = REGEX_JSON_FENCE.fullmatch(stripped)
    if fence_match is not None:
        stripped = fence_match.group(1).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(parsed, dict):
        raise ValueError("schema_mismatch")
    if not isinstance(parsed.get("passages"), list):
        raise ValueError("schema_mismatch")
    if "excluded_blocks" in parsed and not isinstance(parsed.get("excluded_blocks"), list):
        raise ValueError("schema_mismatch")
    return parsed


def fallback_passage_result(page: CanonicalPage) -> dict[str, Any]:
    passages: list[dict[str, Any]] = []
    current: list[str] = []
    for block in _ordered_blocks(page):
        if not _is_content_eligible(block):
            continue
        if block.canonical_label in HEADING_LABELS and current:
            passages.append({"block_ids": current, "title": "", "summary": "", "main_function": "content passage"})
            current = []
        current.append(block.block_id)
        if len(current) >= 8:
            passages.append({"block_ids": current, "title": "", "summary": "", "main_function": "content passage"})
            current = []
    if current:
        passages.append({"block_ids": current, "title": "", "summary": "", "main_function": "content passage"})
    return {"passages": passages, "excluded_blocks": []}


def repair_passage_result(
    *,
    page: CanonicalPage,
    parsed_result: dict[str, Any],
    passage_start_index: int,
    max_blocks_per_passage: int = 8,
) -> tuple[list[SemanticPassage], list[ExcludedBlock], dict[str, Any], int]:
    blocks = _ordered_blocks(page)
    block_by_id = {block.block_id: block for block in blocks}
    valid_ids = set(block_by_id)
    content_ids = {block.block_id for block in blocks if _is_content_eligible(block)}
    assigned: set[str] = set()

    normalized_passage_blocks: list[tuple[list[str], dict[str, str]]] = []
    for item in parsed_result.get("passages") or []:
        if not isinstance(item, dict):
            continue
        block_ids = _coerce_str_list(item.get("block_ids"))
        cleaned_ids: list[str] = []
        for block_id in block_ids:
            if block_id not in valid_ids or block_id in assigned:
                continue
            cleaned_ids.append(block_id)
            assigned.add(block_id)
        if cleaned_ids:
            normalized_passage_blocks.append(
                (
                    _sort_block_ids(cleaned_ids, block_by_id),
                    {
                        "title": _coerce_text(item.get("title")),
                        "summary": _coerce_text(item.get("summary")),
                        "main_function": _coerce_text(item.get("main_function")),
                    },
                )
            )

    excluded_by_id: dict[str, str] = {}
    for item in parsed_result.get("excluded_blocks") or []:
        if not isinstance(item, dict):
            continue
        block_id = _coerce_text(item.get("block_id"))
        if block_id not in valid_ids or block_id in assigned or block_id in excluded_by_id:
            continue
        excluded_by_id[block_id] = _coerce_text(item.get("reason")) or "excluded_by_passage_grouping"

    for block_id in _sort_block_ids(list(content_ids - assigned - set(excluded_by_id)), block_by_id):
        normalized_passage_blocks.append(
            ([block_id], {"title": "", "summary": "", "main_function": "singleton_content_block"})
        )
        assigned.add(block_id)

    final_block_groups: list[tuple[list[str], dict[str, str]]] = []
    for block_ids, metadata in normalized_passage_blocks:
        final_block_groups.extend(_split_large_group(block_ids, metadata, block_by_id, max_blocks_per_passage))

    passages: list[SemanticPassage] = []
    for offset, (block_ids, metadata) in enumerate(final_block_groups, start=passage_start_index):
        passage_id = f"passage-{offset:04d}"
        passage_blocks = [block_by_id[block_id] for block_id in block_ids]
        title = metadata["title"] or _derive_title(passage_blocks)
        summary = metadata["summary"] or _derive_summary(passage_blocks)
        main_function = metadata["main_function"] or "content passage"
        retrieval_text = _build_retrieval_text(title, summary, main_function, passage_blocks)
        representative_block_id = block_ids[0]
        for block in passage_blocks:
            block.passage_id = passage_id
            block.content_status = "content"
            block.section_id = passage_id
            block.section_purpose = main_function
        passages.append(
            SemanticPassage(
                passage_id=passage_id,
                page_span=[page.page, page.page],
                block_ids=block_ids,
                title=title,
                summary=summary,
                main_function=main_function,
                retrieval_text=retrieval_text,
                representative_block_id=representative_block_id,
            )
        )

    excluded_blocks: list[ExcludedBlock] = []
    for block_id in _sort_block_ids(list(excluded_by_id), block_by_id):
        block = block_by_id[block_id]
        block.passage_id = None
        block.content_status = "excluded"
        excluded_blocks.append(ExcludedBlock(block_id=block_id, reason=excluded_by_id[block_id]))

    repaired_result = {
        "passages": [
            {
                "passage_id": passage.passage_id,
                "block_ids": passage.block_ids,
                "title": passage.title,
                "summary": passage.summary,
                "main_function": passage.main_function,
            }
            for passage in passages
        ],
        "excluded_blocks": [{"block_id": item.block_id, "reason": item.reason} for item in excluded_blocks],
    }
    return passages, excluded_blocks, repaired_result, passage_start_index + len(passages)


def _ordered_blocks(page: CanonicalPage) -> list[CanonicalBlock]:
    return sorted(page.blocks, key=lambda block: (block.reading_order, block.bbox_px[1], block.bbox_px[0]))


def _is_content_eligible(block: CanonicalBlock) -> bool:
    return bool(clean_text(block.text)) or block.canonical_label in EVIDENCE_LABELS


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_coerce_text(item) for item in value if _coerce_text(item)]


def _sort_block_ids(block_ids: Sequence[str], block_by_id: dict[str, CanonicalBlock]) -> list[str]:
    return sorted(block_ids, key=lambda block_id: block_by_id[block_id].reading_order)


def _split_large_group(
    block_ids: list[str],
    metadata: dict[str, str],
    block_by_id: dict[str, CanonicalBlock],
    max_blocks_per_passage: int,
) -> list[tuple[list[str], dict[str, str]]]:
    if len(block_ids) <= max_blocks_per_passage:
        return [(block_ids, metadata)]
    heading_groups: list[list[str]] = []
    current: list[str] = []
    for block_id in block_ids:
        block = block_by_id[block_id]
        if current and block.canonical_label in HEADING_LABELS:
            heading_groups.append(current)
            current = []
        current.append(block_id)
    if current:
        heading_groups.append(current)

    result: list[tuple[list[str], dict[str, str]]] = []
    for group in heading_groups:
        for index in range(0, len(group), max_blocks_per_passage):
            result.append((group[index : index + max_blocks_per_passage], metadata))
    return result


def _derive_title(blocks: Sequence[CanonicalBlock]) -> str:
    for block in blocks:
        if block.canonical_label in HEADING_LABELS and clean_text(block.text):
            return clean_text(block.text).splitlines()[0][:120]
    for block in blocks:
        if clean_text(block.text):
            return clean_text(block.text).splitlines()[0][:80]
    return "Untitled passage"


def _derive_summary(blocks: Sequence[CanonicalBlock]) -> str:
    text = " ".join(clean_text(block.text) for block in blocks if clean_text(block.text))
    return text[:240] if text else "Non-text visual or evidence passage."


def _build_retrieval_text(
    title: str,
    summary: str,
    main_function: str,
    blocks: Sequence[CanonicalBlock],
) -> str:
    parts = [
        f"title: {title}",
        f"summary: {summary}",
        f"main_function: {main_function}",
        "content:",
    ]
    for block in blocks:
        text = clean_text(block.text)
        label = block.canonical_label
        if text:
            parts.append(f"[{label}] {text}")
        elif label in EVIDENCE_LABELS:
            parts.append(f"[{label}]")
    return "\n".join(parts)
