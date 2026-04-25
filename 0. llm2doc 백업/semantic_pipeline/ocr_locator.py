import re
from pathlib import Path
from typing import Dict, List, Optional

from .types import PageSource


SAMPLE_PATTERNS = [
    re.compile(r"(financial\d+(?:-\d+)?)", re.IGNORECASE),
    re.compile(r"(blog\d+(?:-\d+)?)", re.IGNORECASE),
    re.compile(r"(medical\d+(?:-\d+)?)", re.IGNORECASE),
    re.compile(r"(company\d+(?:-\d+)?)", re.IGNORECASE),
]


def _candidate_stems(stem: str) -> List[str]:
    candidates = [stem]
    normalized = re.sub(r"[^A-Za-z0-9]+", "", stem)
    if normalized and normalized not in candidates:
        candidates.append(normalized)
    lowered = stem.lower()
    for pattern in SAMPLE_PATTERNS:
        match = pattern.search(lowered)
        if not match:
            continue
        token = match.group(1)
        candidates.append(token)
        if re.fullmatch(r"(financial|blog|medical)\d+", token):
            candidates.append(f"{token}-00")
    return list(dict.fromkeys(candidates))


def _find_dolphin_pages(ocr_root: Path, stem: str) -> List[Path]:
    output_dir = ocr_root / "dolphin" / "output_json"
    for candidate in _candidate_stems(stem):
        exact = output_dir / f"{candidate}.json"
        if exact.exists():
            return [exact]
        grouped = sorted(output_dir.glob(f"{candidate}-*.json"))
        if grouped:
            return grouped
    return []


def _map_paddle_json(ocr_root: Path, sample_id: str) -> Optional[Path]:
    if sample_id.startswith("financial1-00"):
        path = ocr_root / "paddle" / "Paddle_json" / "financial1" / "original-00_res.json"
        return path if path.exists() else None
    if sample_id.startswith("financial2-00"):
        path = ocr_root / "paddle" / "Paddle_json" / "financial2" / "original-00_res.json"
        return path if path.exists() else None
    if sample_id.startswith("medical1"):
        path = ocr_root / "paddle" / "Paddle_json" / "medical1" / "original-00_res.json"
        return path if path.exists() else None
    return None


def _map_paddle_markdown(ocr_root: Path, sample_id: str) -> Optional[Path]:
    if sample_id.startswith("financial1-00"):
        path = ocr_root / "paddle" / "Paddle_json" / "financial1" / "original-00.md"
        return path if path.exists() else None
    if sample_id.startswith("financial2-00"):
        path = ocr_root / "paddle" / "Paddle_json" / "financial2" / "original-00.md"
        return path if path.exists() else None
    if sample_id.startswith("medical1"):
        path = ocr_root / "paddle" / "Paddle_json" / "medical1" / "original-00.md"
        return path if path.exists() else None
    return None


def locate_reference_pages(reference_path: str, ocr_results_root: str) -> List[PageSource]:
    ocr_root = Path(ocr_results_root)
    reference = Path(reference_path)
    stem = reference.stem if reference.suffix else reference.name
    dolphin_pages = _find_dolphin_pages(ocr_root, stem)
    if not dolphin_pages and reference.suffix == ".json" and reference.exists():
        dolphin_pages = [reference]
    if not dolphin_pages:
        raise FileNotFoundError(
            f"No precomputed OCR pages were found for reference '{reference_path}'. "
            "Use a sample whose basename matches OCR_results/dolphin/output_json."
        )

    sources: List[PageSource] = []
    for index, dolphin_json in enumerate(dolphin_pages, start=1):
        sample_id = dolphin_json.stem
        sources.append(
            PageSource(
                page_number=index,
                sample_id=sample_id,
                dolphin_json_path=str(dolphin_json),
                dolphin_layout_path=str(ocr_root / "dolphin" / "layout_visualization" / f"{sample_id}_layout.png"),
                dolphin_markdown_path=str(ocr_root / "dolphin" / "markdown" / f"{sample_id}.md"),
                paddle_json_path=str(_map_paddle_json(ocr_root, sample_id)) if _map_paddle_json(ocr_root, sample_id) else None,
                paddle_markdown_path=str(_map_paddle_markdown(ocr_root, sample_id)) if _map_paddle_markdown(ocr_root, sample_id) else None,
                paddle_visualization_path=str(ocr_root / "paddle" / "visualization" / f"{sample_id}.png"),
                surya_image_path=str(ocr_root / "surya" / f"{sample_id}.png"),
            )
        )
    return sources


def available_preview_paths(page_source: PageSource) -> Dict[str, str]:
    previews = {}
    if page_source.dolphin_layout_path and Path(page_source.dolphin_layout_path).exists():
        previews["dolphin_layout"] = page_source.dolphin_layout_path
    if page_source.paddle_visualization_path and Path(page_source.paddle_visualization_path).exists():
        previews["paddle_visualization"] = page_source.paddle_visualization_path
    if page_source.surya_image_path and Path(page_source.surya_image_path).exists():
        previews["surya_image"] = page_source.surya_image_path
    return previews
