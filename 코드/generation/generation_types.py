from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


GenerationMode = Literal["rule", "qwen"]
RenderAs = Literal["plain", "title", "heading", "paragraph"]


@dataclass
class GenerationConfig:
    mode: GenerationMode = "rule"
    model_name: str = "Qwen/Qwen3.5-9B"
    runtime: Literal["transformers"] = "transformers"
    prompt_version: str = "reference-fill-v1"
    do_sample: bool = False
    temperature: float = 0.2
    max_new_tokens: int = 384
    max_facts_per_slot: int = 4
    min_fact_score: float = 1.5
    quality_threshold: float = 0.55
    device: str = "auto"


@dataclass
class ReferenceSlot:
    slot_id: str
    page: int
    order_index: int
    block_id: str
    generic_role: Optional[str]
    domain_role: Optional[str]
    generated_role_name: Optional[str]
    generated_role_description: Optional[str]
    reference_text: str
    render_as: RenderAs
    preserve_reference_text: bool = False
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    target_word_count: int = 0
    prompt_hint: Optional[str] = None


@dataclass
class SourceFact:
    fact_id: str
    kind: str
    page: int
    block_ids: List[str]
    text: str
    generic_role: Optional[str] = None
    domain_role: Optional[str] = None
    generated_role_name: Optional[str] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    used_for_generation: Optional[bool] = None
    quality_score: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SlotAssignment:
    slot_id: str
    strategy: str
    selected_fact_ids: List[str]
    rationale: str
    confidence: float
    preserve_reference_text: bool = False


@dataclass
class SlotWritePayload:
    slot_id: str
    document_family: str
    source_language: str
    slot: Dict[str, Any]
    selected_facts: List[Dict[str, Any]]
    style_tokens: Dict[str, Any]


@dataclass
class SlotDraft:
    slot_id: str
    text: str
    source_fact_ids: List[str]
    citations: List[str] = field(default_factory=list)
    rationale: Optional[str] = None
    needs_review: bool = False
    render_as: RenderAs = "paragraph"
    section_id: Optional[str] = None
    used_reference_text: bool = False


@dataclass
class GenerationTraceEntry:
    stage: str
    slot_id: str
    input_payload: Dict[str, Any]
    raw_response: Optional[str]
    parsed_payload: Optional[Dict[str, Any]]
    applied_payload: Dict[str, Any]
    fallback_reason: Optional[str]
    latency_ms: int


@dataclass
class GenerationRunSummary:
    mode: str
    backend: str
    model_name: Optional[str]
    prompt_version: Optional[str]
    slot_count: int
    generated_slot_count: int
    preserved_slot_count: int
    fallback_count: int
    needs_review_count: int
    trace: List[GenerationTraceEntry] = field(default_factory=list)
