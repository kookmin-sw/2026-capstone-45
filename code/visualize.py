import base64
import html
import json
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image


ROLE_COLORS = {
    "main_title": "#b91c1c",
    "section_heading": "#1d4ed8",
    "summary": "#0f766e",
    "body": "#1f2937",
    "evidence": "#7c3aed",
    "metadata": "#475569",
    "author_info": "#0369a1",
    "disclaimer": "#92400e",
}

LABEL_COLORS = {
    "document_title": "#dc2626",
    "section_heading": "#2563eb",
    "subheading": "#3b82f6",
    "paragraph": "#374151",
    "paragraph_or_meta": "#4b5563",
    "image": "#9333ea",
    "table": "#7c3aed",
    "chart": "#6d28d9",
    "meta_candidate": "#64748b",
    "caption_or_panel_title": "#059669",
}

GENERIC_ROLE_MEANINGS = {
    "main_title": "문서 전체의 대표 제목입니다.",
    "section_heading": "아래에 이어질 내용의 주제를 여는 섹션 제목입니다.",
    "summary": "핵심 요약이나 결론을 먼저 보여주는 블록입니다.",
    "body": "실제 서술과 설명이 이어지는 본문입니다.",
    "evidence": "표, 차트, 이미지처럼 근거 자료 역할을 하는 블록입니다.",
    "metadata": "문서 헤더, 발행 정보, 기관명 같은 메타데이터입니다.",
    "author_info": "작성자, 감수자, 분석가 정보입니다.",
    "disclaimer": "면책, 규정, 법적 고지 영역입니다.",
    "unknown": "현재 파이프라인이 의미를 확정하지 못한 블록입니다.",
}

DOMAIN_ROLE_MEANINGS = {
    "report_header_meta": "리포트 상단의 발행 정보, 기관 브랜드, 날짜 같은 헤더 메타정보입니다.",
    "investment_opinion_box": "투자의견, 목표주가, 현재주가처럼 요약 투자 판단을 담는 박스입니다.",
    "key_data_box": "핵심 지표를 요약해 보여주는 데이터 패널입니다.",
    "consensus_box": "컨센서스 수치나 추정치를 모아둔 패널입니다.",
    "price_chart_block": "주가 흐름을 보여주는 차트 영역입니다.",
    "financial_table_block": "재무 수치나 정량 데이터를 담은 표입니다.",
    "report_title": "문서의 대표 제목입니다.",
    "thesis_heading": "핵심 주장이나 논지의 제목입니다.",
    "supporting_argument": "주장을 뒷받침하는 설명 또는 논거입니다.",
    "analyst_info": "애널리스트/작성자 식별 정보입니다.",
    "research_center_meta": "리서치센터나 발행 기관 정보입니다.",
    "disclaimer_block": "법적 고지나 면책 문구입니다.",
    "unsupported_evidence": "시각 자료이지만 현재는 더 구체적으로 분류하지 않은 근거 블록입니다.",
}

SEMANTIC_SOURCE_MEANINGS = {
    "qwen": "Qwen 모델의 결과가 최종 채택된 상태입니다.",
    "rule": "기존 규칙 기반 결과가 최종 적용된 상태입니다.",
    "safety_rule": "안전 규칙이 최종 fallback으로 적용된 상태입니다.",
    "unknown_fallback": "모델 결과를 쓰지 못했고 규칙도 적용되지 않아 unknown으로 남은 상태입니다.",
}

FALLBACK_REASON_MEANINGS = {
    "backend_error": "모델 호출 또는 로딩 단계에서 오류가 발생해 fallback 되었습니다.",
    "invalid_json": "모델 응답이 기대한 JSON 형식이 아니어서 fallback 되었습니다.",
    "schema_mismatch": "응답 JSON은 있었지만 스키마가 맞지 않아 fallback 되었습니다.",
    "low_role_confidence": "모델 confidence가 기준보다 낮아 fallback 되었습니다.",
    "low_page_quality": "페이지 품질 점수가 낮아 모델 추론을 건너뛰었습니다.",
    "shadow_mode_not_applied": "shadow 모드라 모델 결과를 기록만 하고 실제 적용은 하지 않았습니다.",
}

WARNING_MEANINGS = {
    "low_ocr_quality_repaired_via_secondary_engine": "주 엔진 OCR 품질이 낮았지만 보조 엔진 결과로 일부 복구되었다는 뜻입니다.",
}

CONFIDENCE_SUMMARY_MEANINGS = {
    "overall_score": "문서 전반의 품질/신뢰도 요약 점수입니다.",
    "review_required": "사람 검토가 필요한지 여부입니다.",
    "high_noise_pages": "노이즈가 심한 페이지 목록입니다.",
    "fusion_conflicts": "OCR 엔진 간 충돌 또는 교체가 있었던 횟수입니다.",
    "unsupported_page_count": "현재 MVP에서 제대로 지원하지 않는 페이지 수입니다.",
    "notes": "파이프라인이 남긴 추가 메모입니다.",
}

SEMANTIC_METRIC_MEANINGS = {
    "mode": "semantic 결과를 어떤 운영 모드로 생성했는지 보여줍니다.",
    "backend": "실제 semantic 추론 backend입니다.",
    "model_name": "semantic 추론에 사용한 모델명입니다.",
    "prompt_version": "semantic prompt 버전입니다.",
    "page_count": "처리한 페이지 수입니다.",
    "block_count": "전체 블록 수입니다.",
    "attempted_count": "모델 추론을 시도한 블록 수입니다.",
    "accepted_count": "모델 결과가 최종 채택된 블록 수입니다.",
    "fallback_count": "모델 결과 대신 fallback이 적용된 블록 수입니다.",
    "needs_review_count": "사람 검토 플래그가 켜진 블록 수입니다.",
    "avg_role_confidence": "최종 semantic 결정들의 평균 confidence입니다.",
    "shadow_disagreement_count": "shadow 비교 시 rule과 model이 달랐던 횟수입니다.",
}

JSON_ARTIFACT_GUIDE = [
    (
        "reference_template.json",
        "최종 템플릿 산출물",
        "문서군, 섹션 순서, 스타일 토큰, 블록 역할처럼 downstream이 실제로 쓰는 대표 결과입니다.",
    ),
    (
        "canonical_pages.json",
        "페이지/블록 정규화 결과",
        "엔진별 OCR을 합친 뒤 블록 단위로 정리한 페이지 구조입니다. 화면 오버레이와 블록 테이블의 원본이 됩니다.",
    ),
    (
        "parser_diagnostics.json",
        "파이프라인 상태 보고서",
        "페이지 품질, fusion 교체, semantic 요약 등 결과가 왜 이렇게 나왔는지 추적하는 진단 정보입니다.",
    ),
    (
        "semantic_overlay.json",
        "블록별 최종 semantic 결과",
        "각 블록에 대해 최종적으로 어떤 role이 적용됐는지, 어떤 source에서 왔는지 보여줍니다.",
    ),
    (
        "semantic_trace.json",
        "모델 추론 과정 기록",
        "입력 컨텍스트, raw 응답, parsed/applied decision을 함께 남겨 모델이 어떤 판단을 했는지 확인할 수 있습니다.",
    ),
]


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_json(path: Path):
    if not path.exists():
        return None
    return _load_json(path)


def _color_for_block(block: Dict[str, object]) -> str:
    generic_role = block.get("generic_role")
    if generic_role in ROLE_COLORS:
        return ROLE_COLORS[generic_role]
    return LABEL_COLORS.get(block.get("canonical_label"), "#111827")


def _escape(value: object) -> str:
    return html.escape(str(value))


def _format_value(value: object) -> str:
    if value is None or value == "":
        return "-"
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    if isinstance(value, float):
        rendered = "%.4f" % value
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "-"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _json_pre(value: object) -> str:
    return "<pre>%s</pre>" % _escape(json.dumps(value, ensure_ascii=False, indent=2))


def _preview_text(text: object, limit: int = 180) -> str:
    value = (text or "").strip()
    if not value:
        return "-"
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _role_label(generic_role: Optional[str], domain_role: Optional[str]) -> str:
    if not generic_role and not domain_role:
        return "-"
    return "%s / %s" % (generic_role or "-", domain_role or "-")


def _meaning_for_role(generic_role: Optional[str], domain_role: Optional[str], generated_role_name: Optional[str] = None) -> str:
    pieces: List[str] = []
    if domain_role and domain_role in DOMAIN_ROLE_MEANINGS:
        pieces.append(DOMAIN_ROLE_MEANINGS[domain_role])
    elif generic_role and generic_role in GENERIC_ROLE_MEANINGS:
        pieces.append(GENERIC_ROLE_MEANINGS[generic_role])
    if generated_role_name:
        pieces.append("생성 역할명 '%s'은 모델이 붙인 자유 설명용 이름입니다." % generated_role_name)
    return " ".join(pieces) if pieces else "이 블록의 의미를 해석할 단서가 아직 부족합니다."


def _meaning_for_source(source: Optional[str], fallback_reason: Optional[str] = None) -> str:
    pieces: List[str] = []
    if source and source in SEMANTIC_SOURCE_MEANINGS:
        pieces.append(SEMANTIC_SOURCE_MEANINGS[source])
    if fallback_reason and fallback_reason in FALLBACK_REASON_MEANINGS:
        pieces.append(FALLBACK_REASON_MEANINGS[fallback_reason])
    return " ".join(pieces) if pieces else "-"


def _badge(label: object, tone: str = "neutral") -> str:
    return '<span class="badge badge-%s">%s</span>' % (_escape(tone), _escape(_format_value(label)))


def _badge_for_source(source: Optional[str]) -> str:
    tone_map = {
        "qwen": "good",
        "rule": "info",
        "safety_rule": "warn",
        "unknown_fallback": "muted",
    }
    return _badge(source or "-", tone_map.get(source, "neutral"))


def _badge_for_bool(value: object) -> str:
    if value is True:
        return _badge("Yes", "good")
    if value is False:
        return _badge("No", "neutral")
    return _badge("-", "neutral")


def _preview_path(artifact_dir: Path, sample_id: str) -> Optional[Path]:
    preview_dir = artifact_dir / "layout_preview"
    candidates = [
        preview_dir / ("%s_surya_image.png" % sample_id),
        preview_dir / ("%s_dolphin_layout.png" % sample_id),
        preview_dir / ("%s_paddle_visualization.png" % sample_id),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _image_data_uri(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return "data:%s;base64,%s" % (mime, encoded)


def _render_reference_pages(reference_source: Path, output_dir: Path, page_count: int) -> Dict[int, Path]:
    rendered: Dict[int, Path] = {}
    output_dir.mkdir(parents=True, exist_ok=True)

    if reference_source.suffix.lower() == ".pdf":
        import fitz

        document = fitz.open(reference_source)
        for page_index in range(min(page_count, document.page_count)):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            target = output_dir / ("page_%03d.png" % (page_index + 1))
            pixmap.save(target)
            rendered[page_index + 1] = target
        return rendered

    with Image.open(reference_source) as image:
        target = output_dir / "page_001.png"
        image.convert("RGB").save(target)
        rendered[1] = target
    return rendered


def _summary_cards(template: Dict[str, object]) -> str:
    items = [
        ("Document Family", template.get("document_family"), "문서군 분류 결과"),
        ("Language", template.get("language"), "감지된 언어"),
        ("Source Engines", ", ".join(template.get("source_engines", [])), "결합에 사용된 OCR 엔진"),
        ("Anchor Pages", ", ".join(str(page) for page in template.get("anchor_pages", [])) or "-", "문서 구조의 기준 페이지"),
        ("Review Required", template.get("confidence_summary", {}).get("review_required"), "사람 검토 필요 여부"),
        ("Unsupported For MVP", template.get("unsupported_for_mvp"), "현재 범위에서 지원 불가 여부"),
    ]
    cards = []
    for label, value, hint in items:
        cards.append(
            '<div class="card"><div class="card-label">%s</div><div class="card-value">%s</div><div class="card-hint">%s</div></div>'
            % (_escape(label), _escape(_format_value(value)), _escape(hint))
        )
    return "\n".join(cards)

def _section_order_html(template: Dict[str, object]) -> str:
    sections = template.get("section_order", [])
    if not sections:
        return '<div class="empty">No section_order extracted.</div>'
    rows = []
    for section in sections:
        rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (
                _escape(section.get("section_id")),
                _escape(_format_value(section.get("page"))),
                _escape(section.get("title")),
                _escape(section.get("purpose") or "-"),
            )
        )
    table = (
        '<table class="grid-table"><thead><tr><th>Section</th><th>Page</th><th>Title</th><th>Purpose</th></tr></thead>'
        "<tbody>%s</tbody></table>" % "".join(rows)
    )
    return '<div class="table-wrap">%s</div>' % table


def _semantic_cards(diagnostics: Dict[str, object]) -> str:
    semantic = diagnostics.get("semantic", {})
    if not semantic:
        return '<div class="empty">No semantic diagnostics available.</div>'
    items = [
        ("Semantic Mode", semantic.get("mode"), "semantic 파이프라인 운영 모드"),
        ("Semantic Backend", semantic.get("backend"), "실제 추론 backend"),
        ("Model", semantic.get("model_name"), "semantic 추론 모델"),
        ("Accepted", semantic.get("accepted_count"), "최종 채택된 모델 결과 수"),
        ("Fallback", semantic.get("fallback_count"), "모델 대신 fallback이 적용된 수"),
        ("Avg Confidence", semantic.get("avg_role_confidence"), "최종 역할 confidence 평균"),
    ]
    cards = []
    for label, value, hint in items:
        cards.append(
            '<div class="card"><div class="card-label">%s</div><div class="card-value">%s</div><div class="card-hint">%s</div></div>'
            % (_escape(label), _escape(_format_value(value)), _escape(hint))
        )
    return "\n".join(cards)

def _style_tokens_html(template: Dict[str, object]) -> str:
    tokens = template.get("style_tokens", {})
    if not tokens:
        return '<div class="empty">No style tokens available.</div>'
    rows = []
    for key, value in tokens.items():
        rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (
                _escape(key),
                _escape(_format_value(value)),
                _escape("레이아웃/타이포 복원에 쓰이는 스타일 힌트"),
            )
        )
    table = (
        '<table class="grid-table"><thead><tr><th>Style Token</th><th>Value</th><th>Meaning</th></tr></thead>'
        "<tbody>%s</tbody></table>" % "".join(rows)
    )
    return '<div class="table-wrap">%s</div>' % table


def _json_reading_guide_html() -> str:
    cards = []
    for file_name, short_title, meaning in JSON_ARTIFACT_GUIDE:
        cards.append(
            '<div class="guide-card"><div class="guide-file">%s</div><div class="guide-title">%s</div><div class="guide-body">%s</div></div>'
            % (_escape(file_name), _escape(short_title), _escape(meaning))
        )
    return '<div class="guide-grid">%s</div>' % "".join(cards)


def _warning_list_html(template: Dict[str, object]) -> str:
    warnings = template.get("template_warnings", [])
    if not warnings:
        return '<div class="empty">No warnings.</div>'
    items = []
    for warning in warnings:
        items.append(
            '<li><strong>%s</strong><div class="list-hint">%s</div></li>'
            % (_escape(warning), _escape(WARNING_MEANINGS.get(warning, "파이프라인이 주의가 필요하다고 표시한 항목입니다.")))
        )
    return '<ul class="warning-list">%s</ul>' % "".join(items)


def _confidence_summary_html(template: Dict[str, object]) -> str:
    summary = template.get("confidence_summary", {})
    if not summary:
        return '<div class="empty">No diagnostics summary available.</div>'
    rows = []
    for key, value in summary.items():
        rows.append(
            '<tr><td>%s</td><td>%s</td><td>%s</td></tr>'
            % (
                _escape(key),
                _escape(_format_value(value)),
                _escape(CONFIDENCE_SUMMARY_MEANINGS.get(key, "진단 요약 항목입니다.")),
            )
        )
    table = (
        '<table class="grid-table"><thead><tr><th>Field</th><th>Value</th><th>Meaning</th></tr></thead>'
        '<tbody>%s</tbody></table>' % "".join(rows)
    )
    return '<div class="table-wrap">%s</div>' % table


def _page_analysis_html(diagnostics: Dict[str, object]) -> str:
    analyses = diagnostics.get("page_analyses", [])
    if not analyses:
        return '<div class="empty">No page analyses available.</div>'
    rows = []
    for analysis in analyses:
        rows.append(
            '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
            % (
                _escape(_format_value(analysis.get("page"))),
                _escape(analysis.get("page_archetype")),
                _escape(_format_value(analysis.get("column_count"))),
                _escape(_format_value(analysis.get("quality_score"))),
                _escape(analysis.get("dominant_layout_pattern") or "-"),
                _escape(_format_value(analysis.get("warnings") or [])),
            )
        )
    table = (
        '<table class="grid-table"><thead><tr><th>Page</th><th>Archetype</th><th>Columns</th><th>Quality</th><th>Layout</th><th>Warnings</th></tr></thead>'
        '<tbody>%s</tbody></table>' % "".join(rows)
    )
    return '<div class="table-wrap">%s</div>' % table


def _fusion_html(diagnostics: Dict[str, object]) -> str:
    fusion = diagnostics.get("fusion", {})
    if not fusion:
        return '<div class="empty">No fusion diagnostics available.</div>'
    rows = []
    for sample_id, payload in fusion.items():
        rows.append(
            '<tr><td>%s</td><td>%s</td><td>%s</td><td class="text-cell">%s</td></tr>'
            % (
                _escape(sample_id),
                _escape(_format_value(payload.get("matched_pairs"))),
                _escape(_format_value(payload.get("text_replacements"))),
                _escape(_format_value(payload.get("added_secondary_blocks") or [])),
            )
        )
    table = (
        '<table class="grid-table"><thead><tr><th>Sample</th><th>Matched Pairs</th><th>Text Replacements</th><th>Added Secondary Blocks</th></tr></thead>'
        '<tbody>%s</tbody></table>' % "".join(rows)
    )
    return '<div class="table-wrap">%s</div>' % table


def _breakdown_table_html(title: str, data: Dict[str, object], meaning_map: Dict[str, str], total: float, empty_message: str) -> str:
    if not data:
        return '<div class="subpanel"><h3>%s</h3><div class="empty">%s</div></div>' % (_escape(title), _escape(empty_message))
    rows = []
    for key, value in sorted(data.items(), key=lambda item: (-float(item[1]), item[0])):
        share = "-"
        try:
            numeric_value = float(value)
            if total:
                share = "%.1f%%" % ((numeric_value / total) * 100)
        except Exception:
            numeric_value = None
        rows.append(
            '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
            % (
                _escape(key),
                _escape(_format_value(value)),
                _escape(share),
                _escape(meaning_map.get(key, "세부 집계 항목입니다.")),
            )
        )
    table = (
        '<div class="subpanel"><h3>%s</h3><div class="table-wrap"><table class="grid-table">'
        '<thead><tr><th>Key</th><th>Count</th><th>Share</th><th>Meaning</th></tr></thead><tbody>%s</tbody></table></div></div>'
        % (_escape(title), "".join(rows))
    )
    return table


def _semantic_metric_table_html(diagnostics: Dict[str, object]) -> str:
    semantic = diagnostics.get("semantic", {})
    if not semantic:
        return '<div class="empty">No semantic diagnostics available.</div>'
    keys = [
        "mode",
        "backend",
        "model_name",
        "prompt_version",
        "page_count",
        "block_count",
        "attempted_count",
        "accepted_count",
        "fallback_count",
        "needs_review_count",
        "avg_role_confidence",
        "shadow_disagreement_count",
    ]
    rows = []
    for key in keys:
        if key not in semantic:
            continue
        rows.append(
            '<tr><td>%s</td><td>%s</td><td>%s</td></tr>'
            % (
                _escape(key),
                _escape(_format_value(semantic.get(key))),
                _escape(SEMANTIC_METRIC_MEANINGS.get(key, "semantic 진단 항목입니다.")),
            )
        )
    table = (
        '<table class="grid-table"><thead><tr><th>Metric</th><th>Value</th><th>Meaning</th></tr></thead>'
        '<tbody>%s</tbody></table>' % "".join(rows)
    )
    return '<div class="table-wrap">%s</div>' % table


def _overlay_boxes(blocks: List[Dict[str, object]]) -> str:
    overlays = []
    for block in blocks:
        bbox = block.get("bbox_norm") or [0, 0, 0, 0]
        x1, y1, x2, y2 = bbox
        width = max(0.0, x2 - x1)
        height = max(0.0, y2 - y1)
        label = "%s | %s" % (
            block.get("generated_role_name") or block.get("domain_role") or block.get("generic_role") or block.get("canonical_label"),
            block.get("block_id"),
        )
        tooltip = "%s\nsource=%s\nconfidence=%s\n%s" % (
            label,
            block.get("semantic_source") or "-",
            _format_value(block.get("role_confidence")),
            _preview_text(block.get("text"), 220),
        )
        color = _color_for_block(block)
        overlays.append(
            '<div class="overlay-box" title="%s" style="left:%0.3f%%;top:%0.3f%%;width:%0.3f%%;height:%0.3f%%;border-color:%s;">'
            '<span class="overlay-label" style="background:%s;">%s</span></div>'
            % (
                _escape(tooltip),
                x1 * 100,
                y1 * 100,
                width * 100,
                height * 100,
                _escape(color),
                _escape(color),
                _escape(label),
            )
        )
    return "".join(overlays)


def _block_inspect_html(block: Dict[str, object]) -> str:
    summary = '<div class="inspect-grid">'         '<div><strong>Section</strong><div>%s</div></div>'         '<div><strong>Purpose</strong><div>%s</div></div>'         '<div><strong>Used For Generation</strong><div>%s</div></div>'         '<div><strong>Needs Review</strong><div>%s</div></div>'         '</div>' % (
            _escape(block.get("section_id") or "-"),
            _escape(block.get("section_purpose") or "-"),
            _escape(_format_value(block.get("used_for_generation"))),
            _escape(_format_value(block.get("semantic_needs_review"))),
        )
    return '<details class="inspect"><summary>Inspect</summary>%s%s</details>' % (summary, _json_pre(block))


def _block_rows(blocks: List[Dict[str, object]]) -> str:
    rows = []
    for block in blocks:
        rows.append(
            '<tr>'
            '<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
            '<td>%s</td><td class="meaning-cell">%s</td><td class="text-cell">%s</td><td>%s</td>'
            '</tr>'
            % (
                _escape(_format_value(block.get("reading_order"))),
                _escape(block.get("block_id")),
                _escape(block.get("canonical_label")),
                _escape(_role_label(block.get("generic_role"), block.get("domain_role"))),
                _badge_for_source(block.get("semantic_source")),
                _escape(_format_value(block.get("role_confidence"))),
                _escape(block.get("generated_role_name") or "-"),
                _escape(_meaning_for_role(block.get("generic_role"), block.get("domain_role"), block.get("generated_role_name"))),
                _escape(_preview_text(block.get("text"), 220)),
                _block_inspect_html(block),
            )
        )
    return "".join(rows)


def _semantic_overlay_table_html(semantic_overlay: List[Dict[str, object]], block_lookup: Dict[str, Dict[str, object]]) -> str:
    if not semantic_overlay:
        return '<div class="empty">No semantic overlay available.</div>'

    def _sort_key(entry: Dict[str, object]):
        block = block_lookup.get(entry.get("block_id"), {})
        return (
            entry.get("page", block.get("page", 0)),
            block.get("reading_order", 9999),
            entry.get("block_id", ""),
        )

    rows = []
    for entry in sorted(semantic_overlay, key=_sort_key):
        block = block_lookup.get(entry.get("block_id"), {})
        generated_role_name = entry.get("generated_role_name") or block.get("generated_role_name")
        meaning = _meaning_for_role(entry.get("generic_role"), entry.get("domain_role"), generated_role_name)
        source_meaning = _meaning_for_source(entry.get("semantic_source"), entry.get("semantic_fallback_reason"))
        rows.append(
            '<tr>'
            '<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
            '<td>%s</td><td>%s</td><td class="meaning-cell">%s</td><td class="text-cell">%s</td><td>%s</td>'
            '</tr>'
            % (
                _escape(entry.get("block_id")),
                _escape(_format_value(entry.get("page") or block.get("page"))),
                _escape(_role_label(entry.get("generic_role"), entry.get("domain_role"))),
                _escape(generated_role_name or "-"),
                _badge_for_source(entry.get("semantic_source")),
                _escape(_format_value(entry.get("role_confidence"))),
                _escape(entry.get("section_id") or "-"),
                _escape("%s %s" % (meaning, source_meaning if source_meaning != "-" else "")),
                _escape(_preview_text(block.get("text"), 180)),
                '<details class="inspect"><summary>Inspect</summary>%s</details>' % _json_pre(entry),
            )
        )
    table = (
        '<table class="grid-table"><thead><tr><th>Block ID</th><th>Page</th><th>Final Role</th><th>Generated Role</th><th>Source</th><th>Confidence</th><th>Section</th><th>Meaning</th><th>Text</th><th>Inspect</th></tr></thead>'
        '<tbody>%s</tbody></table>' % "".join(rows)
    )
    return '<div class="table-wrap">%s</div>' % table


def _trace_inspect_html(entry: Dict[str, object]) -> str:
    input_payload = entry.get("input_payload") or {}
    parsed = entry.get("parsed_decision") or {}
    applied = entry.get("applied_decision") or {}
    sections = [
        '<div class="inspect-section"><strong>Target Block</strong>%s</div>' % _json_pre(input_payload.get("target_block", {})),
        '<div class="inspect-section"><strong>Structural Relations</strong>%s</div>' % _json_pre(input_payload.get("structural_relations", {})),
        '<div class="inspect-section"><strong>Parsed Decision</strong>%s</div>' % _json_pre(parsed),
        '<div class="inspect-section"><strong>Applied Decision</strong>%s</div>' % _json_pre(applied),
    ]
    raw_response = entry.get("raw_response")
    if raw_response is not None:
        sections.append('<div class="inspect-section"><strong>Raw Response</strong><pre>%s</pre></div>' % _escape(raw_response))
    return '<details class="inspect"><summary>Inspect</summary>%s</details>' % "".join(sections)


def _trace_rows(trace_entries: List[Dict[str, object]]) -> str:
    rows = []
    for entry in trace_entries:
        payload = entry.get("input_payload") or {}
        target = payload.get("target_block") or {}
        parsed = entry.get("parsed_decision") or {}
        applied = entry.get("applied_decision") or {}
        generated_role_name = applied.get("generated_role_name") or parsed.get("generated_role_name")
        fallback_reason = entry.get("fallback_reason")
        result_label = _role_label(
            applied.get("generic_role") or parsed.get("generic_role"),
            applied.get("domain_role") or parsed.get("domain_role"),
        )
        result_meaning = _meaning_for_role(
            applied.get("generic_role") or parsed.get("generic_role"),
            applied.get("domain_role") or parsed.get("domain_role"),
            generated_role_name,
        )
        source_meaning = _meaning_for_source("qwen" if not fallback_reason else None, fallback_reason)
        context_summary = "label=%s | zone=%s | neighbors=%s | text=%s" % (
            target.get("canonical_label") or "-",
            ", ".join(target.get("zone_tags", [])) or "-",
            len(payload.get("local_neighbors") or []),
            _preview_text(target.get("text"), 120),
        )
        rows.append(
            '<tr>'
            '<td>%s</td><td class="text-cell">%s</td><td>%s<div class="cell-sub">generated=%s · latency=%s ms</div></td>'
            '<td class="meaning-cell">%s</td><td class="meaning-cell">%s</td><td>%s</td>'
            '</tr>'
            % (
                _escape(entry.get("block_id")),
                _escape(context_summary),
                _escape(result_label),
                _escape(generated_role_name or "-"),
                _escape(_format_value(entry.get("latency_ms"))),
                _escape((applied.get("reason") or parsed.get("reason") or "-") ),
                _escape("%s %s" % (result_meaning, source_meaning if source_meaning != "-" else "")),
                _trace_inspect_html(entry),
            )
        )
    return "".join(rows)


def _trace_table_html(trace_entries: Optional[List[Dict[str, object]]]) -> str:
    if not trace_entries:
        return '<div class="empty">No semantic trace available.</div>'
    table = (
        '<table class="grid-table"><thead><tr><th>Block ID</th><th>Input Snapshot</th><th>Result</th><th>Why It Happened</th><th>What It Means</th><th>Inspect</th></tr></thead>'
        '<tbody>%s</tbody></table>' % _trace_rows(trace_entries)
    )
    return '<div class="table-wrap">%s</div>' % table


def _raw_json_panel(title: str, payload: object, open_by_default: bool = False) -> str:
    open_attr = " open" if open_by_default else ""
    return '<details class="json-panel"%s><summary>%s</summary>%s</details>' % (
        open_attr,
        _escape(title),
        _json_pre(payload),
    )


def _raw_json_panels_html(template: Dict[str, object], canonical_pages: List[Dict[str, object]], diagnostics: Dict[str, object], semantic_overlay: List[Dict[str, object]], semantic_trace: Optional[List[Dict[str, object]]]) -> str:
    panels = [
        _raw_json_panel("reference_template.json", template),
        _raw_json_panel("canonical_pages.json", canonical_pages),
        _raw_json_panel("parser_diagnostics.json", diagnostics),
        _raw_json_panel("semantic_overlay.json", semantic_overlay),
    ]
    if semantic_trace is not None:
        panels.append(_raw_json_panel("semantic_trace.json", semantic_trace))
    return '<div class="raw-json-stack">%s</div>' % "".join(panels)


def render_reference_visualization(
    artifact_dir: str,
    output_path: Optional[str] = None,
    reference_source: Optional[str] = None,
) -> str:
    artifact_root = Path(artifact_dir)
    template = _load_json(artifact_root / "reference_template.json")
    canonical_pages = _load_json(artifact_root / "canonical_pages.json")
    diagnostics = _load_json(artifact_root / "parser_diagnostics.json")
    semantic_overlay = _load_json(artifact_root / "semantic_overlay.json")
    semantic_trace = _load_optional_json(artifact_root / "semantic_trace.json")

    block_lookup: Dict[str, Dict[str, object]] = {}
    for page in canonical_pages:
        for block in page.get("blocks", []):
            block_lookup[block.get("block_id")] = block

    rendered_reference_pages: Dict[int, Path] = {}
    if reference_source:
        rendered_reference_pages = _render_reference_pages(
            reference_source=Path(reference_source),
            output_dir=artifact_root / "reference_previews",
            page_count=len(canonical_pages),
        )

    page_sections = []
    for page in canonical_pages:
        sample_id = page.get("sample_id")
        preview_path = rendered_reference_pages.get(page.get("page")) or _preview_path(artifact_root, sample_id)
        preview_html = '<div class="preview-missing">No preview image found.</div>'
        if preview_path:
            preview_html = (
                '<div class="preview-stage"><img src="%s" alt="%s" class="preview-image"/>%s</div>'
                % (
                    _escape(_image_data_uri(preview_path)),
                    _escape(sample_id),
                    _overlay_boxes(page.get("blocks", [])),
                )
            )
        block_table = (
            '<div class="table-wrap"><table class="grid-table"><thead><tr><th>Order</th><th>Block ID</th><th>Label</th><th>Final Role</th><th>Source</th><th>Confidence</th><th>Generated Role</th><th>Meaning</th><th>Text</th><th>Inspect</th></tr></thead>'
            '<tbody>%s</tbody></table></div>' % _block_rows(page.get("blocks", []))
        )
        page_sections.append(
            '<section class="page-section">'
            '<div class="page-header"><h2>Page %s</h2><div class="page-meta">sample_id=%s · engines=%s</div></div>'
            '<div class="page-grid"><div class="preview-panel">%s</div>'
            '<div class="detail-panel">%s</div></div></section>'
            % (
                _escape(_format_value(page.get("page"))),
                _escape(sample_id),
                _escape(", ".join(page.get("source_engines", []))),
                preview_html,
                block_table,
            )
        )

    semantic = diagnostics.get("semantic", {})
    applied_source_counts = semantic.get("applied_source_counts", {}) if semantic else {}
    fallback_reasons = semantic.get("fallback_reasons", {}) if semantic else {}
    attempted_count = float(semantic.get("attempted_count") or 0) if semantic else 0.0
    block_count = float(semantic.get("block_count") or 0) if semantic else 0.0

    html_output = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>Reference Visualization</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --bg-accent: linear-gradient(180deg, #eef4ff 0%, #f7f4ea 100%);
      --panel: rgba(255, 255, 255, 0.92);
      --panel-strong: #ffffff;
      --line: #d6dce8;
      --line-strong: #c1cad9;
      --text: #162033;
      --muted: #5f6b82;
      --accent: #0f5bd8;
      --good: #0f766e;
      --warn: #b45309;
      --muted-badge: #64748b;
      --shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Segoe UI", "Noto Sans KR", sans-serif; background: var(--bg-accent); color: var(--text); }}
    .shell {{ max-width: 1760px; margin: 0 auto; padding: 28px; }}
    h1, h2, h3 {{ margin: 0; }}
    h2 {{ font-size: 22px; }}
    h3 {{ font-size: 16px; margin-bottom: 10px; }}
    p {{ margin: 0; }}
    .intro {{ margin-bottom: 24px; padding: 24px; background: rgba(255,255,255,.72); border: 1px solid rgba(255,255,255,.6); border-radius: 20px; box-shadow: var(--shadow); }}
    .intro h1 {{ margin-bottom: 8px; }}
    .intro-sub {{ color: var(--muted); line-height: 1.55; max-width: 980px; }}
    .cards {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; margin: 16px 0 24px; }}
    .card {{ background: var(--panel); backdrop-filter: blur(8px); border: 1px solid var(--line); border-radius: 16px; padding: 16px; box-shadow: var(--shadow); }}
    .card-label {{ font-size: 12px; color: var(--muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: .05em; }}
    .card-value {{ font-size: 20px; font-weight: 700; word-break: break-word; margin-bottom: 6px; }}
    .card-hint {{ color: var(--muted); font-size: 12px; line-height: 1.5; }}
    .two-col {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; margin-bottom: 24px; }}
    .three-col {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .panel {{ background: var(--panel); backdrop-filter: blur(8px); border: 1px solid var(--line); border-radius: 20px; padding: 20px; box-shadow: var(--shadow); min-width: 0; }}
    .panel-intro {{ color: var(--muted); font-size: 13px; line-height: 1.55; margin: 8px 0 14px; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid #edf1f7; border-radius: 14px; background: var(--panel-strong); }}
    .grid-table {{ width: 100%; border-collapse: collapse; font-size: 13px; min-width: 720px; }}
    .grid-table th, .grid-table td {{ border-bottom: 1px solid #e8edf5; text-align: left; padding: 10px 12px; vertical-align: top; }}
    .grid-table th {{ background: #f7f9fd; position: sticky; top: 0; z-index: 1; }}
    .text-cell {{ max-width: 320px; word-break: break-word; line-height: 1.5; }}
    .meaning-cell {{ max-width: 380px; word-break: break-word; line-height: 1.55; color: #334155; }}
    .cell-sub {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
    .page-section {{ background: var(--panel); backdrop-filter: blur(8px); border: 1px solid var(--line); border-radius: 20px; padding: 20px; margin-bottom: 20px; box-shadow: var(--shadow); }}
    .page-header {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 14px; }}
    .page-meta {{ color: var(--muted); font-size: 13px; }}
    .page-grid {{ display: grid; grid-template-columns: minmax(420px, 720px) minmax(420px, 1fr); gap: 16px; align-items: start; }}
    .preview-panel, .detail-panel {{ min-width: 0; }}
    .preview-stage {{ position: relative; width: 100%; border: 1px solid var(--line); border-radius: 14px; overflow: hidden; background: #fff; }}
    .preview-image {{ display: block; width: 100%; height: auto; }}
    .overlay-box {{ position: absolute; border: 2px solid; background: rgba(255,255,255,.06); }}
    .overlay-label {{ position: absolute; left: 0; top: 0; color: white; font-size: 10px; line-height: 1.2; padding: 2px 4px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .preview-missing, .empty {{ color: var(--muted); padding: 24px; background: #f8fafc; border-radius: 14px; border: 1px dashed var(--line-strong); }}
    .warning-list {{ margin: 0; padding-left: 18px; }}
    .warning-list li {{ margin-bottom: 10px; }}
    .list-hint {{ color: var(--muted); font-size: 12px; line-height: 1.5; margin-top: 4px; }}
    .guide-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .guide-card {{ background: #f9fbff; border: 1px solid #e3ebf7; border-radius: 16px; padding: 14px; }}
    .guide-file {{ font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; color: var(--accent); margin-bottom: 6px; }}
    .guide-title {{ font-size: 15px; font-weight: 700; margin-bottom: 6px; }}
    .guide-body {{ color: var(--muted); font-size: 13px; line-height: 1.55; }}
    .subpanel {{ background: #fbfcfe; border: 1px solid #e7edf8; border-radius: 16px; padding: 16px; min-width: 0; }}
    .badge {{ display: inline-flex; align-items: center; padding: 4px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; border: 1px solid transparent; white-space: nowrap; }}
    .badge-good {{ color: #065f46; background: #d1fae5; border-color: #a7f3d0; }}
    .badge-info {{ color: #1d4ed8; background: #dbeafe; border-color: #bfdbfe; }}
    .badge-warn {{ color: #92400e; background: #fef3c7; border-color: #fde68a; }}
    .badge-muted {{ color: #475569; background: #e2e8f0; border-color: #cbd5e1; }}
    .badge-neutral {{ color: #334155; background: #f1f5f9; border-color: #e2e8f0; }}
    details.inspect, details.json-panel {{ border: 1px solid #e7edf7; border-radius: 12px; background: #fcfdff; }}
    details.inspect summary, details.json-panel summary {{ cursor: pointer; padding: 10px 12px; font-weight: 700; color: var(--accent); }}
    details.inspect[open], details.json-panel[open] {{ box-shadow: inset 0 0 0 1px #eef3fb; }}
    .inspect-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 0 12px 12px; color: var(--muted); font-size: 12px; }}
    .inspect-section {{ padding: 0 12px 12px; }}
    .inspect-section strong {{ display: block; margin-bottom: 6px; }}
    pre {{ margin: 0; padding: 12px; overflow-x: auto; background: #0f172a; color: #e2e8f0; border-radius: 0 0 12px 12px; font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; line-height: 1.55; }}
    .raw-json-stack {{ display: grid; gap: 12px; }}
    @media (max-width: 1380px) {{
      .cards {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .three-col {{ grid-template-columns: 1fr; }}
      .page-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 900px) {{
      .shell {{ padding: 16px; }}
      .cards, .two-col, .guide-grid {{ grid-template-columns: 1fr; }}
      .inspect-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="intro">
      <h1>Reference Template Visualization</h1>
      <p class="intro-sub">`reference_template.json`, `parser_diagnostics.json`, `semantic_overlay.json`, `semantic_trace.json`를 한 화면에서 읽을 수 있게 정리한 뷰입니다. 위쪽은 요약과 해석, 아래쪽은 블록별 결과와 raw JSON 확인용입니다.</p>
      <p class="intro-sub" style="margin-top:8px;">source_path={_escape(template.get("source_path"))}</p>
    </div>

    <div class="cards">{_summary_cards(template)}</div>
    <div class="cards">{_semantic_cards(diagnostics)}</div>

    <div class="two-col">
      <section class="panel">
        <h2>JSON Reading Guide</h2>
        <p class="panel-intro">각 결과 파일이 무엇을 담고 있는지 먼저 이해하면, 아래 표와 raw JSON을 훨씬 빠르게 읽을 수 있습니다.</p>
        {_json_reading_guide_html()}
      </section>
      <section class="panel">
        <h2>Confidence Summary</h2>
        <p class="panel-intro">문서 품질과 검토 필요 여부를 요약한 값입니다. 사람이 다시 봐야 할지 판단할 때 먼저 보는 구간입니다.</p>
        {_confidence_summary_html(template)}
      </section>
    </div>

    <div class="two-col">
      <section class="panel">
        <h2>Section Order</h2>
        <p class="panel-intro">`reference_template.json` 기준으로 최종 추출된 섹션 흐름입니다.</p>
        {_section_order_html(template)}
      </section>
      <section class="panel">
        <h2>Style Tokens</h2>
        <p class="panel-intro">레이아웃과 스타일 복원에 활용할 수 있는 문서 특성 요약입니다.</p>
        {_style_tokens_html(template)}
      </section>
    </div>

    <div class="two-col">
      <section class="panel">
        <h2>Template Warnings</h2>
        <p class="panel-intro">템플릿 생성 중 품질 이슈나 보정 흔적이 있으면 여기 표시됩니다.</p>
        {_warning_list_html(template)}
      </section>
      <section class="panel">
        <h2>Page Analysis</h2>
        <p class="panel-intro">페이지 구조 분석 결과입니다. archetype, column 수, quality score가 semantic 해석에 직접 영향을 줍니다.</p>
        {_page_analysis_html(diagnostics)}
      </section>
    </div>

    <div class="two-col">
      <section class="panel">
        <h2>OCR Fusion Summary</h2>
        <p class="panel-intro">엔진 결과를 합치는 과정에서 어떤 블록이 교체/추가되었는지 보여줍니다. 텍스트가 왜 바뀌었는지 확인할 때 유용합니다.</p>
        {_fusion_html(diagnostics)}
      </section>
      <section class="panel">
        <h2>Semantic Metrics Guide</h2>
        <p class="panel-intro">semantic 집계 값이 무엇을 뜻하는지 설명합니다. 모델이 얼마나 시도했고, 얼마나 채택됐는지 읽는 기준입니다.</p>
        {_semantic_metric_table_html(diagnostics)}
      </section>
    </div>

    <div class="three-col">
      {_breakdown_table_html("Applied Source Breakdown", applied_source_counts, SEMANTIC_SOURCE_MEANINGS, block_count, "No applied source counts available.")}
      {_breakdown_table_html("Fallback Reason Breakdown", fallback_reasons, FALLBACK_REASON_MEANINGS, attempted_count, "No fallback reasons recorded.")}
      <section class="subpanel">
        <h3>Reading Tips</h3>
        <div class="guide-body">`semantic_overlay`는 최종 결과, `semantic_trace`는 그 결과가 어떻게 나왔는지 보여주는 로그입니다. 두 섹션을 함께 보면 “최종 적용값”과 “모델 판단 근거”를 연결해서 읽을 수 있습니다.</div>
        <div class="guide-body" style="margin-top:10px;">`generated_role_name`은 모델이 자유롭게 붙인 설명용 이름이고, `generic_role/domain_role`은 시스템 호환용 닫힌 집합 역할입니다.</div>
        <div class="guide-body" style="margin-top:10px;">`unknown_fallback`가 많으면 모델 실패나 규칙 미적용이 많았다는 뜻이고, `needs_review`가 많으면 사람이 다시 검토할 여지가 큰 결과입니다.</div>
      </section>
    </div>

    <section class="panel" style="margin-bottom:24px;">
      <h2>Semantic Trace Explorer</h2>
      <p class="panel-intro">`semantic_trace.json`을 읽기 쉬운 형태로 풀어놓은 표입니다. 각 블록에 대해 입력 단서, 최종 결과, 이유, 의미를 함께 볼 수 있습니다.</p>
      {_trace_table_html(semantic_trace)}
    </section>

    <section class="panel" style="margin-bottom:24px;">
      <h2>Semantic Overlay Explorer</h2>
      <p class="panel-intro">`semantic_overlay.json` 기준 최종 적용 결과입니다. 블록별 source, confidence, section 연결 상태를 빠르게 훑어볼 수 있습니다.</p>
      {_semantic_overlay_table_html(semantic_overlay, block_lookup)}
    </section>

    {''.join(page_sections)}

    <section class="panel" style="margin-bottom:24px;">
      <h2>Raw JSON Inspectors</h2>
      <p class="panel-intro">요약 화면만으로 부족할 때 원본 JSON을 그대로 펼쳐서 확인할 수 있습니다.</p>
      {_raw_json_panels_html(template, canonical_pages, diagnostics, semantic_overlay, semantic_trace)}
    </section>
  </div>
</body>
</html>"""

    output = Path(output_path) if output_path else artifact_root / "reference_visualization.html"
    output.write_text(html_output, encoding="utf-8")
    return str(output)
