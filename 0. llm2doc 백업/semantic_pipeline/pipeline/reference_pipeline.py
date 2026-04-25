from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..analysis.archetypes import classify_page, detect_document_family, detect_language_from_pages
from ..analysis.template import (
    anchor_pages_from_analyses,
    build_image_slots,
    build_section_order,
    build_style_tokens,
    collect_unsupported_blocks,
    detect_repeating_elements,
    page_specs_from_analysis,
)
from ..common.types import CanonicalPage, ReferenceTemplate, dataclass_to_dict
from ..common.utils import ensure_dir, save_json, stable_hash
from ..parsing.canonicalize import build_canonical_page
from ..parsing.llm2doc_adapter import (
    build_llm2doc_page_sources,
    load_llm2doc_pages,
    resolve_llm2doc_reference_path,
    save_llm2doc_artifacts,
)
from ..semantic.semantic import apply_financial_semantic_overlay
from ..semantic.semantic_types import SemanticConfig


def load_llm2doc_paddle_pages(reference_path: str, llm2doc_root: str) -> Tuple[List[CanonicalPage], Dict[str, Any]]:
    paddle_pages = load_llm2doc_pages(reference_path, llm2doc_root)
    canonical_pages = [build_canonical_page(page) for page in paddle_pages]
    source_bundle: Dict[str, Any] = {
        "ocr_source": "llm2doc",
        "resolved_reference_path": str(
            resolve_llm2doc_reference_path(reference_path, llm2doc_root).resolve()
        ),
        "page_sources": build_llm2doc_page_sources(reference_path, llm2doc_root, paddle_pages),
        "llm2doc_pages": paddle_pages,
    }
    return canonical_pages, source_bundle


def _review_gate(
    document_family: str,
    pages: List[CanonicalPage],
    analyses,
    section_order,
) -> Tuple[List[str], Dict[str, object], bool]:
    warnings: List[str] = []
    low_quality_pages = [analysis.page for analysis in analyses if analysis.quality_score < 0.55]
    if low_quality_pages:
        warnings.append("low_ocr_quality_pages:%s" % ",".join(str(page) for page in low_quality_pages))
    if not section_order:
        warnings.append("no_narrative_sections_extracted")
    unsupported_for_mvp = document_family in {"form", "unknown"}
    if unsupported_for_mvp:
        warnings.append("unsupported_for_mvp")
    review_required = bool(low_quality_pages or unsupported_for_mvp)
    confidence_summary = {
        "overall_score": round(sum(analysis.quality_score for analysis in analyses) / max(1, len(analyses)), 4),
        "review_required": review_required,
        "high_noise_pages": low_quality_pages,
        "unsupported_page_count": len(
            [analysis for analysis in analyses if analysis.page_archetype in {"evidence_table", "compliance"}]
        ),
        "notes": warnings,
    }
    return warnings, confidence_summary, unsupported_for_mvp


def build_reference_outputs(
    *,
    job_id: str,
    canonical_pages: List[CanonicalPage],
    source_bundle: Dict[str, Any],
    semantic_config: Optional[SemanticConfig] = None,
) -> Tuple[ReferenceTemplate, Dict[str, object], List[Dict[str, object]]]:
    analyses = [classify_page(page) for page in canonical_pages]
    document_family = detect_document_family(canonical_pages, analyses)
    language = detect_language_from_pages(canonical_pages)

    semantic_summary = apply_financial_semantic_overlay(
        canonical_pages,
        analyses,
        config=semantic_config or SemanticConfig(),
        document_family=document_family,
    )

    anchor_pages = anchor_pages_from_analyses(analyses)
    section_order = build_section_order(canonical_pages, anchor_pages)
    style_tokens = build_style_tokens(canonical_pages, anchor_pages, analyses)
    image_slots = build_image_slots(canonical_pages, anchor_pages)
    unsupported_blocks = collect_unsupported_blocks(canonical_pages)
    repeating_elements = detect_repeating_elements(canonical_pages)
    template_warnings, confidence_summary, unsupported_for_mvp = _review_gate(
        document_family=document_family,
        pages=canonical_pages,
        analyses=analyses,
        section_order=section_order,
    )

    template = ReferenceTemplate(
        template_id="%s-%s" % (job_id, stable_hash([job_id, source_bundle["resolved_reference_path"]])),
        source_path=source_bundle["resolved_reference_path"],
        document_family=document_family,
        language=language,
        source_engines=["paddle"],
        page_specs=page_specs_from_analysis(canonical_pages, analyses),
        page_archetypes=[dataclass_to_dict(analysis) for analysis in analyses],
        anchor_pages=anchor_pages,
        blocks=[block for page in canonical_pages for block in page.blocks],
        section_order=section_order,
        style_tokens=style_tokens,
        image_slots=image_slots,
        unsupported_blocks=unsupported_blocks,
        repeating_elements=repeating_elements,
        template_warnings=template_warnings,
        confidence_summary=confidence_summary,
        unsupported_for_mvp=unsupported_for_mvp,
    )

    diagnostics: Dict[str, object] = {
        "reference_path": source_bundle["resolved_reference_path"],
        "ocr_source": "llm2doc",
        "page_sources": [dataclass_to_dict(page_source) for page_source in source_bundle["page_sources"]],
        "page_analyses": [dataclass_to_dict(analysis) for analysis in analyses],
        "document_family": document_family,
        "language": language,
        "ingest": {
            "source_engine": "paddle",
            "page_count": len(canonical_pages),
            "block_count": sum(len(page.blocks) for page in canonical_pages),
        },
    }
    diagnostics["semantic"] = {
        key: value
        for key, value in dataclass_to_dict(semantic_summary).items()
        if key != "trace"
    }
    if semantic_summary.trace:
        diagnostics["semantic_trace"] = [dataclass_to_dict(entry) for entry in semantic_summary.trace]

    canonical_payload = [
        {
            "page": page.page,
            "sample_id": page.sample_id,
            "width": page.width,
            "height": page.height,
            "source_engine": page.source_engine,
            "diagnostics": page.diagnostics,
            "blocks": [dataclass_to_dict(block) for block in page.blocks],
        }
        for page in canonical_pages
    ]
    return template, diagnostics, canonical_payload


def build_reference_template(
    job_id: str,
    reference_path: str,
    semantic_config: Optional[SemanticConfig] = None,
    llm2doc_root: Optional[str] = None,
) -> Tuple[ReferenceTemplate, Dict[str, object], List[Dict[str, object]], Dict[str, Any]]:
    if not llm2doc_root:
        raise ValueError("llm2doc_root is required for semantic_pipeline")

    canonical_pages, source_bundle = load_llm2doc_paddle_pages(reference_path, llm2doc_root)
    template, diagnostics, canonical_payload = build_reference_outputs(
        job_id=job_id,
        canonical_pages=canonical_pages,
        source_bundle=source_bundle,
        semantic_config=semantic_config,
    )
    return template, diagnostics, canonical_payload, source_bundle


def save_reference_artifacts(
    *,
    artifact_dir: Path,
    template: ReferenceTemplate,
    diagnostics: Dict[str, object],
    canonical_pages: List[Dict[str, object]],
    source_bundle: Dict[str, Any],
) -> Dict[str, str]:
    ensure_dir(artifact_dir)
    template_path = artifact_dir / "reference_template.json"
    canonical_pages_path = artifact_dir / "canonical_pages.json"
    semantic_overlay_path = artifact_dir / "semantic_overlay.json"
    diagnostics_path = artifact_dir / "parser_diagnostics.json"
    semantic_trace_path = artifact_dir / "semantic_trace.json"

    save_json(template_path, dataclass_to_dict(template))
    save_json(canonical_pages_path, canonical_pages)
    save_json(
        semantic_overlay_path,
        [
            {
                "block_id": block["block_id"],
                "page": block["page"],
                "generic_role": block.get("generic_role"),
                "domain_role": block.get("domain_role"),
                "role_confidence": block.get("role_confidence"),
                "generated_role_name": block.get("generated_role_name"),
                "generated_role_description": block.get("generated_role_description"),
                "generated_parent_role_name": block.get("generated_parent_role_name"),
                "generated_role_level": block.get("generated_role_level"),
                "section_id": block.get("section_id"),
                "section_purpose": block.get("section_purpose"),
                "used_for_generation": block.get("used_for_generation"),
                "semantic_source": block.get("semantic_source"),
                "semantic_reason": block.get("semantic_reason"),
                "semantic_needs_review": block.get("semantic_needs_review"),
                "semantic_fallback_reason": block.get("semantic_fallback_reason"),
            }
            for page in canonical_pages
            for block in page["blocks"]
            if block.get("generic_role") or block.get("domain_role") or block.get("generated_role_name")
        ],
    )
    semantic_trace = diagnostics.pop("semantic_trace", None)
    save_json(diagnostics_path, diagnostics)
    if semantic_trace is not None:
        save_json(semantic_trace_path, semantic_trace)

    save_llm2doc_artifacts(source_bundle["llm2doc_pages"], artifact_dir)

    result = {
        "reference_template": str(template_path),
        "canonical_pages": str(canonical_pages_path),
        "semantic_overlay": str(semantic_overlay_path),
        "diagnostics": str(diagnostics_path),
        "artifact_dir": str(artifact_dir),
    }
    if semantic_trace is not None:
        result["semantic_trace"] = str(semantic_trace_path)
    return result


def parse_reference(
    job_id: str,
    reference_path: str,
    artifacts_root: str = "artifacts",
    semantic_config: Optional[SemanticConfig] = None,
    llm2doc_root: Optional[str] = None,
) -> Dict[str, str]:
    template, diagnostics, canonical_pages, source_bundle = build_reference_template(
        job_id=job_id,
        reference_path=reference_path,
        semantic_config=semantic_config,
        llm2doc_root=llm2doc_root,
    )
    artifact_dir = Path(artifacts_root) / job_id / "01_reference"
    return save_reference_artifacts(
        artifact_dir=artifact_dir,
        template=template,
        diagnostics=diagnostics,
        canonical_pages=canonical_pages,
        source_bundle=source_bundle,
    )
