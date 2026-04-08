import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .adapters import load_dolphin_page, load_paddle_page
from .archetypes import classify_page, detect_document_family, detect_language_from_pages
from .fusion import fuse_pages
from .ocr_locator import available_preview_paths, locate_reference_pages
from .semantic import apply_financial_semantic_overlay
from .semantic_types import SemanticConfig
from .template import (
    anchor_pages_from_analyses,
    build_image_slots,
    build_section_order,
    build_style_tokens,
    collect_unsupported_blocks,
    detect_repeating_elements,
    page_specs_from_analysis,
)
from .types import FusedPage, ReferenceTemplate, dataclass_to_dict
from .utils import ensure_dir, save_json, stable_hash


def _copy_if_exists(source: str, target: Path) -> None:
    if not source:
        return
    source_path = Path(source)
    if not source_path.exists():
        return
    ensure_dir(target.parent)
    shutil.copy2(str(source_path), str(target))


def _review_gate(
    document_family: str,
    pages: List[FusedPage],
    analyses,
    section_order,
    unsupported_blocks,
) -> Tuple[List[str], Dict[str, object], bool]:
    warnings: List[str] = []
    low_quality_pages = [analysis.page for analysis in analyses if analysis.quality_score < 0.55]
    if low_quality_pages:
        warnings.append("low_ocr_quality_pages:%s" % ",".join(str(page) for page in low_quality_pages))
    fusion_conflicts = sum(page.diagnostics.get("text_replacements", 0) for page in pages)
    if fusion_conflicts >= 5:
        warnings.append("low_ocr_quality_repaired_via_secondary_engine")
    if not section_order:
        warnings.append("no_narrative_sections_extracted")
    unsupported_for_mvp = document_family in {"form", "unknown"}
    if unsupported_for_mvp:
        warnings.append("unsupported_for_mvp")
    review_required = bool(low_quality_pages or unsupported_for_mvp or fusion_conflicts >= 5)
    confidence_summary = {
        "overall_score": round(sum(analysis.quality_score for analysis in analyses) / max(1, len(analyses)), 4),
        "review_required": review_required,
        "high_noise_pages": low_quality_pages,
        "fusion_conflicts": fusion_conflicts,
        "unsupported_page_count": len(
            [analysis for analysis in analyses if analysis.page_archetype in {"evidence_table", "compliance"}]
        ),
        "notes": warnings,
    }
    return warnings, confidence_summary, unsupported_for_mvp


def build_reference_template(
    job_id: str,
    reference_path: str,
    ocr_results_root: str = "OCR_results",
    semantic_config: Optional[SemanticConfig] = None,
) -> Tuple[ReferenceTemplate, Dict[str, object], List[Dict[str, object]]]:
    page_sources = locate_reference_pages(reference_path, ocr_results_root)
    fused_pages: List[FusedPage] = []
    for page_source in page_sources:
        dolphin_page = load_dolphin_page(page_source)
        paddle_page = load_paddle_page(page_source)
        fused_pages.append(
            fuse_pages(
                dolphin_page=dolphin_page,
                paddle_page=paddle_page,
                page_number=page_source.page_number,
                sample_id=page_source.sample_id,
            )
        )

    analyses = [classify_page(page) for page in fused_pages]
    document_family = detect_document_family(fused_pages, analyses)
    language = detect_language_from_pages(fused_pages)

    semantic_summary = None
    semantic_config = semantic_config or SemanticConfig()
    semantic_summary = apply_financial_semantic_overlay(
        fused_pages,
        analyses,
        config=semantic_config,
        document_family=document_family,
    )

    anchor_pages = anchor_pages_from_analyses(analyses)
    section_order = build_section_order(fused_pages, anchor_pages)
    style_tokens = build_style_tokens(fused_pages, anchor_pages, analyses)
    image_slots = build_image_slots(fused_pages, anchor_pages)
    unsupported_blocks = collect_unsupported_blocks(fused_pages)
    repeating_elements = detect_repeating_elements(fused_pages)
    template_warnings, confidence_summary, unsupported_for_mvp = _review_gate(
        document_family=document_family,
        pages=fused_pages,
        analyses=analyses,
        section_order=section_order,
        unsupported_blocks=unsupported_blocks,
    )

    source_engines = sorted({engine for page in fused_pages for engine in page.source_engines})
    template = ReferenceTemplate(
        template_id="%s-%s" % (job_id, stable_hash([job_id, str(Path(reference_path).resolve())])),
        source_path=str(Path(reference_path).resolve()),
        document_family=document_family,
        language=language,
        source_engines=source_engines,
        page_specs=page_specs_from_analysis(fused_pages, analyses),
        page_archetypes=[dataclass_to_dict(analysis) for analysis in analyses],
        anchor_pages=anchor_pages,
        blocks=[block for page in fused_pages for block in page.blocks],
        section_order=section_order,
        style_tokens=style_tokens,
        image_slots=image_slots,
        unsupported_blocks=unsupported_blocks,
        repeating_elements=repeating_elements,
        template_warnings=template_warnings,
        confidence_summary=confidence_summary,
        unsupported_for_mvp=unsupported_for_mvp,
    )

    diagnostics = {
        "reference_path": str(Path(reference_path).resolve()),
        "page_sources": [dataclass_to_dict(page_source) for page_source in page_sources],
        "page_analyses": [dataclass_to_dict(analysis) for analysis in analyses],
        "fusion": {page.sample_id: page.diagnostics for page in fused_pages},
        "document_family": document_family,
        "language": language,
    }
    if semantic_summary is not None:
        diagnostics["semantic"] = {
            key: value
            for key, value in dataclass_to_dict(semantic_summary).items()
            if key != "trace"
        }
        if semantic_summary.mode != "rule":
            diagnostics["semantic_trace"] = [dataclass_to_dict(entry) for entry in semantic_summary.trace]
    canonical_pages = []
    for page in fused_pages:
        canonical_pages.append(
            {
                "page": page.page,
                "sample_id": page.sample_id,
                "width": page.width,
                "height": page.height,
                "source_engines": page.source_engines,
                "diagnostics": page.diagnostics,
                "blocks": [dataclass_to_dict(block) for block in page.blocks],
            }
        )
    return template, diagnostics, canonical_pages


def parse_reference(
    job_id: str,
    reference_path: str,
    artifacts_root: str = "artifacts",
    ocr_results_root: str = "OCR_results",
    semantic_config: Optional[SemanticConfig] = None,
) -> Dict[str, str]:
    template, diagnostics, canonical_pages = build_reference_template(
        job_id=job_id,
        reference_path=reference_path,
        ocr_results_root=ocr_results_root,
        semantic_config=semantic_config,
    )
    artifact_dir = Path(artifacts_root) / job_id / "01_reference"
    raw_dolphin_dir = ensure_dir(artifact_dir / "raw" / "dolphin")
    raw_paddle_dir = ensure_dir(artifact_dir / "raw" / "paddle")
    preview_dir = ensure_dir(artifact_dir / "layout_preview")

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

    for page_source in locate_reference_pages(reference_path, ocr_results_root):
        if page_source.dolphin_json_path:
            _copy_if_exists(page_source.dolphin_json_path, raw_dolphin_dir / Path(page_source.dolphin_json_path).name)
        if page_source.dolphin_markdown_path:
            _copy_if_exists(page_source.dolphin_markdown_path, raw_dolphin_dir / Path(page_source.dolphin_markdown_path).name)
        if page_source.paddle_json_path:
            _copy_if_exists(page_source.paddle_json_path, raw_paddle_dir / ("%s.json" % page_source.sample_id))
        if page_source.paddle_markdown_path:
            _copy_if_exists(page_source.paddle_markdown_path, raw_paddle_dir / ("%s.md" % page_source.sample_id))
        for preview_name, preview_path in available_preview_paths(page_source).items():
            suffix = Path(preview_path).suffix
            _copy_if_exists(preview_path, preview_dir / ("%s_%s%s" % (page_source.sample_id, preview_name, suffix)))

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
