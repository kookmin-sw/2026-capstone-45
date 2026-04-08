from typing import Dict, List

from .types import CanonicalBlock, EnginePage
from .utils import clean_text, text_quality_score


DOLPHIN_LABEL_MAP: Dict[str, str] = {
    "sec_0": "document_title",
    "sec_1": "section_heading",
    "sec_2": "subheading",
    "para": "paragraph",
    "fig": "image",
    "tab": "table",
    "cap": "caption_or_panel_title",
    "header": "meta_candidate",
    "foot": "meta_candidate",
    "fnote": "meta_candidate",
    "list": "meta_candidate",
    "anno": "meta_candidate",
    "half_para": "paragraph",
}

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
    blocks: List[CanonicalBlock] = []
    for index, raw in enumerate(engine_page.raw_blocks):
        if engine_page.engine == "dolphin":
            canonical_label = DOLPHIN_LABEL_MAP.get(raw.raw_label, "unknown")
        else:
            canonical_label = PADDLE_LABEL_MAP.get(raw.raw_label, "unknown")
        reading_order = raw.reading_order if raw.reading_order is not None else index
        cleaned_text = clean_text(raw.text)
        semantic_hints = {
            "raw_engine": engine_page.engine,
            "raw_tags": list(raw.tags),
            "page_sample_id": engine_page.sample_id,
            "engine_raw_labels": {engine_page.engine: raw.raw_label},
            "primary_raw_label": raw.raw_label,
        }
        blocks.append(
            CanonicalBlock(
                block_id=f"{engine_page.engine}-{engine_page.sample_id}-{index}",
                page=engine_page.page,
                source_sample_id=engine_page.sample_id,
                raw_label=raw.raw_label,
                canonical_label=canonical_label,
                text=cleaned_text,
                text_source=engine_page.engine,
                engine_sources=[engine_page.engine],
                bbox_px=list(raw.bbox_px),
                bbox_norm=list(raw.bbox_norm),
                reading_order=int(reading_order),
                text_quality_score=text_quality_score(cleaned_text),
                semantic_hints=semantic_hints,
                tags=list(raw.tags),
            )
        )
    return blocks
