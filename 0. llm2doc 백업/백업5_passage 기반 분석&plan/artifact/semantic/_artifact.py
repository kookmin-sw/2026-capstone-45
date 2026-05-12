from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any, Literal


class SemanticHints(BaseModel):
    raw_engine: str
    raw_tags: List[str] = Field(default_factory=list)
    page_sample_id: str
    engine_raw_labels: Dict[str, str] = Field(default_factory=dict)
    primary_raw_label: str


class CanonicalBlock(BaseModel):
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
    semantic_hints: SemanticHints
    tags: List[str] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)
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
    non_content_hints: List[Dict[str, Any]] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class SectionOrderItem(BaseModel):
    section_id: str
    page: int
    title: str
    block_ids: List[str]
    purpose: Optional[str] = None


class ImageSlot(BaseModel):
    slot_id: str
    page: int
    block_id: str
    bbox_norm: List[float]
    alignment: str
    width_ratio: float
    height_ratio: float
    caption_expected: bool


class UnsupportedBlock(BaseModel):
    block_id: str
    page: int
    type: str
    reason: str


class PageSpec(BaseModel):
    page: int
    width: int
    height: int
    column_count: int
    margin_top: int
    margin_right: int
    margin_bottom: int
    margin_left: int
    content_bbox: List[int]
    has_large_visual: bool
    dominant_layout_pattern: str


class PageAnalysis(BaseModel):
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
    warnings: List[str] = Field(default_factory=list)
    left_sidebar_ratio: float = 0.0
    meta_area_ratio: float = 0.0
    dominant_layout_pattern: str = "single_column"
    has_large_visual: bool = False


class ImageAlignmentRules(BaseModel):
    default_alignment: str
    observed_alignments: List[str]


class StyleTokens(BaseModel):
    title_font_scale: float
    subtitle_font_scale: float
    body_font_scale: float
    line_height_ratio: float
    paragraph_spacing: float
    section_spacing: float
    column_count: int
    body_width_ratio: float
    image_alignment_rules: ImageAlignmentRules


class RepeatingElement(BaseModel):
    text: str
    raw_label: str
    bbox_norm: List[float]


class ConfidenceSummary(BaseModel):
    overall_score: float
    review_required: bool
    high_noise_pages: List[int]
    unsupported_page_count: int
    notes: List[str]


class ReferenceTemplate(BaseModel):
    template_id: str
    source_path: str
    document_family: str
    language: str
    source_engines: List[str]
    page_specs: List[PageSpec]
    page_archetypes: List[PageAnalysis]
    anchor_pages: List[int]
    blocks: List[CanonicalBlock]
    section_order: List[SectionOrderItem]
    style_tokens: StyleTokens
    image_slots: List[ImageSlot]
    unsupported_blocks: List[UnsupportedBlock]
    repeating_elements: List[RepeatingElement]
    template_warnings: List[str]
    confidence_summary: ConfidenceSummary
    unsupported_for_mvp: bool = False


class PageSource(BaseModel):
    page_number: int
    sample_id: str
    source_type: str
    reference_doc_id: str
    document_dir: str
    image_path: Optional[str] = None


class IngestDiagnostics(BaseModel):
    source_engine: str
    page_count: int
    block_count: int


class SemanticRunSummary(BaseModel):
    mode: str
    backend: str
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    page_count: int
    block_count: int
    attempted_count: int
    accepted_count: int
    fallback_count: int
    needs_review_count: int
    avg_role_confidence: float
    fallback_reasons: Dict[str, int]
    applied_source_counts: Dict[str, int]
    passage_count: int = 0
    excluded_block_count: int = 0


class RoleTraceEntry(BaseModel):
    block_id: str
    page: int
    mode: str
    input_payload: Dict[str, Any]
    raw_response: Optional[str] = None
    parsed_decision: Optional[Dict[str, Any]] = None
    applied_decision: Dict[str, Any]
    fallback_reason: Optional[str] = None
    latency_ms: int


class PassageTraceEntry(BaseModel):
    page: int
    mode: str
    input_payload: Dict[str, Any]
    raw_response: Optional[str] = None
    parsed_result: Optional[Dict[str, Any]] = None
    repaired_result: Dict[str, Any]
    fallback_reason: Optional[str] = None
    latency_ms: int = 0


class Diagnostics(BaseModel):
    reference_path: str
    ocr_source: str
    page_sources: List[PageSource]
    page_analyses: List[PageAnalysis]
    document_family: str
    language: str
    ingest: IngestDiagnostics
    semantic: SemanticRunSummary
    semantic_trace: Optional[List[RoleTraceEntry]] = None
    passage_trace: Optional[List[PassageTraceEntry]] = None


class CanonicalPageArtifact(BaseModel):
    page: int
    sample_id: str
    width: int
    height: int
    source_engine: str
    diagnostics: Dict[str, Any]
    blocks: List[CanonicalBlock]


class DocumentProfile(BaseModel):
    language: str
    page_count: int
    block_count: int
    document_family: str


class SemanticPassage(BaseModel):
    passage_id: str
    page_span: List[int]
    block_ids: List[str]
    title: str
    summary: str
    main_function: str
    retrieval_text: str
    representative_block_id: str


class ExcludedBlock(BaseModel):
    block_id: str
    reason: str


class SemanticArtifact(BaseModel):
    schema_version: Literal["semantic-passage-v1"]
    document_profile: DocumentProfile
    template: ReferenceTemplate
    diagnostics: Diagnostics
    canonical_pages: List[CanonicalPageArtifact]
    passages: List[SemanticPassage]
    excluded_blocks: List[ExcludedBlock]
