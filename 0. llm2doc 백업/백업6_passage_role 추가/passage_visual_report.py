from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image

from llm2doc.artifact.semantic import SemanticArtifact


@dataclass(frozen=True)
class PassageVisualDocument:
    role: str
    doc_id: int
    display_name: str
    semantic_artifact: SemanticArtifact
    page_images: Sequence[Image.Image]


def write_passage_visual_report(root: str | Path, documents: Sequence[PassageVisualDocument]) -> list[str]:
    """Write static document-level HTML pages that overlay passage grouping on page images."""
    report_root = Path(root) / "passage_visual"
    asset_root = report_root / "assets"
    report_root.mkdir(parents=True, exist_ok=True)
    asset_root.mkdir(parents=True, exist_ok=True)
    _clear_existing_report_files(report_root, asset_root)

    document_links: list[tuple[str, str]] = []
    for document in documents:
        document_links.append(_write_document_report(report_root, asset_root, document))

    index_path = report_root / "index.html"
    index_path.write_text(_render_index(document_links), encoding="utf-8")
    return ["passage_visual/index.html", *[path for _, path in document_links]]


def _clear_existing_report_files(report_root: Path, asset_root: Path) -> None:
    for path in report_root.glob("*.html"):
        path.unlink()
    for path in asset_root.glob("*.png"):
        path.unlink()


def _write_document_report(
    report_root: Path,
    asset_root: Path,
    document: PassageVisualDocument,
) -> tuple[str, str]:
    artifact = document.semantic_artifact
    passage_by_block: dict[str, object] = {}
    for passage in artifact.passages:
        for block_id in passage.block_ids:
            passage_by_block[block_id] = passage

    excluded_by_block = {item.block_id: item for item in artifact.excluded_blocks}
    safe_doc = _slug(f"{document.role}_{document.doc_id}")
    page_sections: list[str] = []

    for page_index, page in enumerate(artifact.canonical_pages, start=1):
        image_rel = ""
        if page_index <= len(document.page_images):
            image_name = f"{safe_doc}_page_{page_index}.png"
            image_path = asset_root / image_name
            _save_page_image(document.page_images[page_index - 1], image_path)
            image_rel = f"assets/{image_name}"

        page_sections.append(
            _render_page_section(
                page_title=f"Page {page_index}",
                image_rel=image_rel,
                page_width=page.width,
                page_height=page.height,
                blocks=page.blocks,
                passage_by_block=passage_by_block,
                excluded_by_block=excluded_by_block,
            )
        )

    report_filename = f"{safe_doc}.html"
    title = f"{document.role} doc {document.doc_id} - {document.display_name}"
    (report_root / report_filename).write_text(_render_document(title, page_sections), encoding="utf-8")
    return title, f"passage_visual/{report_filename}"


def _save_page_image(image: Image.Image, path: Path) -> None:
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGB")
    image.save(path)


def _render_index(page_links: Sequence[tuple[str, str]]) -> str:
    items = "\n".join(
        f'<li><a href="{html.escape(Path(path).name)}">{html.escape(label)}</a></li>'
        for label, path in page_links
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Passage Visual Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #172033; }}
    h1 {{ font-size: 24px; margin: 0 0 20px; }}
    li {{ margin: 8px 0; }}
    a {{ color: #1d4ed8; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <h1>Passage Visual Report</h1>
  <ul>
    {items}
  </ul>
</body>
</html>
"""


def _render_page_section(
    *,
    page_title: str,
    image_rel: str,
    page_width: int,
    page_height: int,
    blocks: Sequence[object],
    passage_by_block: dict[str, object],
    excluded_by_block: dict[str, object],
) -> str:
    passage_order: list[str] = []
    for block in blocks:
        passage = passage_by_block.get(block.block_id)
        if passage is not None and passage.passage_id not in passage_order:
            passage_order.append(passage.passage_id)

    color_by_passage = {
        passage_id: _PALETTE[index % len(_PALETTE)]
        for index, passage_id in enumerate(passage_order)
    }

    overlay_html: list[str] = []
    for order, block in enumerate(blocks, start=1):
        passage = passage_by_block.get(block.block_id)
        excluded = excluded_by_block.get(block.block_id)
        if passage is not None:
            color = color_by_passage.get(passage.passage_id, _PALETTE[0])
            css_class = "block passage"
            panel_payload = _passage_payload(passage)
            label = f"{order}. {passage.passage_id}"
        elif excluded is not None:
            color = "#8a8f98"
            css_class = "block excluded"
            panel_payload = {
                "type": "excluded",
                "block_id": block.block_id,
                "reason": excluded.reason,
                "text": block.text,
            }
            label = f"{order}. excluded"
        else:
            color = "#6b7280"
            css_class = "block unassigned"
            panel_payload = {
                "type": "unassigned",
                "block_id": block.block_id,
                "text": block.text,
            }
            label = f"{order}. unassigned"

        x1, y1, x2, y2 = block.bbox_px
        style = (
            f"left:{x1}px;top:{y1}px;width:{max(1, x2 - x1)}px;height:{max(1, y2 - y1)}px;"
            f"--border:{color};--fill:{_rgba(color, 0.18)};"
        )
        tooltip = _tooltip_for_block(block, passage, excluded)
        overlay_html.append(
            '<button class="{css_class}" style="{style}" title="{title}" '
            'data-info="{info}" onclick="showInfo(this)">'
            '<span>{label}</span></button>'.format(
                css_class=css_class,
                style=html.escape(style, quote=True),
                title=html.escape(tooltip, quote=True),
                info=html.escape(json.dumps(panel_payload, ensure_ascii=False), quote=True),
                label=html.escape(label),
            )
        )

    page_image = (
        f'<img class="page-image" src="{html.escape(image_rel)}" width="{page_width}" height="{page_height}" alt="">'
        if image_rel
        else '<div class="missing-image">No page image available</div>'
    )

    return f"""
      <section class="page-section">
        <h2>{html.escape(page_title)}</h2>
        <div class="page-stage" style="width:{page_width}px;height:{page_height}px">
          {page_image}
          {"".join(overlay_html)}
        </div>
      </section>
"""


def _render_document(title: str, page_sections: Sequence[str]) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; color: #172033; background: #f3f4f6; }}
    .layout {{ display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; padding: 16px; }}
    .document-scroll {{ overflow: auto; height: calc(100vh - 32px); background: #d7dbe2; border: 1px solid #b8c0cc; padding: 18px; }}
    .page-section {{ width: max-content; margin: 0 auto 24px; }}
    .page-section h2 {{ font-size: 14px; margin: 0 0 8px; color: #374151; }}
    .page-stage {{ position: relative; background: white; box-shadow: 0 1px 6px rgba(15,23,42,.2); }}
    .page-image {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
    .missing-image {{ position: absolute; inset: 0; display: grid; place-items: center; color: #6b7280; }}
    .block {{ position: absolute; z-index: 2; box-sizing: border-box; border: 2px solid var(--border); background: var(--fill); padding: 0; text-align: left; cursor: pointer; }}
    .block span {{ position: absolute; left: 2px; top: 2px; font: 11px/1.2 Arial, sans-serif; color: #111827; background: rgba(255,255,255,.78); padding: 1px 3px; max-width: calc(100% - 4px); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .block:hover, .block.active {{ outline: 3px solid rgba(17,24,39,.75); outline-offset: 1px; z-index: 5; }}
    .excluded {{ background: repeating-linear-gradient(45deg, rgba(120,120,120,.25), rgba(120,120,120,.25) 6px, rgba(255,255,255,.18) 6px, rgba(255,255,255,.18) 12px); }}
    .unassigned {{ border-style: dashed; }}
    aside {{ background: white; border: 1px solid #c8ced8; padding: 16px; height: calc(100vh - 66px); overflow: auto; position: sticky; top: 16px; }}
    h1 {{ font-size: 18px; margin: 0 0 12px; }}
    h2 {{ font-size: 15px; margin: 20px 0 8px; }}
    .legend-item {{ border-left: 8px solid var(--color); padding: 6px 0 6px 8px; margin: 6px 0; background: #f9fafb; }}
    .legend-title {{ font-weight: 700; font-size: 13px; }}
    .legend-meta, .empty {{ font-size: 12px; color: #5c6675; }}
    pre {{ white-space: pre-wrap; word-break: break-word; font: 12px/1.45 Consolas, monospace; background: #f7f8fa; padding: 10px; border: 1px solid #e1e5ec; }}
    .kv {{ font-size: 13px; margin: 4px 0; }}
    .label {{ color: #5c6675; }}
  </style>
</head>
<body>
  <div class="layout">
    <main class="document-scroll">
      {"".join(page_sections)}
    </main>
    <aside>
      <h1>{html.escape(title)}</h1>
      <h2>Selected</h2>
      <div id="panel" class="empty">Click a block to inspect passage details.</div>
    </aside>
  </div>
  <script>
    function showInfo(el) {{
      document.querySelectorAll('.block.active').forEach(function(node) {{ node.classList.remove('active'); }});
      el.classList.add('active');
      var data = JSON.parse(el.dataset.info);
      var panel = document.getElementById('panel');
      var rows = [];
      Object.keys(data).forEach(function(key) {{
        var value = data[key];
        if (Array.isArray(value)) value = value.join(', ');
        rows.push('<div class="kv"><span class="label">' + escapeHtml(key) + ':</span> ' + escapeHtml(String(value || '')) + '</div>');
      }});
      panel.innerHTML = rows.join('') + '<pre>' + escapeHtml(data.text || data.retrieval_text || data.summary || '') + '</pre>';
    }}
    function escapeHtml(value) {{
      return value.replace(/[&<>"']/g, function(ch) {{
        return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch];
      }});
    }}
  </script>
</body>
</html>
"""


def _passage_payload(passage: object) -> dict[str, object]:
    return {
        "type": "passage",
        "passage_id": passage.passage_id,
        "title": passage.title,
        "main_function": passage.main_function,
        "page_span": passage.page_span,
        "block_ids": passage.block_ids,
        "summary": passage.summary,
        "retrieval_text": passage.retrieval_text,
    }


def _tooltip_for_block(block: object, passage: object | None, excluded: object | None) -> str:
    if passage is not None:
        heading = f"{passage.passage_id} | {passage.title or '(untitled)'}"
    elif excluded is not None:
        heading = f"excluded | {excluded.reason}"
    else:
        heading = "unassigned"
    text = re.sub(r"\s+", " ", block.text or "").strip()
    if len(text) > 240:
        text = text[:237] + "..."
    return f"{heading}\n{block.block_id}\n{text}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return slug.strip("._") or "document"


def _rgba(hex_color: str, alpha: float) -> str:
    color = hex_color.lstrip("#")
    if len(color) != 6:
        return f"rgba(107, 114, 128, {alpha})"
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


_PALETTE = [
    "#2563eb",
    "#059669",
    "#dc2626",
    "#7c3aed",
    "#0891b2",
    "#ea580c",
    "#16a34a",
    "#9333ea",
    "#0f766e",
    "#be123c",
    "#4f46e5",
    "#ca8a04",
]
