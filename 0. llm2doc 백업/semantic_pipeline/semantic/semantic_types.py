from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


SemanticMode = Literal["qwen"]
GeneratedRoleLevel = Literal["document", "section", "block"]


@dataclass
class SemanticConfig:
    mode: SemanticMode = "qwen"
    model_name: str = "Qwen/Qwen3.5-9B"
    runtime: Literal["api"] = "api"
    prompt_version: str = "financial-report-v1-en"
    do_sample: bool = False
    temperature: float = 0.1
    max_new_tokens: int = 256
    quality_threshold: float = 0.55
    confidence_accept_threshold: float = 0.75
    confidence_generic_only_threshold: float = 0.55
    max_context_blocks: int = 6


@dataclass
class OpenRoleProposal:
    block_id: str
    role_name: str
    role_description: str
    parent_role_name: Optional[str]
    role_level: GeneratedRoleLevel
    role_confidence: float
    needs_review: bool = False
    reason: Optional[str] = None


@dataclass
class ConsolidatedRole:
    canonical_role_name: str
    canonical_description: str
    parent_role_name: Optional[str]
    member_role_names: List[str] = field(default_factory=list)


@dataclass
class RoleDecision:
    block_id: str
    generic_role: str
    domain_role: Optional[str]
    role_confidence: float
    section_purpose: Optional[str]
    used_for_generation: Optional[bool]
    reason: Optional[str] = None
    needs_review: bool = False
    generated_role_name: Optional[str] = None
    generated_role_description: Optional[str] = None
    generated_parent_role_name: Optional[str] = None
    generated_role_level: Optional[GeneratedRoleLevel] = None


@dataclass
class BlockContextPayload:
    block_id: str
    page: int
    document_family: str
    page_archetype: str
    page_quality_score: float
    target_block: Dict[str, Any]
    page_context: Dict[str, Any]
    local_neighbors: List[Dict[str, Any]]
    structural_relations: Dict[str, Any]
    allowed_roles: Dict[str, List[str]]


@dataclass
class RoleTraceEntry:
    block_id: str
    page: int
    mode: str
    input_payload: Dict[str, Any]
    raw_response: Optional[str]
    parsed_decision: Optional[Dict[str, Any]]
    applied_decision: Dict[str, Any]
    fallback_reason: Optional[str]
    latency_ms: int


@dataclass
class SemanticRunSummary:
    mode: str
    backend: str
    model_name: Optional[str]
    prompt_version: Optional[str]
    page_count: int
    block_count: int
    attempted_count: int
    accepted_count: int
    fallback_count: int
    needs_review_count: int
    avg_role_confidence: float
    fallback_reasons: Dict[str, int]
    applied_source_counts: Dict[str, int]
    trace: List[RoleTraceEntry] = field(default_factory=list)
