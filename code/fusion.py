from copy import deepcopy
from typing import List, Optional, Tuple

from .canonicalize import canonicalize_engine_page
from .types import CanonicalBlock, EnginePage, FusedPage
from .utils import bbox_iou, text_quality_score


def _sort_blocks(blocks: List[CanonicalBlock]) -> List[CanonicalBlock]:
    return sorted(blocks, key=lambda block: (block.reading_order, block.bbox_px[1], block.bbox_px[0]))


def _promote_label(primary: CanonicalBlock, secondary: CanonicalBlock) -> str:
    if secondary.canonical_label == "chart" and primary.canonical_label == "image":
        return "chart"
    if primary.canonical_label == "meta_candidate" and secondary.canonical_label not in {
        "paragraph_or_meta",
        "section_heading_or_panel_title",
        "footnote",
    }:
        return secondary.canonical_label
    if primary.canonical_label == "caption_or_panel_title" and secondary.canonical_label == "section_heading_or_panel_title":
        return "caption_or_panel_title"
    return primary.canonical_label


def _merge_block(primary: CanonicalBlock, secondary: CanonicalBlock) -> Tuple[CanonicalBlock, bool]:
    merged = deepcopy(primary)
    text_replaced = False
    if secondary.text:
        primary_quality = text_quality_score(primary.text)
        secondary_quality = text_quality_score(secondary.text)
        if not primary.text or secondary_quality > primary_quality:
            merged.text = secondary.text
            merged.text_source = secondary.text_source
            merged.text_quality_score = secondary_quality
            merged.flags.append("text_replaced_from_secondary")
            text_replaced = True
    promoted = _promote_label(primary, secondary)
    if promoted != primary.canonical_label:
        merged.canonical_label = promoted
        merged.flags.append("label_promoted_from_secondary")
    merged.engine_sources = sorted(set(primary.engine_sources + secondary.engine_sources))
    primary_labels = dict(primary.semantic_hints.get("engine_raw_labels", {}))
    secondary_labels = dict(secondary.semantic_hints.get("engine_raw_labels", {}))
    if not secondary_labels:
        for engine_name in secondary.engine_sources:
            secondary_labels[engine_name] = secondary.raw_label
    merged.semantic_hints["engine_raw_labels"] = {**primary_labels, **secondary_labels}
    merged.semantic_hints["primary_raw_label"] = primary.semantic_hints.get("primary_raw_label", primary.raw_label)
    merged.semantic_hints["secondary_match_id"] = secondary.block_id
    merged.semantic_hints["secondary_raw_label"] = secondary.raw_label
    merged.tags = sorted(set(primary.tags + secondary.tags))
    return merged, text_replaced


def fuse_pages(dolphin_page: Optional[EnginePage], paddle_page: Optional[EnginePage], page_number: int, sample_id: str) -> FusedPage:
    dolphin_blocks = canonicalize_engine_page(dolphin_page) if dolphin_page else []
    paddle_blocks = canonicalize_engine_page(paddle_page) if paddle_page else []

    if dolphin_page:
        primary_blocks = dolphin_blocks
        secondary_blocks = paddle_blocks
        width = dolphin_page.width
        height = dolphin_page.height
        source_engines = ["dolphin"] + (["paddle"] if paddle_page else [])
    elif paddle_page:
        primary_blocks = paddle_blocks
        secondary_blocks = []
        width = paddle_page.width
        height = paddle_page.height
        source_engines = ["paddle"]
    else:
        raise ValueError(f"Page {page_number} has no OCR sources to fuse.")

    fused_blocks: List[CanonicalBlock] = []
    used_secondary = set()
    text_replacements = 0

    for primary in primary_blocks:
        best_match = None
        best_iou = 0.0
        for secondary in secondary_blocks:
            if secondary.block_id in used_secondary:
                continue
            current_iou = bbox_iou(primary.bbox_px, secondary.bbox_px)
            if current_iou >= 0.5 and current_iou > best_iou:
                best_match = secondary
                best_iou = current_iou
        if best_match:
            merged, replaced = _merge_block(primary, best_match)
            merged.semantic_hints["match_iou"] = round(best_iou, 4)
            fused_blocks.append(merged)
            used_secondary.add(best_match.block_id)
            if replaced:
                text_replacements += 1
        else:
            fused_blocks.append(primary)

    added_secondary = []
    for secondary in secondary_blocks:
        if secondary.block_id in used_secondary:
            continue
        if secondary.canonical_label == "footnote" and secondary.text_quality_score < 0.2:
            continue
        secondary.flags.append("secondary_only")
        fused_blocks.append(secondary)
        added_secondary.append(secondary.block_id)

    fused_blocks = _sort_blocks(fused_blocks)
    for order, block in enumerate(fused_blocks):
        block.reading_order = order

    return FusedPage(
        page=page_number,
        sample_id=sample_id,
        width=width,
        height=height,
        blocks=fused_blocks,
        source_engines=source_engines,
        diagnostics={
            "matched_pairs": len(used_secondary),
            "text_replacements": text_replacements,
            "added_secondary_blocks": added_secondary,
        },
    )
