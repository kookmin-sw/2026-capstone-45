from typing import List, Sequence

from ..common.types import CanonicalBlock, CanonicalPage, PageAnalysis
from ..common.utils import EMAIL_RE, TICKER_RE, area_ratio, count_columns, detect_language, has_financial_signal, median_or_default, union_bbox


TEXT_LIKE_LABELS = {
    "document_title",
    "section_heading",
    "subheading",
    "paragraph",
    "paragraph_or_meta",
    "section_heading_or_panel_title",
    "caption_or_panel_title",
}

META_RAW_LABELS = {"header", "foot", "fnote", "list", "anno", "vision_footnote"}


def _is_meta_candidate(block: CanonicalBlock) -> bool:
    return block.canonical_label in {"meta_candidate", "footnote"} or block.raw_label in META_RAW_LABELS


def _textual_quality_blocks(blocks: Sequence[CanonicalBlock]) -> List[CanonicalBlock]:
    return [block for block in blocks if block.canonical_label in TEXT_LIKE_LABELS and block.text]


def classify_page(page: CanonicalPage) -> PageAnalysis:
    page_area = max(1, page.width * page.height)
    blocks = page.blocks
    content_blocks = [block for block in blocks if not _is_meta_candidate(block)]
    content_bbox = union_bbox([block.bbox_px for block in content_blocks]) if content_blocks else [0, 0, page.width, page.height]
    table_blocks = [block for block in blocks if block.canonical_label == "table"]
    chart_blocks = [block for block in blocks if block.canonical_label == "chart"]
    image_blocks = [block for block in blocks if block.canonical_label in {"image", "chart"}]
    text_blocks = [block for block in blocks if block.canonical_label in TEXT_LIKE_LABELS]
    substantial_text_blocks = [block for block in _textual_quality_blocks(text_blocks) if len(block.text) >= 20]

    table_area_ratio = round(sum(area_ratio(block.bbox_px, page.width, page.height) for block in table_blocks + chart_blocks), 4)
    visual_area_ratio = round(sum(area_ratio(block.bbox_px, page.width, page.height) for block in image_blocks), 4)
    text_area_ratio = round(sum(area_ratio(block.bbox_px, page.width, page.height) for block in substantial_text_blocks), 4)
    left_sidebar_ratio = round(
        sum(area_ratio(block.bbox_px, page.width, page.height) for block in blocks if block.bbox_norm[2] <= 0.35),
        4,
    )
    meta_area_ratio = round(
        sum(area_ratio(block.bbox_px, page.width, page.height) for block in blocks if _is_meta_candidate(block)),
        4,
    )
    column_positions = [block.bbox_px[0] for block in substantial_text_blocks or text_blocks]
    column_count = count_columns(column_positions, page.width)
    quality_score = round(
        median_or_default([block.text_quality_score for block in substantial_text_blocks], 0.75),
        4,
    )

    all_text = "\n".join(block.text for block in blocks if block.text)
    lower_text = all_text.lower()
    compliance_keywords = [
        "compliance notice",
        "투자판단",
        "중요 내용",
        "중요내용",
        "유동성공급자",
        "면책",
        "notice",
    ]
    has_compliance_keyword = any(keyword in lower_text for keyword in compliance_keywords)
    has_structured_list = any(block.raw_label in {"list", "fnote", "vision_footnote"} for block in blocks)
    financial_signal_count = sum(1 for block in blocks if has_financial_signal(block.text))
    left_panel_present = any(
        block.bbox_norm[2] <= 0.35 and area_ratio(block.bbox_px, page.width, page.height) >= 0.015
        for block in blocks
        if block.canonical_label in TEXT_LIKE_LABELS.union({"table", "chart", "image"})
    )
    main_body_present = any(
        block.bbox_norm[0] >= 0.32 and len(block.text) >= 40
        for block in substantial_text_blocks
    )
    bottom_compliance_block = any(
        block.bbox_norm[1] >= 0.6 and (
            block.raw_label in {"list", "fnote", "vision_footnote"}
            or any(keyword in block.text.lower() for keyword in compliance_keywords)
        )
        for block in blocks
        if block.text
    )
    image_count = sum(1 for block in blocks if block.canonical_label == "image")

    archetype = "unknown"
    if bottom_compliance_block and (has_compliance_keyword or has_structured_list):
        archetype = "compliance"
    elif financial_signal_count >= 2 and left_panel_present and main_body_present:
        archetype = "cover_summary"
    elif len(table_blocks) >= 3 and text_area_ratio < 0.12 and not main_body_present:
        archetype = "evidence_table"
    elif table_area_ratio >= 0.45 or (len(table_blocks) >= 2 and text_area_ratio < 0.08 and visual_area_ratio < 0.1):
        archetype = "evidence_table"
    elif text_area_ratio >= 0.12 and table_area_ratio < 0.35:
        archetype = "body_narrative"
    elif image_count >= 3 and len(text_blocks) >= 2:
        archetype = "body_narrative"

    warnings = []
    if quality_score < 0.55:
        warnings.append("low_ocr_quality")
    if not substantial_text_blocks:
        warnings.append("sparse_text")
    if column_count >= 3:
        dominant_layout_pattern = "multi_column"
    elif column_count == 2:
        dominant_layout_pattern = "two_column"
    elif visual_area_ratio >= 0.18:
        dominant_layout_pattern = "visual_heavy"
    else:
        dominant_layout_pattern = "single_column"

    return PageAnalysis(
        page=page.page,
        page_archetype=archetype,
        width=page.width,
        height=page.height,
        column_count=column_count,
        content_bbox=content_bbox,
        table_area_ratio=table_area_ratio,
        visual_area_ratio=visual_area_ratio,
        text_area_ratio=text_area_ratio,
        quality_score=quality_score,
        warnings=warnings,
        left_sidebar_ratio=left_sidebar_ratio,
        meta_area_ratio=meta_area_ratio,
        dominant_layout_pattern=dominant_layout_pattern,
        has_large_visual=visual_area_ratio >= 0.18,
    )


def detect_document_family(pages: Sequence[CanonicalPage], analyses: Sequence[PageAnalysis]) -> str:
    candidate_pages = list(pages[:2]) if len(pages) >= 2 else list(pages)
    joined_text = "\n".join(block.text for page in candidate_pages for block in page.blocks if block.text)
    financial_hits = 0
    for page in candidate_pages:
        for block in page.blocks:
            if has_financial_signal(block.text):
                financial_hits += 1
    if financial_hits >= 2 or (TICKER_RE.search(joined_text) and ("목표주가" in joined_text or "buy" in joined_text.lower())):
        return "financial_report"

    total_tables = sum(1 for page in pages for block in page.blocks if block.canonical_label == "table")
    total_text_blocks = sum(1 for page in pages for block in page.blocks if block.text and block.canonical_label in TEXT_LIKE_LABELS)
    if total_tables >= 1 and total_text_blocks <= 1:
        return "form"

    if any(analysis.page_archetype in {"cover_summary", "body_narrative"} for analysis in analyses):
        return "article"
    total_images = sum(1 for page in pages for block in page.blocks if block.canonical_label == "image")
    if total_images >= 3 and total_text_blocks >= 1:
        return "article"
    return "report"


def detect_language_from_pages(pages: Sequence[CanonicalPage]) -> str:
    texts = [block.text for page in pages for block in page.blocks if block.text]
    return detect_language(texts)
