import json
import shutil
import sys
from pathlib import Path
from typing import Any, List

from ..common.types import EnginePage, PageSource, RawEngineBlock
from ..common.utils import ensure_dir, normalize_bbox


def _ensure_llm2doc_importable(llm2doc_root: str | Path):
    root = Path(llm2doc_root).resolve()
    package_dir = root / "llm2doc"
    if not package_dir.exists():
        raise FileNotFoundError(f"llm2doc package directory does not exist: {package_dir}")

    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    from llm2doc.analyze_layout import LayoutAnalyzer

    return LayoutAnalyzer


def resolve_llm2doc_reference_path(reference_doc_id: str, llm2doc_root: str | Path) -> Path:
    data_dir = Path(llm2doc_root).resolve() / "data" / reference_doc_id
    if not data_dir.exists():
        raise FileNotFoundError(f"llm2doc document directory does not exist: {data_dir}")
    return data_dir


def _source_image_names(doc_dir: Path) -> List[str]:
    names = [path.name for path in doc_dir.iterdir() if path.is_file() and path.name.startswith("original")]
    names.sort()
    return names


def _sample_id(doc_id: str, image_name: str, page_count: int) -> str:
    if page_count == 1:
        return doc_id

    suffix = Path(image_name).stem.removeprefix("original-")
    return f"{doc_id}-{suffix}"


def load_llm2doc_pages(reference_doc_id: str, llm2doc_root: str | Path) -> List[EnginePage]:
    root = Path(llm2doc_root).resolve()
    doc_dir = resolve_llm2doc_reference_path(reference_doc_id, root)
    image_names = _source_image_names(doc_dir)
    LayoutAnalyzer = _ensure_llm2doc_importable(root)

    analyzer = LayoutAnalyzer(data_root=root / "data")
    parsed = analyzer(reference_doc_id)

    if len(parsed.pages) != len(image_names):
        analyzer.dispose()
        raise ValueError(
            f"page count mismatch for {reference_doc_id}: "
            f"{len(parsed.pages)} parsed pages vs {len(image_names)} source images"
        )

    pages: List[EnginePage] = []

    for page_index, (page, image_name) in enumerate(zip(parsed.pages, image_names), start=1):
        sample_id = _sample_id(reference_doc_id, image_name, len(image_names))
        raw_blocks = []

        for order, block in enumerate(page.blocks):
            raw_blocks.append(
                RawEngineBlock(
                    engine="paddle",
                    page=page_index,
                    raw_label=block.label,
                    text=block.content or "",
                    bbox_px=[int(value) for value in block.bbox],
                    bbox_norm=normalize_bbox(block.bbox, page.width, page.height),
                    reading_order=order,
                    polygon=[],
                    tags=[],
                    raw_confidence=None,
                )
            )

        pages.append(
            EnginePage(
                engine="paddle",
                page=page_index,
                sample_id=sample_id,
                width=page.width,
                height=page.height,
                raw_blocks=raw_blocks,
                source_paths={
                    "image": str((doc_dir / image_name).resolve()),
                },
                metadata={
                    "llm2doc_root": str(root),
                    "reference_doc_id": reference_doc_id,
                    "image_name": image_name,
                    "json": page.json,
                    "markdown": page.markdown,
                    "markdown_image_count": len(page.markdown_images),
                },
            )
        )

    analyzer.dispose()
    return pages


def build_llm2doc_page_sources(
    reference_doc_id: str, llm2doc_root: str | Path, pages: List[EnginePage]
) -> List[PageSource]:
    root = Path(llm2doc_root).resolve()
    doc_dir = resolve_llm2doc_reference_path(reference_doc_id, root)
    sources: List[PageSource] = []

    for page in pages:
        sources.append(
            PageSource(
                page_number=page.page,
                sample_id=page.sample_id,
                source_type="llm2doc",
                reference_doc_id=reference_doc_id,
                document_dir=str(doc_dir),
                image_path=page.source_paths.get("image"),
            )
        )

    return sources


def save_llm2doc_artifacts(pages: List[EnginePage], artifact_dir: Path) -> None:
    raw_paddle_dir = ensure_dir(artifact_dir / "raw" / "paddle")
    preview_dir = ensure_dir(artifact_dir / "layout_preview")

    for page in pages:
        sample_id = page.sample_id

        page_json = page.metadata.get("json")
        if isinstance(page_json, str) and page_json.strip():
            try:
                payload = json.loads(page_json)
            except json.JSONDecodeError:
                payload = page_json

            rendered = (
                json.dumps(payload, ensure_ascii=False, indent=2)
                if not isinstance(payload, str)
                else payload
            )
            (raw_paddle_dir / f"{sample_id}.json").write_text(rendered, encoding="utf-8")

        page_markdown = page.metadata.get("markdown")
        if isinstance(page_markdown, str) and page_markdown.strip():
            (raw_paddle_dir / f"{sample_id}.md").write_text(page_markdown, encoding="utf-8")

        image_path = page.source_paths.get("image")
        if image_path:
            image_source = Path(image_path)
            if image_source.exists():
                target = preview_dir / f"{sample_id}_paddle_visualization{image_source.suffix}"
                shutil.copy2(str(image_source), str(target))
