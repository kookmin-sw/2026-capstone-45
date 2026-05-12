import math
import re
from typing import Any, Sequence

from llm2doc.artifact.semantic.semantic_pipeline.common.types import CanonicalBlock, CanonicalPage, PageAnalysis
from llm2doc.artifact.semantic.semantic_pipeline.common.utils import clean_text


TEXTUAL_LABELS = {
    "document_title",
    "section_heading",
    "subheading",
    "paragraph",
    "paragraph_or_meta",
    "section_heading_or_panel_title",
    "caption_or_panel_title",
    "meta_candidate",
    "footnote",
}
HEADING_LABELS = {"document_title", "section_heading", "subheading", "section_heading_or_panel_title"}
EVIDENCE_LABELS = {"table", "chart", "image"}
SHORT_SOURCE_RE = re.compile(r"^\s*(source|자료|주|note|출처|주석)\s*[:：]", re.IGNORECASE)


def zone_tags_for_block(block: CanonicalBlock) -> list[str]:
    tags: list[str] = []
    if block.bbox_norm[2] <= 0.35:
        tags.append("left_sidebar_zone")
    if block.bbox_norm[0] >= 0.32:
        tags.append("main_body_zone")
    if block.bbox_norm[3] <= 0.14:
        tags.append("top_meta_zone")
    if block.bbox_norm[1] >= 0.78:
        tags.append("bottom_meta_zone")
    if not tags:
        tags.append("unclassified_zone")
    return tags


def same_column(left: CanonicalBlock, right: CanonicalBlock | None) -> bool | None:
    if right is None:
        return None
    left_x1, _, left_x2, _ = left.bbox_norm
    right_x1, _, right_x2, _ = right.bbox_norm
    overlap = max(0.0, min(left_x2, right_x2) - max(left_x1, right_x1))
    min_width = max(min(left_x2 - left_x1, right_x2 - right_x1), 1e-6)
    return overlap / min_width >= 0.45


def normalized_distance(left: CanonicalBlock, right: CanonicalBlock | None) -> float | None:
    if right is None:
        return None
    lx1, ly1, lx2, ly2 = left.bbox_norm
    rx1, ry1, rx2, ry2 = right.bbox_norm
    lx = (lx1 + lx2) / 2.0
    ly = (ly1 + ly2) / 2.0
    rx = (rx1 + rx2) / 2.0
    ry = (ry1 + ry2) / 2.0
    return round(min(math.sqrt((lx - rx) ** 2 + (ly - ry) ** 2) / math.sqrt(2.0), 1.0), 4)


def _sorted_blocks(page: CanonicalPage) -> list[CanonicalBlock]:
    return sorted(page.blocks, key=lambda block: (block.reading_order, block.bbox_px[1], block.bbox_px[0]))


def _is_text_block(block: CanonicalBlock) -> bool:
    return block.canonical_label in TEXTUAL_LABELS and bool(clean_text(block.text))


def _is_heading(block: CanonicalBlock) -> bool:
    return block.canonical_label in HEADING_LABELS and bool(clean_text(block.text))


def _is_evidence(block: CanonicalBlock) -> bool:
    return block.canonical_label in EVIDENCE_LABELS


def _is_content_eligible(block: CanonicalBlock) -> bool:
    return bool(clean_text(block.text)) or block.canonical_label in EVIDENCE_LABELS


def _block_payload(block: CanonicalBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id,
        "structural_kind": block.canonical_label,
        "raw_label": block.raw_label,
        "canonical_label": block.canonical_label,
        "text": clean_text(block.text),
        "bbox_norm": list(block.bbox_norm),
        "reading_order": block.reading_order,
        "zone_tags": zone_tags_for_block(block),
    }


def _relation_payload(target: CanonicalBlock, candidate: CanonicalBlock) -> dict[str, Any]:
    return {
        "block_id": candidate.block_id,
        "text": clean_text(candidate.text),
        "structural_kind": candidate.canonical_label,
        "distance": normalized_distance(target, candidate),
        "same_column": same_column(target, candidate),
    }


def _nearby_blocks(
    blocks: Sequence[CanonicalBlock],
    target: CanonicalBlock,
    *,
    before: bool,
    predicate,
    limit: int,
) -> list[CanonicalBlock]:
    candidates = [
        block
        for block in blocks
        if block.block_id != target.block_id
        and predicate(block)
        and ((block.reading_order < target.reading_order) if before else (block.reading_order > target.reading_order))
    ]
    candidates.sort(key=lambda block: (abs(block.reading_order - target.reading_order), normalized_distance(target, block) or 1.0))
    return candidates[:limit]


def _build_non_content_hints(
    block: CanonicalBlock,
    repeated_texts: set[str],
) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    zones = zone_tags_for_block(block)
    text = clean_text(block.text)
    lowered = text.lower()
    if "top_meta_zone" in zones and text:
        hints.append({"type": "top_margin_text", "reason": "text appears near the top margin"})
    if "bottom_meta_zone" in zones and text:
        hints.append({"type": "bottom_margin_text", "reason": "text appears near the bottom margin"})
    if block.raw_label in {"header", "foot"}:
        hints.append({"type": "ocr_header_footer_label", "reason": "OCR label suggests header or footer"})
    if lowered and lowered in repeated_texts:
        hints.append({"type": "repeated_text", "reason": "same text appears on multiple pages"})
    if text.isdigit() and "bottom_meta_zone" in zones and len(text) <= 4:
        hints.append({"type": "page_number_pattern", "reason": "short numeric text appears near the bottom margin"})
    return hints


def _build_attachment_hints(blocks: Sequence[CanonicalBlock]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    previous_table_or_chart: CanonicalBlock | None = None
    for index, block in enumerate(blocks):
        if block.canonical_label in {"table", "chart", "image"}:
            previous_text = next((candidate for candidate in reversed(blocks[:index]) if _is_text_block(candidate)), None)
            if previous_text and same_column(block, previous_text):
                hints.append(
                    {
                        "block_id": block.block_id,
                        "hint": "likely_supports_previous_text",
                        "target_block_id": previous_text.block_id,
                        "reason": "evidence block follows nearby text in the same column",
                    }
                )
            previous_table_or_chart = block
            continue

        if previous_table_or_chart and _is_text_block(block) and same_column(block, previous_table_or_chart):
            text = clean_text(block.text)
            if len(text) <= 120 or SHORT_SOURCE_RE.search(text):
                hints.append(
                    {
                        "block_id": block.block_id,
                        "hint": "likely_caption_or_footnote_for_previous_evidence",
                        "target_block_id": previous_table_or_chart.block_id,
                        "reason": "short text appears near a preceding table/chart/image",
                    }
                )

    for index, block in enumerate(blocks):
        if not _is_heading(block):
            continue
        scoped_ids: list[str] = []
        for candidate in blocks[index + 1 :]:
            if _is_heading(candidate):
                break
            if same_column(block, candidate):
                scoped_ids.append(candidate.block_id)
            if len(scoped_ids) >= 8:
                break
        if scoped_ids:
            hints.append(
                {
                    "block_id": block.block_id,
                    "hint": "likely_heading_scope",
                    "target_block_ids": scoped_ids,
                    "reason": "same-column blocks follow this heading before the next heading",
                }
            )
    return hints


def build_page_passage_payload(
    *,
    page: CanonicalPage,
    analysis: PageAnalysis,
    repeating_elements: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    blocks = _sorted_blocks(page)
    repeated_texts = {clean_text(str(item.get("text", ""))).lower() for item in repeating_elements if item.get("text")}
    for block in blocks:
        block.non_content_hints = _build_non_content_hints(block, repeated_texts)

    block_contexts: list[dict[str, Any]] = []
    for block in blocks:
        previous_text = _nearby_blocks(blocks, block, before=True, predicate=_is_text_block, limit=2)
        next_text = _nearby_blocks(blocks, block, before=False, predicate=_is_text_block, limit=2)
        nearby_headings = sorted(
            [candidate for candidate in blocks if candidate.block_id != block.block_id and _is_heading(candidate)],
            key=lambda candidate: (normalized_distance(block, candidate) or 1.0, abs(block.reading_order - candidate.reading_order)),
        )[:2]
        nearby_evidence = sorted(
            [candidate for candidate in blocks if candidate.block_id != block.block_id and _is_evidence(candidate)],
            key=lambda candidate: (normalized_distance(block, candidate) or 1.0, abs(block.reading_order - candidate.reading_order)),
        )[:2]
        block_contexts.append(
            {
                **_block_payload(block),
                "content_eligible": _is_content_eligible(block),
                "non_content_hints": list(block.non_content_hints),
                "neighbor_context": {
                    "previous_text_blocks": [_relation_payload(block, candidate) for candidate in previous_text],
                    "next_text_blocks": [_relation_payload(block, candidate) for candidate in next_text],
                    "nearby_heading_candidates": [_relation_payload(block, candidate) for candidate in nearby_headings],
                    "nearby_evidence_candidates": [_relation_payload(block, candidate) for candidate in nearby_evidence],
                },
            }
        )

    return {
        "page": page.page,
        "page_layout_hints": {
            "column_count": analysis.column_count,
            "dominant_layout_pattern": analysis.dominant_layout_pattern,
            "text_area_ratio": analysis.text_area_ratio,
            "table_area_ratio": analysis.table_area_ratio,
            "visual_area_ratio": analysis.visual_area_ratio,
        },
        "blocks": block_contexts,
        "attachment_hints": _build_attachment_hints(blocks),
        "rules": {
            "cross_page_passages_allowed": False,
            "non_content_hints_are_weak_evidence": True,
        },
    }
