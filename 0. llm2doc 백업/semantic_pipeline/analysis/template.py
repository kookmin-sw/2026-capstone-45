from collections import Counter
from statistics import median
from typing import Dict, List, Sequence, Tuple

from .archetypes import TEXT_LIKE_LABELS
from ..common.types import CanonicalBlock, CanonicalPage, ImageSlot, PageAnalysis, SectionOrderItem, UnsupportedBlock
from ..common.utils import area_ratio, infer_alignment, median_or_default, relative_gap


def page_specs_from_analysis(pages: Sequence[CanonicalPage], analyses: Sequence[PageAnalysis]) -> List[Dict[str, object]]:
    analysis_map = {analysis.page: analysis for analysis in analyses}
    specs = []
    for page in pages:
        analysis = analysis_map[page.page]
        x1, y1, x2, y2 = analysis.content_bbox
        specs.append(
            {
                "page": page.page,
                "width": page.width,
                "height": page.height,
                "column_count": analysis.column_count,
                "margin_top": y1,
                "margin_right": max(0, page.width - x2),
                "margin_bottom": max(0, page.height - y2),
                "margin_left": x1,
                "content_bbox": analysis.content_bbox,
                "has_large_visual": analysis.has_large_visual,
                "dominant_layout_pattern": analysis.dominant_layout_pattern,
            }
        )
    return specs


def anchor_pages_from_analyses(analyses: Sequence[PageAnalysis]) -> List[int]:
    return [analysis.page for analysis in analyses if analysis.page_archetype in {"cover_summary", "body_narrative"}]


def _narrative_blocks(page: CanonicalPage) -> List[CanonicalBlock]:
    blocks = []
    for block in page.blocks:
        if not block.text:
            continue
        if block.canonical_label not in TEXT_LIKE_LABELS and block.generic_role not in {"main_title", "section_heading", "body"}:
            continue
        if block.generic_role in {"metadata", "author_info", "disclaimer", "evidence", "visual"}:
            continue
        if block.raw_label in {"header", "foot", "fnote", "anno", "list"}:
            continue
        blocks.append(block)
    return blocks


def build_section_order(pages: Sequence[CanonicalPage], anchor_pages: Sequence[int]) -> List[SectionOrderItem]:
    sections: List[SectionOrderItem] = []
    section_index = 0
    anchor_set = set(anchor_pages)

    for page in pages:
        if page.page not in anchor_set:
            continue
        current: SectionOrderItem = None
        narrative_blocks = _narrative_blocks(page)
        previous_block = None

        for block in narrative_blocks:
            text = block.text.strip()
            if not text:
                continue
            is_titleish = False
            if block.domain_role in {"report_title", "thesis_heading"} or block.canonical_label in {
                "document_title",
                "section_heading",
                "subheading",
            }:
                is_titleish = True
            elif len(text) <= 80 and (previous_block is None or relative_gap(previous_block.bbox_px, block.bbox_px, page.height) >= 0.03):
                is_titleish = True

            if is_titleish:
                section_index += 1
                current = SectionOrderItem(
                    section_id="section-%03d" % section_index,
                    page=page.page,
                    title=text.splitlines()[0][:160],
                    block_ids=[block.block_id],
                    purpose=block.section_purpose,
                )
                sections.append(current)
            else:
                if current is None:
                    section_index += 1
                    current = SectionOrderItem(
                        section_id="section-%03d" % section_index,
                        page=page.page,
                        title=text.splitlines()[0][:80],
                        block_ids=[],
                        purpose=block.section_purpose,
                    )
                    sections.append(current)
                current.block_ids.append(block.block_id)
            previous_block = block
    return sections


def build_style_tokens(pages: Sequence[CanonicalPage], anchor_pages: Sequence[int], analyses: Sequence[PageAnalysis]) -> Dict[str, object]:
    anchor_set = set(anchor_pages)
    title_heights = []
    subtitle_heights = []
    body_heights = []
    paragraph_gaps = []
    section_gaps = []
    body_widths = []
    image_alignments = []
    previous_body = None
    previous_heading = None

    for page in pages:
        if page.page not in anchor_set:
            continue
        for block in page.blocks:
            height_ratio = max(0.0, block.bbox_norm[3] - block.bbox_norm[1])
            width_ratio = max(0.0, block.bbox_norm[2] - block.bbox_norm[0])
            if block.domain_role == "report_title" or block.canonical_label == "document_title":
                title_heights.append(height_ratio)
                previous_heading = block
            elif block.domain_role == "thesis_heading" or block.canonical_label in {"section_heading", "subheading"}:
                subtitle_heights.append(height_ratio)
                if previous_heading:
                    section_gaps.append(relative_gap(previous_heading.bbox_px, block.bbox_px, page.height))
                previous_heading = block
            elif block.canonical_label in {"paragraph", "paragraph_or_meta"} and len(block.text) >= 20:
                body_heights.append(height_ratio)
                body_widths.append(width_ratio)
                if previous_body:
                    paragraph_gaps.append(relative_gap(previous_body.bbox_px, block.bbox_px, page.height))
                previous_body = block
            if block.canonical_label == "image":
                image_alignments.append(infer_alignment(block.bbox_norm))

    analysis_column_count = median_or_default([analysis.column_count for analysis in analyses if analysis.page in anchor_set], 1.0)
    default_alignment = Counter(image_alignments).most_common(1)[0][0] if image_alignments else "center"
    body_scale = median_or_default(body_heights, 0.028)
    title_scale = median_or_default(title_heights, body_scale * 1.8) / max(body_scale, 0.001)
    subtitle_scale = median_or_default(subtitle_heights, body_scale * 1.3) / max(body_scale, 0.001)
    return {
        "title_font_scale": round(title_scale, 4),
        "subtitle_font_scale": round(subtitle_scale, 4),
        "body_font_scale": round(body_scale, 4),
        "line_height_ratio": 1.45,
        "paragraph_spacing": round(median_or_default(paragraph_gaps, 0.018), 4),
        "section_spacing": round(median_or_default(section_gaps, 0.03), 4),
        "column_count": int(round(analysis_column_count)),
        "body_width_ratio": round(median_or_default(body_widths, 0.52), 4),
        "image_alignment_rules": {
            "default_alignment": default_alignment,
            "observed_alignments": sorted(set(image_alignments)) or [default_alignment],
        },
    }


def build_image_slots(pages: Sequence[CanonicalPage], anchor_pages: Sequence[int]) -> List[ImageSlot]:
    anchor_set = set(anchor_pages)
    slots: List[ImageSlot] = []
    for page in pages:
        if page.page not in anchor_set:
            continue
        for block in page.blocks:
            if block.canonical_label != "image":
                continue
            ratio = area_ratio(block.bbox_px, page.width, page.height)
            if ratio < 0.03:
                continue
            slots.append(
                ImageSlot(
                    slot_id="image-slot-%s" % block.block_id,
                    page=page.page,
                    block_id=block.block_id,
                    bbox_norm=block.bbox_norm,
                    alignment=infer_alignment(block.bbox_norm),
                    width_ratio=round(block.bbox_norm[2] - block.bbox_norm[0], 4),
                    height_ratio=round(block.bbox_norm[3] - block.bbox_norm[1], 4),
                    caption_expected=False,
                )
            )
    return slots


def collect_unsupported_blocks(pages: Sequence[CanonicalPage]) -> List[UnsupportedBlock]:
    unsupported: List[UnsupportedBlock] = []
    for page in pages:
        for block in page.blocks:
            if block.canonical_label in {"table", "chart"}:
                unsupported.append(
                    UnsupportedBlock(
                        block_id=block.block_id,
                        page=page.page,
                        type=block.canonical_label,
                        reason="unsupported_for_generation",
                    )
                )
            elif block.generic_role == "disclaimer":
                unsupported.append(
                    UnsupportedBlock(
                        block_id=block.block_id,
                        page=page.page,
                        type="disclaimer",
                        reason="reference_only_non_body_content",
                    )
                )
    return unsupported


def detect_repeating_elements(pages: Sequence[CanonicalPage]) -> List[Dict[str, object]]:
    if len(pages) <= 1:
        return []
    counts = Counter()
    examples = {}
    for page in pages:
        for block in page.blocks:
            if block.raw_label not in {"header", "foot"}:
                continue
            text = block.text.strip()
            if not text:
                continue
            key = text.lower()
            counts[key] += 1
            examples[key] = {
                "text": text,
                "raw_label": block.raw_label,
                "bbox_norm": block.bbox_norm,
            }
    return [value for key, value in examples.items() if counts[key] >= 2]
