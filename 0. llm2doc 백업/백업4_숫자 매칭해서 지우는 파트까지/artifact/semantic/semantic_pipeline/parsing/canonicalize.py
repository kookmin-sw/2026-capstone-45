from typing import Dict, List

from ..common.types import CanonicalBlock, CanonicalPage, EnginePage
from ..common.utils import clean_text, text_quality_score


PADDLE_LABEL_MAP: Dict[str, str] = {
    "doc_title": "document_title",
    "paragraph_title": "section_heading_or_panel_title",
    "text": "paragraph_or_meta",
    "table": "table",
    "chart": "chart",
    "image": "image",
    "vision_footnote": "footnote",
}


def canonicalize_engine_page(engine_page: EnginePage) -> List[CanonicalBlock]:
    if engine_page.engine != "paddle":
        raise ValueError(f"unsupported engine for canonicalization: {engine_page.engine}")

    blocks: List[CanonicalBlock] = []
    for index, raw in enumerate(engine_page.raw_blocks):
        reading_order = raw.reading_order if raw.reading_order is not None else index
        cleaned_text = clean_text(raw.text)
        canonical_label = PADDLE_LABEL_MAP.get(raw.raw_label, "unknown")
        blocks.append(
            CanonicalBlock(
                block_id=f"paddle-{engine_page.sample_id}-{index}",
                page=engine_page.page,
                source_sample_id=engine_page.sample_id,
                raw_label=raw.raw_label,
                canonical_label=canonical_label,
                text=cleaned_text,
                text_source="paddle",
                bbox_px=list(raw.bbox_px),
                bbox_norm=list(raw.bbox_norm),
                reading_order=int(reading_order),
                text_quality_score=text_quality_score(cleaned_text),
                semantic_hints={
                    "raw_engine": "paddle",
                    "raw_tags": list(raw.tags),
                    "page_sample_id": engine_page.sample_id,
                    "engine_raw_labels": {"paddle": raw.raw_label},
                    "primary_raw_label": raw.raw_label,
                },
                tags=list(raw.tags),
            )
        )
    return blocks


def build_canonical_page(engine_page: EnginePage) -> CanonicalPage:
    blocks = canonicalize_engine_page(engine_page)
    blocks.sort(key=lambda block: (block.reading_order, block.bbox_px[1], block.bbox_px[0]))
    for order, block in enumerate(blocks):
        block.reading_order = order

    return CanonicalPage(
        page=engine_page.page,
        sample_id=engine_page.sample_id,
        width=engine_page.width,
        height=engine_page.height,
        blocks=blocks,
        source_engine="paddle",
        diagnostics={"block_count": len(blocks)},
    )
