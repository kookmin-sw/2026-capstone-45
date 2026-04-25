from .archetypes import classify_page, detect_document_family, detect_language_from_pages
from .template import (
    anchor_pages_from_analyses,
    build_image_slots,
    build_section_order,
    build_style_tokens,
    collect_unsupported_blocks,
    detect_repeating_elements,
    page_specs_from_analysis,
)

__all__ = [
    "classify_page",
    "detect_document_family",
    "detect_language_from_pages",
    "anchor_pages_from_analyses",
    "build_image_slots",
    "build_section_order",
    "build_style_tokens",
    "collect_unsupported_blocks",
    "detect_repeating_elements",
    "page_specs_from_analysis",
]
