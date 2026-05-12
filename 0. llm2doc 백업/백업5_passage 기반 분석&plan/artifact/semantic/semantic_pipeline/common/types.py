from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RawEngineBlock:
    engine: str
    page: int
    raw_label: str
    text: str
    bbox_px: List[int]
    bbox_norm: List[float]
    reading_order: Optional[int]
    polygon: List[List[float]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    raw_confidence: Optional[float] = None


@dataclass
class CanonicalBlock:
    block_id: str
    page: int
    source_sample_id: str
    raw_label: str
    canonical_label: str
    text: str
    text_source: str
    bbox_px: List[int]
    bbox_norm: List[float]
    reading_order: int
    text_quality_score: float
    semantic_hints: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)
    generic_role: Optional[str] = None
    domain_role: Optional[str] = None
    role_confidence: Optional[float] = None
    section_id: Optional[str] = None
    section_purpose: Optional[str] = None
    used_for_generation: Optional[bool] = None
    semantic_source: Optional[str] = None
    semantic_reason: Optional[str] = None
    semantic_needs_review: Optional[bool] = None
    semantic_backend: Optional[str] = None
    semantic_model_name: Optional[str] = None
    semantic_prompt_version: Optional[str] = None
    semantic_fallback_reason: Optional[str] = None
    generated_role_name: Optional[str] = None
    generated_role_description: Optional[str] = None
    generated_parent_role_name: Optional[str] = None
    generated_role_level: Optional[str] = None
    passage_id: Optional[str] = None
    content_status: Optional[str] = None
    non_content_hints: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class EnginePage:
    engine: str
    page: int
    sample_id: str
    width: int
    height: int
    raw_blocks: List[RawEngineBlock]
    source_paths: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalPage:
    page: int
    sample_id: str
    width: int
    height: int
    blocks: List[CanonicalBlock]
    source_engine: str = "paddle"
    diagnostics: Dict[str, Any] = field(default_factory=dict)


# Backward-compatible alias for older internal names.
FusedPage = CanonicalPage


@dataclass
class PageAnalysis:
    page: int
    page_archetype: str
    width: int
    height: int
    column_count: int
    content_bbox: List[int]
    table_area_ratio: float
    visual_area_ratio: float
    text_area_ratio: float
    quality_score: float
    warnings: List[str] = field(default_factory=list)
    left_sidebar_ratio: float = 0.0
    meta_area_ratio: float = 0.0
    dominant_layout_pattern: str = "single_column"
    has_large_visual: bool = False


@dataclass
class SectionOrderItem:
    section_id: str
    page: int
    title: str
    block_ids: List[str]
    purpose: Optional[str] = None


@dataclass
class ImageSlot:
    slot_id: str
    page: int
    block_id: str
    bbox_norm: List[float]
    alignment: str
    width_ratio: float
    height_ratio: float
    caption_expected: bool


@dataclass
class UnsupportedBlock:
    block_id: str
    page: int
    type: str
    reason: str


@dataclass
class PageSource:
    page_number: int
    sample_id: str
    source_type: str
    reference_doc_id: str
    document_dir: str
    image_path: Optional[str] = None


@dataclass
class DocumentProfile:
    language: str
    page_count: int
    block_count: int
    document_family: str


@dataclass
class SemanticPassage:
    passage_id: str
    page_span: List[int]
    block_ids: List[str]
    title: str
    summary: str
    main_function: str
    retrieval_text: str
    representative_block_id: str


@dataclass
class ExcludedBlock:
    block_id: str
    reason: str


@dataclass
class PassageTraceEntry:
    page: int
    mode: str
    input_payload: Dict[str, Any]
    raw_response: Optional[str]
    parsed_result: Optional[Dict[str, Any]]
    repaired_result: Dict[str, Any]
    fallback_reason: Optional[str] = None
    latency_ms: int = 0


@dataclass
class ReferenceTemplate:
    template_id: str
    source_path: str
    document_family: str
    language: str
    source_engines: List[str]
    page_specs: List[Dict[str, Any]]
    page_archetypes: List[Dict[str, Any]]
    anchor_pages: List[int]
    blocks: List[CanonicalBlock]
    section_order: List[SectionOrderItem]
    style_tokens: Dict[str, Any]
    image_slots: List[ImageSlot]
    unsupported_blocks: List[UnsupportedBlock]
    repeating_elements: List[Dict[str, Any]]
    template_warnings: List[str]
    confidence_summary: Dict[str, Any]
    unsupported_for_mvp: bool = False


def dataclass_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        result = {}
        for field_info in fields(value):
            field_value = getattr(value, field_info.name)
            if field_value is None:
                continue
            result[field_info.name] = dataclass_to_dict(field_value)
        return result
    if isinstance(value, list):
        return [dataclass_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: dataclass_to_dict(item) for key, item in value.items()}
    return value
