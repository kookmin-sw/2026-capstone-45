import math
from typing import Any, Dict, List, Sequence

from .semantic_schema import DOMAIN_ROLES, GENERIC_ROLES
from .semantic_types import BlockContextPayload, SemanticConfig
from ..common.types import CanonicalBlock, CanonicalPage, PageAnalysis
from ..common.utils import clean_text


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


def _zone_tags_for_block(block: CanonicalBlock) -> List[str]:
    tags: List[str] = []
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


def _primary_zone(block: CanonicalBlock) -> str:
    return _zone_tags_for_block(block)[0]


def _block_metrics(block: CanonicalBlock) -> Dict[str, float]:
    x1, y1, x2, y2 = block.bbox_norm
    width_ratio = max(0.0, x2 - x1)
    height_ratio = max(0.0, y2 - y1)
    return {
        "center_x": round((x1 + x2) / 2.0, 4),
        "center_y": round((y1 + y2) / 2.0, 4),
        "width_ratio": round(width_ratio, 4),
        "height_ratio": round(height_ratio, 4),
        "area_ratio": round(width_ratio * height_ratio, 4),
    }


def _block_center(block: CanonicalBlock) -> Sequence[float]:
    metrics = _block_metrics(block)
    return (metrics["center_x"], metrics["center_y"])


def _normalized_center_distance(left: CanonicalBlock, right: CanonicalBlock) -> float:
    lx, ly = _block_center(left)
    rx, ry = _block_center(right)
    return min(math.sqrt((lx - rx) ** 2 + (ly - ry) ** 2) / math.sqrt(2.0), 1.0)


def _horizontal_overlap_ratio(left: CanonicalBlock, right: CanonicalBlock) -> float:
    left_x1, _, left_x2, _ = left.bbox_norm
    right_x1, _, right_x2, _ = right.bbox_norm
    overlap = max(0.0, min(left_x2, right_x2) - max(left_x1, right_x1))
    min_width = max(min(left_x2 - left_x1, right_x2 - right_x1), 1e-6)
    return min(overlap / min_width, 1.0)


def _same_column(left: CanonicalBlock, right: CanonicalBlock) -> bool:
    return _horizontal_overlap_ratio(left, right) >= 0.45


def _candidate_score(target: CanonicalBlock, candidate: CanonicalBlock) -> float:
    distance_score = 0.6 * min(abs(target.reading_order - candidate.reading_order) / 10.0, 1.0)
    distance_score += 0.4 * _normalized_center_distance(target, candidate)
    same_zone_bonus = -0.3 if _primary_zone(target) == _primary_zone(candidate) else 0.0
    return distance_score + same_zone_bonus


def _is_text_candidate(block: CanonicalBlock) -> bool:
    return block.canonical_label in TEXTUAL_LABELS and bool(clean_text(block.text))


def _is_heading_candidate(block: CanonicalBlock) -> bool:
    return block.canonical_label in HEADING_LABELS and bool(clean_text(block.text))


def _is_evidence_candidate(block: CanonicalBlock) -> bool:
    return block.canonical_label in EVIDENCE_LABELS


def _ocr_label_payload(block: CanonicalBlock) -> Dict[str, Any]:
    engine_raw_labels = dict(block.semantic_hints.get("engine_raw_labels", {}))
    if not engine_raw_labels:
        engine_raw_labels["paddle"] = block.raw_label
    return {
        "primary_raw_label": block.semantic_hints.get("primary_raw_label", block.raw_label),
        "current_raw_label": block.raw_label,
        "engine_raw_labels": engine_raw_labels,
        "secondary_raw_label": block.semantic_hints.get("secondary_raw_label"),
    }


def _neighbor_payload(target: CanonicalBlock, candidate: CanonicalBlock, relation: str) -> Dict[str, Any]:
    return {
        "relation": relation,
        "block_id": candidate.block_id,
        "canonical_label": candidate.canonical_label,
        "raw_label": candidate.raw_label,
        "text": clean_text(candidate.text),
        "bbox_norm": list(candidate.bbox_norm),
        "reading_order": candidate.reading_order,
        "zone_tags": _zone_tags_for_block(candidate),
        "ocr_labels": _ocr_label_payload(candidate),
        **_block_metrics(candidate),
    }


def _top_k(candidates: List[CanonicalBlock], target: CanonicalBlock, k: int) -> List[CanonicalBlock]:
    return sorted(
        candidates,
        key=lambda candidate: (_candidate_score(target, candidate), abs(target.reading_order - candidate.reading_order)),
    )[:k]


def _safe_distance(target: CanonicalBlock, candidate: CanonicalBlock) -> float:
    return round(_normalized_center_distance(target, candidate), 4)


def _safe_overlap(target: CanonicalBlock, candidate: CanonicalBlock) -> float:
    return round(_horizontal_overlap_ratio(target, candidate), 4)


def build_block_context(
    *,
    page: CanonicalPage,
    analysis: PageAnalysis,
    block: CanonicalBlock,
    config: SemanticConfig,
    document_family: str = "financial_report",
) -> BlockContextPayload:
    blocks = sorted(page.blocks, key=lambda current: (current.reading_order, current.bbox_px[1], current.bbox_px[0]))
    block_index_map = {current.block_id: index for index, current in enumerate(blocks)}
    zone_tags = _zone_tags_for_block(block)
    previous_text = _top_k(
        [candidate for candidate in blocks if candidate.reading_order < block.reading_order and _is_text_candidate(candidate)],
        block,
        2,
    )
    next_text = _top_k(
        [candidate for candidate in blocks if candidate.reading_order > block.reading_order and _is_text_candidate(candidate)],
        block,
        2,
    )
    nearest_heading = _top_k(
        [candidate for candidate in blocks if candidate.block_id != block.block_id and _is_heading_candidate(candidate)],
        block,
        1,
    )
    nearest_evidence = _top_k(
        [candidate for candidate in blocks if candidate.block_id != block.block_id and _is_evidence_candidate(candidate)],
        block,
        2,
    )

    seen_ids = set()
    local_neighbors: List[Dict[str, Any]] = []
    for relation, candidates in (
        ("previous_text", previous_text),
        ("next_text", next_text),
        ("nearest_heading", nearest_heading),
        ("nearest_evidence", nearest_evidence),
    ):
        for candidate in candidates:
            if candidate.block_id in seen_ids or candidate.block_id == block.block_id:
                continue
            local_neighbors.append(_neighbor_payload(block, candidate, relation))
            seen_ids.add(candidate.block_id)
            if len(local_neighbors) >= config.max_context_blocks:
                break
        if len(local_neighbors) >= config.max_context_blocks:
            break

    nearest_heading_block = nearest_heading[0] if nearest_heading else None
    nearest_evidence_block = nearest_evidence[0] if nearest_evidence else None
    previous_text_block = previous_text[0] if previous_text else None
    next_text_block = next_text[0] if next_text else None

    page_context = {
        "document_family": document_family,
        "page_archetype": analysis.page_archetype,
        "quality_score": analysis.quality_score,
        "column_count": analysis.column_count,
        "dominant_layout_pattern": analysis.dominant_layout_pattern,
        "left_sidebar_ratio": analysis.left_sidebar_ratio,
        "meta_area_ratio": analysis.meta_area_ratio,
        "text_area_ratio": analysis.text_area_ratio,
        "table_area_ratio": analysis.table_area_ratio,
        "visual_area_ratio": analysis.visual_area_ratio,
    }
    target_block = {
        "block_id": block.block_id,
        "text": clean_text(block.text),
        "canonical_label": block.canonical_label,
        "raw_label": block.raw_label,
        "bbox_norm": list(block.bbox_norm),
        "reading_order": block.reading_order,
        "text_quality_score": block.text_quality_score,
        "engine_sources": ["paddle"],
        "tags": list(block.tags),
        "flags": list(block.flags),
        "zone_tags": zone_tags,
        "primary_zone": zone_tags[0],
        "ocr_labels": _ocr_label_payload(block),
        "block_index_on_page": block_index_map[block.block_id],
        "total_blocks_on_page": len(blocks),
        **_block_metrics(block),
    }
    structural_relations = {
        "distance_to_nearest_heading": _safe_distance(block, nearest_heading_block) if nearest_heading_block else None,
        "distance_to_nearest_evidence": _safe_distance(block, nearest_evidence_block) if nearest_evidence_block else None,
        "same_column_as_nearest_heading": _same_column(block, nearest_heading_block) if nearest_heading_block else None,
        "same_column_as_previous_text": _same_column(block, previous_text_block) if previous_text_block else None,
        "same_column_as_next_text": _same_column(block, next_text_block) if next_text_block else None,
        "overlap_ratio_with_nearest_heading": _safe_overlap(block, nearest_heading_block) if nearest_heading_block else None,
        "overlap_ratio_with_nearest_evidence": _safe_overlap(block, nearest_evidence_block) if nearest_evidence_block else None,
        "relative_order_from_nearest_heading": (
            block.reading_order - nearest_heading_block.reading_order if nearest_heading_block else None
        ),
    }
    return BlockContextPayload(
        block_id=block.block_id,
        page=page.page,
        document_family=document_family,
        page_archetype=analysis.page_archetype,
        page_quality_score=analysis.quality_score,
        target_block=target_block,
        page_context=page_context,
        local_neighbors=local_neighbors,
        structural_relations=structural_relations,
        allowed_roles={
            "generic_role": list(GENERIC_ROLES),
            "domain_role": list(DOMAIN_ROLES),
        },
    )
