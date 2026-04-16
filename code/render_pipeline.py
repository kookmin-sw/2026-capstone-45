from pathlib import Path
from typing import Dict, List, Optional, Tuple
import sys

from PIL import Image

from .utils import ensure_dir, save_json


def _ensure_llm2doc_render_importable(llm2doc_root: str | Path):
    root = Path(llm2doc_root).resolve()
    package_dir = root / "llm2doc"
    if not package_dir.exists():
        raise FileNotFoundError(f"llm2doc package directory does not exist: {package_dir}")

    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    from llm2doc.render_image import erase_bounding_box, render_boxes

    return erase_bounding_box, render_boxes


def _read_json(path: Path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_reference_dir(path: str) -> Path:
    base = Path(path)
    if (base / "reference_template.json").exists():
        return base
    candidate = base / "01_reference"
    if (candidate / "reference_template.json").exists():
        return candidate
    raise FileNotFoundError(path)


def _resolve_generation_dir(path: str) -> Path:
    base = Path(path)
    if (base / "slot_drafts.json").exists():
        return base
    candidate = base / "02_generation"
    if (candidate / "slot_drafts.json").exists():
        return candidate
    raise FileNotFoundError(path)


def _resolve_output_dir(
    reference_dir: Path, generation_dir: Path, output_dir: Optional[str]
) -> Path:
    if output_dir:
        return Path(output_dir)

    generation_root = generation_dir.parent
    reference_root = reference_dir.parent
    if generation_root == reference_root:
        return generation_root / "04_render_images"
    return generation_root / "04_render_images"


def _fallback_preview_path(reference_dir: Path, sample_id: str) -> Optional[Path]:
    preview_dir = reference_dir / "layout_preview"
    candidates = [
        preview_dir / f"{sample_id}_paddle_visualization.png",
        preview_dir / f"{sample_id}_paddle_visualization.jpg",
        preview_dir / f"{sample_id}_surya_image.png",
        preview_dir / f"{sample_id}_dolphin_layout.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _reference_image_map_from_dir(reference_source: Path, page_count: int) -> Dict[int, Path]:
    if reference_source.is_file():
        return {1: reference_source}

    image_paths = [
        path
        for path in reference_source.iterdir()
        if path.is_file() and path.name.startswith("original")
    ]
    image_paths.sort(key=lambda path: path.name)
    return {
        page_number: image_path
        for page_number, image_path in enumerate(image_paths[:page_count], start=1)
    }


def _page_image_map(
    reference_dir: Path,
    canonical_pages: List[dict],
    diagnostics: dict,
    reference_source: Optional[str],
) -> Tuple[Dict[int, Path], List[str]]:
    page_sources = diagnostics.get("page_sources", [])
    image_map: Dict[int, Path] = {}
    notes: List[str] = []

    for entry in page_sources:
        image_path = entry.get("image_path")
        page_number = int(entry.get("page_number") or 0)
        if image_path and page_number > 0:
            path = Path(image_path)
            if path.exists():
                image_map[page_number] = path

    if image_map:
        return image_map, notes

    if reference_source:
        source_path = Path(reference_source)
        if source_path.exists():
            image_map.update(_reference_image_map_from_dir(source_path, len(canonical_pages)))
            if image_map:
                return image_map, notes
        notes.append(f"reference_source_not_found:{source_path}")

    reference_path = diagnostics.get("reference_path")
    if reference_path:
        source_path = Path(reference_path)
        if source_path.exists() and source_path.is_dir():
            image_map.update(_reference_image_map_from_dir(source_path, len(canonical_pages)))
            if image_map:
                return image_map, notes

    for page in canonical_pages:
        page_number = int(page.get("page") or 0)
        sample_id = str(page.get("sample_id") or "")
        preview_path = _fallback_preview_path(reference_dir, sample_id)
        if page_number > 0 and preview_path is not None:
            image_map[page_number] = preview_path

    if image_map:
        notes.append("using_layout_preview_fallback")
    else:
        notes.append("no_reference_page_images_found")
    return image_map, notes


def build_render_plan(reference_artifact_dir: str, generation_artifact_dir: str) -> Dict[str, object]:
    reference_dir = _resolve_reference_dir(reference_artifact_dir)
    generation_dir = _resolve_generation_dir(generation_artifact_dir)

    blueprint = _read_json(generation_dir / "reference_blueprint.json")
    drafts = _read_json(generation_dir / "slot_drafts.json")
    canonical_pages = _read_json(reference_dir / "canonical_pages.json")

    slots = blueprint.get("slots", [])
    slot_lookup = {slot.get("slot_id"): slot for slot in slots}
    block_lookup = {
        block.get("block_id"): {"page": page.get("page"), "bbox_px": block.get("bbox_px"), "canonical_label": block.get("canonical_label")}
        for page in canonical_pages
        for block in page.get("blocks", [])
    }

    pages: Dict[int, List[dict]] = {}
    skipped: List[dict] = []

    for draft in drafts:
        slot_id = draft.get("slot_id")
        slot = slot_lookup.get(slot_id)
        if slot is None:
            skipped.append({"slot_id": slot_id, "reason": "missing_slot"})
            continue

        if slot.get("preserve_reference_text") or draft.get("used_reference_text"):
            skipped.append({"slot_id": slot_id, "block_id": slot.get("block_id"), "reason": "preserved_reference"})
            continue

        text = str(draft.get("text") or "").strip()
        if not text:
            skipped.append({"slot_id": slot_id, "block_id": slot.get("block_id"), "reason": "empty_text"})
            continue

        block_id = slot.get("block_id")
        block = block_lookup.get(block_id)
        if block is None:
            skipped.append({"slot_id": slot_id, "block_id": block_id, "reason": "missing_block"})
            continue

        if block.get("canonical_label") in {"table", "chart", "image"}:
            skipped.append({"slot_id": slot_id, "block_id": block_id, "reason": "unsupported_block_type"})
            continue

        page_number = int(block.get("page") or 0)
        if page_number <= 0:
            skipped.append({"slot_id": slot_id, "block_id": block_id, "reason": "invalid_page"})
            continue

        pages.setdefault(page_number, []).append(
            {
                "slot_id": slot_id,
                "block_id": block_id,
                "bbox_px": block.get("bbox_px"),
                "text": text,
                "order_index": int(slot.get("order_index") or 0),
                "render_as": draft.get("render_as") or slot.get("render_as"),
                "needs_review": bool(draft.get("needs_review")),
            }
        )

    for items in pages.values():
        items.sort(key=lambda item: item["order_index"])

    return {
        "reference_dir": str(reference_dir),
        "generation_dir": str(generation_dir),
        "pages": pages,
        "skipped": skipped,
    }


def render_generated_document(
    reference_artifact_dir: str,
    generation_artifact_dir: str,
    llm2doc_root: str = "llm-to-document",
    output_dir: Optional[str] = None,
    reference_source: Optional[str] = None,
) -> Dict[str, object]:
    erase_bounding_box, render_boxes = _ensure_llm2doc_render_importable(llm2doc_root)

    reference_dir = _resolve_reference_dir(reference_artifact_dir)
    generation_dir = _resolve_generation_dir(generation_artifact_dir)
    output_root = ensure_dir(_resolve_output_dir(reference_dir, generation_dir, output_dir))

    canonical_pages = _read_json(reference_dir / "canonical_pages.json")
    diagnostics = _read_json(reference_dir / "parser_diagnostics.json")
    plan = build_render_plan(reference_artifact_dir, generation_artifact_dir)
    page_image_map, image_notes = _page_image_map(reference_dir, canonical_pages, diagnostics, reference_source)

    rendered_pages: List[dict] = []
    missing_pages: List[int] = []

    for page in canonical_pages:
        page_number = int(page.get("page") or 0)
        image_path = page_image_map.get(page_number)
        if image_path is None:
            missing_pages.append(page_number)
            continue

        render_items = plan["pages"].get(page_number, [])
        target_path = output_root / f"page_{page_number:03d}.png"

        with Image.open(image_path) as opened:
            image = opened.convert("RGBA")

        if render_items:
            for item in render_items:
                bbox = item.get("bbox_px")
                if bbox:
                    image = erase_bounding_box(image, bbox)

            bboxes = [item["bbox_px"] for item in render_items]
            texts = [item["text"] for item in render_items]
            image = render_boxes(image, bboxes, texts=texts, selected=None)

        image.save(target_path)
        rendered_pages.append(
            {
                "page": page_number,
                "source_image": str(image_path),
                "output_image": str(target_path),
                "rendered_block_count": len(render_items),
                "rendered_blocks": render_items,
            }
        )

    manifest = {
        "reference_artifact_dir": str(reference_dir),
        "generation_artifact_dir": str(generation_dir),
        "output_dir": str(output_root),
        "image_resolution_notes": image_notes,
        "rendered_pages": rendered_pages,
        "missing_pages": missing_pages,
        "skipped_slots": plan["skipped"],
    }
    manifest_path = output_root / "render_manifest.json"
    save_json(manifest_path, manifest)

    return {
        "output_dir": str(output_root),
        "render_manifest": str(manifest_path),
        "rendered_page_count": len(rendered_pages),
        "missing_page_count": len(missing_pages),
    }
