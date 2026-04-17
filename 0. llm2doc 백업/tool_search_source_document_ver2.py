"""주변 문맥까지 포함해 검색 품질을 높인 고급 검색기.

이 버전은 블록 하나만 인덱싱하지 않고, 같은 앵커 블록에 대해
`block`, `window`, `section` 단위의 여러 검색 레코드를 만든다.
그 뒤 검색 결과를 다시 앵커 기준으로 묶어 재정렬해, 실제로 LLM이
활용하기 좋은 문맥 중심 결과를 돌려준다.
"""

import html
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import chromadb
import chromadb.errors
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from openai.types.responses.response_input_param import FunctionCallOutput

from .analyze_layout import LayoutAnalyzer, ParsedDocument
from .debug_trace import DecisionTracer


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PACKAGE_ROOT / "data"
ARTIFACTS_ROOT = WORKSPACE_ROOT / "artifacts"

COLLECTION_NAME = "docs_v3_contextual"
COLLECTION_BATCH_SIZE = 20
SEARCH_RESULT_LIMIT = 3
RETRIEVAL_LIMIT = 24
WINDOW_RADIUS = 1
MAX_SECTION_TEXT_CHARS = 1400
MAX_CONTEXT_TEXT_CHARS = 500

ROLE_CONFIDENCE_WEIGHT = 0.06
NEEDS_REVIEW_PENALTY = 0.03
LEXICAL_MATCH_WEIGHT = 0.18
METADATA_MATCH_WEIGHT = 0.12
MULTI_KIND_BONUS = 0.03

REGEX_NEWLINE = re.compile(r"[\r\n]+")
REGEX_PLACEHOLDER_IMAGE = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$")
REGEX_TABLE_HTML = re.compile(r"^\s*<table(?:\s|>)", re.IGNORECASE)
REGEX_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")

TITLE_ROLE_MARKERS = {
    "doc_title",
    "paragraph_title",
    "title",
    "heading",
    "header",
    "section_title",
    "subtitle",
}


@dataclass(slots=True)
class BlockContext:
    """문서 안 실제 블록의 시각적/의미적 정보를 모두 담는 기본 단위."""

    anchor_key: str
    document: str
    page: int
    order: int
    display_block_id: str
    text: str
    bbox: list[int]
    width: int
    height: int
    is_html: bool
    label: str | None
    generic_role: str | None
    domain_role: str | None
    generated_role_name: str | None
    section_purpose: str | None
    role_confidence: float
    semantic_needs_review: bool
    source_kind: str


@dataclass(slots=True)
class SearchRecord:
    """하나의 앵커 블록에서 파생된 검색용 레코드.

    같은 블록이라도 주변 문맥 범위에 따라 `record_kind`가 달라질 수 있다.
    """

    record_id: str
    anchor_key: str
    record_kind: str
    document: str
    page: int
    display_block_id: str
    embedding_text: str
    page_title: str | None
    section_title: str | None
    generic_role: str | None
    domain_role: str | None
    generated_role_name: str | None
    section_purpose: str | None
    role_confidence: float
    semantic_needs_review: bool
    source_kind: str
    anchor_text: str


@dataclass(slots=True)
class SearchAssets:
    """검색 시 필요한 여러 인덱스를 한 번에 보관하는 컨테이너."""

    records_by_id: dict[str, SearchRecord]
    blocks_by_anchor: dict[str, BlockContext]
    page_blocks: dict[tuple[str, int], list[BlockContext]]
    page_titles: dict[tuple[str, int], str | None]


def _list_source_documents(data_root: Path = DATA_ROOT) -> list[str]:
    """데이터 루트 아래의 문서 폴더 목록을 정렬해 반환한다."""
    docs = [path.name for path in data_root.iterdir() if path.is_dir()]
    docs.sort()
    return docs


# 아래 coercion/normalization 함수들은 artifact JSON의 느슨한 타입을
# 내부에서 다루기 쉬운 형태로 맞추는 역할을 한다.
def _load_json(path: Path) -> Any:
    with path.open("rt", encoding="utf-8") as f:
        return json.load(f)


def _coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _coerce_role(value: Any) -> str | None:
    text = _coerce_text(value).strip()
    if not text:
        return None
    return text


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no", ""}:
            return False
    return False


def _coerce_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0


def _coerce_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, Sequence) or len(value) < 4:
        return None

    try:
        bbox = [
            int(float(value[0])),
            int(float(value[1])),
            int(float(value[2])),
            int(float(value[3])),
        ]
    except (TypeError, ValueError):
        return None

    return bbox


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _truncate_text(text: str, limit: int) -> str:
    cleaned = _normalize_space(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _is_placeholder_block_text(text: str) -> bool:
    return bool(REGEX_PLACEHOLDER_IMAGE.match(text))


def _should_index_text(text: str) -> bool:
    return bool(text.strip()) and not _is_placeholder_block_text(text)


def _looks_like_table_html(text: str) -> bool:
    return bool(REGEX_TABLE_HTML.match(text))


def _sample_matches_doc(sample_id: str, doc: str) -> bool:
    return sample_id == doc or sample_id.startswith(f"{doc}-")


def _sample_to_doc_page_index(
    sample_id: str,
    doc: str,
    page_count: int,
    artifact_page_number: Any,
) -> int | None:
    if sample_id == doc:
        if page_count == 1:
            return 0
        if isinstance(artifact_page_number, int) and 1 <= artifact_page_number <= page_count:
            return artifact_page_number - 1
        return None

    prefix = f"{doc}-"
    if sample_id.startswith(prefix):
        suffix = sample_id[len(prefix):]
        if suffix.isdigit():
            page_index = int(suffix)
            if 0 <= page_index < page_count:
                return page_index
            return None
        if isinstance(artifact_page_number, int) and 1 <= artifact_page_number <= page_count:
            return artifact_page_number - 1

    return None


def _relative_bbox(bbox: Sequence[int], width: int, height: int) -> list[int]:
    return [
        bbox[0] * 1000 // width,
        bbox[1] * 1000 // height,
        bbox[2] * 1000 // width,
        bbox[3] * 1000 // height,
    ]


def _render_structured_html(
    block_id: str,
    bbox: Sequence[int],
    width: int,
    height: int,
    text: str,
    *,
    is_html: bool,
) -> str:
    bbox_rel = _relative_bbox(bbox, width, height)
    bbox_str = ", ".join(str(value) for value in bbox_rel)
    result = [f'<div id="{block_id}" data-bbox="[{bbox_str}]">\n']

    if is_html:
        result.append("  ")
        result.append(text)
        result.append("\n")
    else:
        for line in REGEX_NEWLINE.split(text.strip()):
            result.append("  <p>")
            result.append(html.escape(line))
            result.append("</p>\n")

    result.append("</div>")
    return "".join(result)


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in REGEX_TOKEN.findall(text) if token}


def _lexical_overlap_score(query_tokens: set[str], *texts: str | None) -> float:
    if not query_tokens:
        return 0.0

    searchable_tokens: set[str] = set()
    for text in texts:
        if text:
            searchable_tokens.update(_tokenize(text))

    if not searchable_tokens:
        return 0.0

    overlap = len(query_tokens & searchable_tokens)
    return overlap / max(1, len(query_tokens))


def _is_title_block(block: BlockContext) -> bool:
    candidate_fields = [
        block.label,
        block.generic_role,
        block.generated_role_name,
        block.section_purpose,
    ]

    for field in candidate_fields:
        if field is None:
            continue
        normalized = field.strip().lower().replace(" ", "_")
        if any(marker in normalized for marker in TITLE_ROLE_MARKERS):
            return True

    text = _normalize_space(block.text)
    if block.is_html or not text:
        return False

    if len(text) <= 48 and "\n" not in block.text and not re.search(r"[.!?]$", text):
        words = text.split(" ")
        if 1 <= len(words) <= 6 and not text.startswith("-"):
            return True

    return False


def _build_embedding_text(
    *,
    document: str,
    page_id: int,
    record_kind: str,
    anchor_text: str,
    page_title: str | None,
    section_title: str | None,
    prev_text: str | None,
    next_text: str | None,
    section_text: str | None,
    generic_role: str | None,
    domain_role: str | None,
    generated_role_name: str | None,
    section_purpose: str | None,
) -> str:
    """앵커 블록, 주변 문맥, 섹션 문맥을 합쳐 임베딩 입력 문자열을 만든다."""
    fields = [
        f"document_id: {document}",
        f"page_id: {page_id}",
        f"record_kind: {record_kind}",
        f"page_title: {page_title or 'unknown'}",
        f"section_title: {section_title or 'unknown'}",
        f"generic_role: {generic_role or 'unknown'}",
        f"domain_role: {domain_role or 'unknown'}",
        f"generated_role_name: {generated_role_name or 'unknown'}",
        f"section_purpose: {section_purpose or 'unknown'}",
        "",
        "anchor_content:",
        _truncate_text(anchor_text, MAX_CONTEXT_TEXT_CHARS),
    ]

    if prev_text:
        fields.extend(["", "previous_context:", _truncate_text(prev_text, MAX_CONTEXT_TEXT_CHARS)])
    if next_text:
        fields.extend(["", "next_context:", _truncate_text(next_text, MAX_CONTEXT_TEXT_CHARS)])
    if section_text and record_kind != "block":
        fields.extend(["", "section_context:", _truncate_text(section_text, MAX_SECTION_TEXT_CHARS)])

    return "\n".join(fields)


def _collection_metadata(record: SearchRecord) -> dict[str, Any]:
    return {
        "document": record.document,
        "page": record.page,
        "display_block_id": record.display_block_id,
        "anchor_key": record.anchor_key,
        "record_kind": record.record_kind,
        "page_title": record.page_title or "unknown",
        "section_title": record.section_title or "unknown",
        "generic_role": record.generic_role or "unknown",
        "domain_role": record.domain_role or "unknown",
        "generated_role_name": record.generated_role_name or "unknown",
        "section_purpose": record.section_purpose or "unknown",
        "role_confidence": record.role_confidence,
        "semantic_needs_review": record.semantic_needs_review,
        "source_kind": record.source_kind,
    }


# 아래 함수군은 OCR/semantic artifact를 합쳐 블록 컨텍스트를 만들고,
# 그 위에서 window/section 레코드를 파생시키는 역할을 한다.
def _load_semantic_artifact_pages(
    doc: str,
    page_count: int,
    artifacts_root: Path = ARTIFACTS_ROOT,
) -> dict[int, dict[str, Any]]:
    matched_pages: dict[int, dict[str, Any]] = {}

    if not artifacts_root.exists():
        return matched_pages

    for artifact_root in sorted(artifacts_root.iterdir(), key=lambda path: path.name):
        reference_dir = artifact_root / "01_reference"
        canonical_pages_path = reference_dir / "canonical_pages.json"
        semantic_overlay_path = reference_dir / "semantic_overlay.json"

        if not canonical_pages_path.exists() or not semantic_overlay_path.exists():
            continue

        try:
            canonical_pages = _load_json(canonical_pages_path)
            semantic_overlay = _load_json(semantic_overlay_path)
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(canonical_pages, list) or not isinstance(semantic_overlay, list):
            continue

        overlay_by_block_id = {
            _coerce_text(entry.get("block_id")): entry
            for entry in semantic_overlay
            if isinstance(entry, dict) and _coerce_text(entry.get("block_id"))
        }

        for canonical_page in canonical_pages:
            if not isinstance(canonical_page, dict):
                continue

            sample_id = _coerce_text(canonical_page.get("sample_id")).strip()
            if not _sample_matches_doc(sample_id, doc):
                continue

            page_index = _sample_to_doc_page_index(
                sample_id,
                doc,
                page_count,
                canonical_page.get("page"),
            )
            if page_index is None:
                continue

            blocks = canonical_page.get("blocks")
            width = canonical_page.get("width")
            height = canonical_page.get("height")
            if not isinstance(blocks, list) or not isinstance(width, int) or not isinstance(height, int):
                continue

            candidate = {
                "sample_id": sample_id,
                "width": width,
                "height": height,
                "blocks": blocks,
                "overlay_by_block_id": overlay_by_block_id,
            }
            current = matched_pages.get(page_index)
            if current is None or len(blocks) > len(current["blocks"]):
                matched_pages[page_index] = candidate

    return matched_pages


def _build_semantic_blocks_for_page(
    doc: str,
    page_index: int,
    artifact_page: dict[str, Any],
) -> list[BlockContext]:
    width = int(artifact_page["width"])
    height = int(artifact_page["height"])
    overlay_by_block_id = artifact_page["overlay_by_block_id"]
    blocks: list[BlockContext] = []

    for ordinal, block in enumerate(artifact_page["blocks"], start=1):
        if not isinstance(block, dict):
            continue

        text = _coerce_text(block.get("text"))
        if not _should_index_text(text):
            continue

        bbox = _coerce_bbox(block.get("bbox_px"))
        if bbox is None:
            continue

        display_block_id = _coerce_text(block.get("block_id")).strip()
        if not display_block_id:
            display_block_id = f"{doc}-page-{page_index + 1}-block-{ordinal}"

        overlay = overlay_by_block_id.get(display_block_id, {})
        generic_role = _coerce_role(
            overlay.get("generic_role") if isinstance(overlay, dict) else None
        ) or _coerce_role(block.get("generic_role"))
        domain_role = _coerce_role(
            overlay.get("domain_role") if isinstance(overlay, dict) else None
        ) or _coerce_role(block.get("domain_role"))
        generated_role_name = _coerce_role(
            overlay.get("generated_role_name") if isinstance(overlay, dict) else None
        ) or _coerce_role(block.get("generated_role_name"))
        section_purpose = _coerce_role(
            overlay.get("section_purpose") if isinstance(overlay, dict) else None
        ) or _coerce_role(block.get("section_purpose"))
        role_confidence = _coerce_float(
            overlay.get("role_confidence") if isinstance(overlay, dict) else None
        )
        if role_confidence == 0.0:
            role_confidence = _coerce_float(block.get("role_confidence"))
        semantic_needs_review = _coerce_bool(
            overlay.get("semantic_needs_review") if isinstance(overlay, dict) else None
        )
        if not semantic_needs_review:
            semantic_needs_review = _coerce_bool(block.get("semantic_needs_review"))

        anchor_key = f"{doc}:{page_index}:{display_block_id}"
        blocks.append(
            BlockContext(
                anchor_key=anchor_key,
                document=doc,
                page=page_index,
                order=ordinal,
                display_block_id=display_block_id,
                text=text,
                bbox=bbox,
                width=width,
                height=height,
                is_html=_looks_like_table_html(text),
                label=None,
                generic_role=generic_role,
                domain_role=domain_role,
                generated_role_name=generated_role_name,
                section_purpose=section_purpose,
                role_confidence=role_confidence,
                semantic_needs_review=semantic_needs_review,
                source_kind="semantic",
            )
        )

    return blocks


def _build_fallback_blocks_for_document(
    doc: str,
    parsed_doc: ParsedDocument,
    covered_pages: set[int],
) -> list[BlockContext]:
    blocks: list[BlockContext] = []

    for page_index, page in enumerate(parsed_doc.pages):
        if page_index in covered_pages:
            continue

        for block_index, block in enumerate(page.blocks, start=1):
            text = block.content or ""
            if not _should_index_text(text):
                continue

            display_block_id = f"page-{page_index + 1}-block-{block_index}"
            anchor_key = f"{doc}:{page_index}:{display_block_id}"
            blocks.append(
                BlockContext(
                    anchor_key=anchor_key,
                    document=doc,
                    page=page_index,
                    order=block_index,
                    display_block_id=display_block_id,
                    text=text,
                    bbox=list(block.bbox),
                    width=page.width,
                    height=page.height,
                    is_html=block.is_html,
                    label=block.label,
                    generic_role=None,
                    domain_role=None,
                    generated_role_name=None,
                    section_purpose=None,
                    role_confidence=0.0,
                    semantic_needs_review=False,
                    source_kind="fallback",
                )
            )

    return blocks


def _build_block_contexts_for_parsed_doc(
    doc: str,
    parsed_doc: ParsedDocument,
    artifacts_root: Path = ARTIFACTS_ROOT,
) -> list[BlockContext]:
    semantic_pages = _load_semantic_artifact_pages(
        doc,
        len(parsed_doc.pages),
        artifacts_root=artifacts_root,
    )
    covered_pages: set[int] = set()
    blocks: list[BlockContext] = []

    for page_index, artifact_page in semantic_pages.items():
        page_blocks = _build_semantic_blocks_for_page(doc, page_index, artifact_page)
        if not page_blocks:
            continue
        covered_pages.add(page_index)
        blocks.extend(page_blocks)

    blocks.extend(_build_fallback_blocks_for_document(doc, parsed_doc, covered_pages))
    return blocks


def _page_title_for_blocks(blocks: Sequence[BlockContext]) -> str | None:
    for block in blocks:
        if block.label == "doc_title":
            return _truncate_text(block.text, 120)

    for block in blocks:
        if _is_title_block(block):
            return _truncate_text(block.text, 120)

    if blocks:
        return _truncate_text(blocks[0].text, 120)

    return None


def _section_bounds(blocks: Sequence[BlockContext], index: int) -> tuple[int, int]:
    start = 0
    for current in range(index, -1, -1):
        if _is_title_block(blocks[current]):
            start = current
            break

    end = len(blocks)
    for current in range(index + 1, len(blocks)):
        if _is_title_block(blocks[current]):
            end = current
            break

    return start, end


def _section_title_for_blocks(
    blocks: Sequence[BlockContext],
    start: int,
    page_title: str | None,
) -> str | None:
    if 0 <= start < len(blocks) and _is_title_block(blocks[start]):
        return _truncate_text(blocks[start].text, 120)
    return page_title


def _section_text_for_blocks(
    blocks: Sequence[BlockContext],
    start: int,
    end: int,
) -> str:
    parts = [_normalize_space(block.text) for block in blocks[start:end] if block.text.strip()]
    return _truncate_text(" ".join(parts), MAX_SECTION_TEXT_CHARS)


def _window_text_for_index(
    blocks: Sequence[BlockContext],
    index: int,
    *,
    radius: int,
) -> tuple[str | None, str | None]:
    prev_texts: list[str] = []
    next_texts: list[str] = []

    for candidate in blocks[max(0, index - radius) : index]:
        prev_texts.append(_normalize_space(candidate.text))

    for candidate in blocks[index + 1 : index + 1 + radius]:
        next_texts.append(_normalize_space(candidate.text))

    prev_text = _truncate_text(" ".join(prev_texts), MAX_CONTEXT_TEXT_CHARS) if prev_texts else None
    next_text = _truncate_text(" ".join(next_texts), MAX_CONTEXT_TEXT_CHARS) if next_texts else None
    return prev_text, next_text


def _make_record(
    *,
    anchor: BlockContext,
    record_kind: str,
    page_title: str | None,
    section_title: str | None,
    prev_text: str | None,
    next_text: str | None,
    section_text: str | None,
) -> SearchRecord:
    return SearchRecord(
        record_id=f"{record_kind}:{anchor.anchor_key}",
        anchor_key=anchor.anchor_key,
        record_kind=record_kind,
        document=anchor.document,
        page=anchor.page,
        display_block_id=anchor.display_block_id,
        embedding_text=_build_embedding_text(
            document=anchor.document,
            page_id=anchor.page + 1,
            record_kind=record_kind,
            anchor_text=anchor.text,
            page_title=page_title,
            section_title=section_title,
            prev_text=prev_text,
            next_text=next_text,
            section_text=section_text,
            generic_role=anchor.generic_role,
            domain_role=anchor.domain_role,
            generated_role_name=anchor.generated_role_name,
            section_purpose=anchor.section_purpose,
        ),
        page_title=page_title,
        section_title=section_title,
        generic_role=anchor.generic_role,
        domain_role=anchor.domain_role,
        generated_role_name=anchor.generated_role_name,
        section_purpose=anchor.section_purpose,
        role_confidence=anchor.role_confidence,
        semantic_needs_review=anchor.semantic_needs_review,
        source_kind=anchor.source_kind,
        anchor_text=anchor.text,
    )


def _build_search_assets_for_parsed_doc(
    doc: str,
    parsed_doc: ParsedDocument,
    artifacts_root: Path = ARTIFACTS_ROOT,
) -> SearchAssets:
    block_contexts = _build_block_contexts_for_parsed_doc(
        doc,
        parsed_doc,
        artifacts_root=artifacts_root,
    )
    page_blocks: dict[tuple[str, int], list[BlockContext]] = {}
    blocks_by_anchor: dict[str, BlockContext] = {}

    for block in block_contexts:
        page_key = (block.document, block.page)
        page_blocks.setdefault(page_key, []).append(block)
        blocks_by_anchor[block.anchor_key] = block

    for blocks in page_blocks.values():
        blocks.sort(key=lambda item: item.order)

    page_titles: dict[tuple[str, int], str | None] = {
        page_key: _page_title_for_blocks(blocks)
        for page_key, blocks in page_blocks.items()
    }

    records_by_id: dict[str, SearchRecord] = {}

    for page_key, blocks in page_blocks.items():
        page_title = page_titles.get(page_key)

        for index, anchor in enumerate(blocks):
            section_start, section_end = _section_bounds(blocks, index)
            section_title = _section_title_for_blocks(blocks, section_start, page_title)
            section_text = _section_text_for_blocks(blocks, section_start, section_end)
            prev_text, next_text = _window_text_for_index(
                blocks,
                index,
                radius=WINDOW_RADIUS,
            )

            block_record = _make_record(
                anchor=anchor,
                record_kind="block",
                page_title=page_title,
                section_title=section_title,
                prev_text=None,
                next_text=None,
                section_text=None,
            )
            window_record = _make_record(
                anchor=anchor,
                record_kind="window",
                page_title=page_title,
                section_title=section_title,
                prev_text=prev_text,
                next_text=next_text,
                section_text=None,
            )
            section_record = _make_record(
                anchor=anchor,
                record_kind="section",
                page_title=page_title,
                section_title=section_title,
                prev_text=prev_text,
                next_text=next_text,
                section_text=section_text,
            )

            records_by_id[block_record.record_id] = block_record
            records_by_id[window_record.record_id] = window_record
            records_by_id[section_record.record_id] = section_record

    return SearchAssets(
        records_by_id=records_by_id,
        blocks_by_anchor=blocks_by_anchor,
        page_blocks=page_blocks,
        page_titles=page_titles,
    )


def _merge_search_assets(all_assets: Iterable[SearchAssets]) -> SearchAssets:
    merged_records: dict[str, SearchRecord] = {}
    merged_blocks: dict[str, BlockContext] = {}
    merged_pages: dict[tuple[str, int], list[BlockContext]] = {}
    merged_titles: dict[tuple[str, int], str | None] = {}

    for assets in all_assets:
        merged_records.update(assets.records_by_id)
        merged_blocks.update(assets.blocks_by_anchor)
        merged_titles.update(assets.page_titles)
        for page_key, blocks in assets.page_blocks.items():
            merged_pages[page_key] = blocks

    return SearchAssets(
        records_by_id=merged_records,
        blocks_by_anchor=merged_blocks,
        page_blocks=merged_pages,
        page_titles=merged_titles,
    )


def _build_search_assets(
    layout_analyzer: LayoutAnalyzer,
    docs: Sequence[str],
    artifacts_root: Path = ARTIFACTS_ROOT,
) -> SearchAssets:
    assets: list[SearchAssets] = []

    for doc in docs:
        parsed_doc = layout_analyzer(doc)
        assets.append(
            _build_search_assets_for_parsed_doc(
                doc,
                parsed_doc,
                artifacts_root=artifacts_root,
            )
        )

    return _merge_search_assets(assets)


def _populate_collection(
    collection: chromadb.Collection,
    records: Iterable[SearchRecord],
) -> None:
    """검색 레코드를 배치 단위로 Chroma 컬렉션에 적재한다."""
    batch_ids: list[str] = []
    batch_documents: list[str] = []
    batch_metadatas: list[dict[str, Any]] = []

    def flush() -> None:
        if not batch_ids:
            return
        collection.add(
            ids=batch_ids.copy(),
            documents=batch_documents.copy(),
            metadatas=batch_metadatas.copy(),
        )
        batch_ids.clear()
        batch_documents.clear()
        batch_metadatas.clear()

    for record in records:
        batch_ids.append(record.record_id)
        batch_documents.append(record.embedding_text)
        batch_metadatas.append(_collection_metadata(record))

        if len(batch_ids) >= COLLECTION_BATCH_SIZE:
            try:
                flush()
            except Exception as e:
                print(f"[Warning] Failed to add batch ending with {record.record_id}: {e}")
                batch_ids.clear()
                batch_documents.clear()
                batch_metadatas.clear()

    try:
        flush()
    except Exception as e:
        print(f"[Warning] Failed to add final batch: {e}")


def _record_sort_value(
    record: SearchRecord,
    *,
    distance: float,
    query_tokens: set[str],
) -> float:
    """벡터 거리, lexical overlap, 역할 메타데이터를 합친 최종 점수를 계산한다."""
    lexical_score = _lexical_overlap_score(
        query_tokens,
        record.anchor_text,
        record.page_title,
        record.section_title,
    )
    metadata_score = _lexical_overlap_score(
        query_tokens,
        record.generated_role_name,
        record.section_purpose,
        record.generic_role,
    )

    if record.record_kind == "window":
        distance -= 0.01
    elif record.record_kind == "section":
        distance -= 0.015

    return (
        distance
        - (lexical_score * LEXICAL_MATCH_WEIGHT)
        - (metadata_score * METADATA_MATCH_WEIGHT)
        - (record.role_confidence * ROLE_CONFIDENCE_WEIGHT)
        + (NEEDS_REVIEW_PENALTY if record.semantic_needs_review else 0.0)
    )


def _record_debug_metrics(
    record: SearchRecord,
    *,
    distance: float,
    query_tokens: set[str],
) -> dict[str, float]:
    lexical_score = _lexical_overlap_score(
        query_tokens,
        record.anchor_text,
        record.page_title,
        record.section_title,
    )
    metadata_score = _lexical_overlap_score(
        query_tokens,
        record.generated_role_name,
        record.section_purpose,
        record.generic_role,
    )
    final_score = _record_sort_value(
        record,
        distance=distance,
        query_tokens=query_tokens,
    )
    return {
        "lexical_score": lexical_score,
        "metadata_score": metadata_score,
        "final_score": final_score,
    }


def _rerank_records(
    query: str,
    candidates: Sequence[tuple[SearchRecord, float]],
) -> list[SearchRecord]:
    """같은 앵커에서 나온 여러 후보를 통합해 실제 반환 순서를 결정한다."""
    query_tokens = _tokenize(query)
    grouped: dict[str, dict[str, Any]] = {}

    for record, distance in candidates:
        score = _record_sort_value(record, distance=distance, query_tokens=query_tokens)
        lexical_score = _lexical_overlap_score(
            query_tokens,
            record.anchor_text,
            record.page_title,
            record.section_title,
            record.generated_role_name,
            record.section_purpose,
        )

        group = grouped.get(record.anchor_key)
        if group is None:
            grouped[record.anchor_key] = {
                "best_record": record,
                "best_score": score,
                "best_distance": distance,
                "best_lexical_score": lexical_score,
                "matched_kinds": {record.record_kind},
            }
            continue

        group["matched_kinds"].add(record.record_kind)
        if score < group["best_score"]:
            group["best_record"] = record
            group["best_score"] = score
            group["best_distance"] = distance
            group["best_lexical_score"] = lexical_score
        else:
            group["best_distance"] = min(group["best_distance"], distance)
            group["best_lexical_score"] = max(group["best_lexical_score"], lexical_score)

    ranked = sorted(
        grouped.values(),
        key=lambda item: (
            item["best_score"] - (MULTI_KIND_BONUS * max(0, len(item["matched_kinds"]) - 1)),
            item["best_distance"],
            -item["best_lexical_score"],
            item["best_record"].document,
            item["best_record"].page,
            item["best_record"].display_block_id,
        ),
    )
    return [item["best_record"] for item in ranked]


def _fallback_candidates(
    query: str,
    records: Sequence[SearchRecord],
) -> list[tuple[SearchRecord, float]]:
    """임베딩 질의가 실패할 때 로컬 lexical score로 후보를 대체한다."""
    query_tokens = _tokenize(query)
    scored: list[tuple[SearchRecord, float]] = []

    for record in records:
        lexical_score = _lexical_overlap_score(
            query_tokens,
            record.anchor_text,
            record.page_title,
            record.section_title,
        )
        metadata_score = _lexical_overlap_score(
            query_tokens,
            record.generated_role_name,
            record.section_purpose,
            record.generic_role,
        )
        pseudo_distance = max(
            0.0,
            1.0
            - lexical_score
            - (metadata_score * 0.2)
            - (record.role_confidence * ROLE_CONFIDENCE_WEIGHT)
            + (NEEDS_REVIEW_PENALTY if record.semantic_needs_review else 0.0),
        )
        scored.append((record, pseudo_distance))

    scored.sort(
        key=lambda item: (
            item[1],
            item[0].document,
            item[0].page,
            item[0].display_block_id,
            item[0].record_kind,
        )
    )
    return scored[:RETRIEVAL_LIMIT]


def _context_html(block: BlockContext) -> str:
    return _render_structured_html(
        block.display_block_id,
        block.bbox,
        block.width,
        block.height,
        block.text,
        is_html=block.is_html,
    )


def _format_search_output(
    records: Sequence[SearchRecord],
    *,
    blocks_by_anchor: dict[str, BlockContext],
    page_blocks: dict[tuple[str, int], list[BlockContext]],
    page_titles: dict[tuple[str, int], str | None],
) -> str:
    """앵커 블록과 앞뒤 문맥을 함께 포함한 결과 문자열을 만든다."""
    if not records:
        return "Search result: no matching source blocks found."

    output = ["Search result:"]

    for index, record in enumerate(records, start=1):
        anchor = blocks_by_anchor.get(record.anchor_key)
        if anchor is None:
            continue

        page_key = (record.document, record.page)
        blocks = page_blocks.get(page_key, [])
        page_title = page_titles.get(page_key) or record.page_title or "unknown"

        prev_block: BlockContext | None = None
        next_block: BlockContext | None = None

        for block_index, block in enumerate(blocks):
            if block.anchor_key != record.anchor_key:
                continue
            if 0 < block_index:
                prev_block = blocks[block_index - 1]
            if block_index + 1 < len(blocks):
                next_block = blocks[block_index + 1]
            break

        output.append(
            "Match #{idx}: document_id={doc}, page_id={page}, block_id={block}, "
            "matched_via={record_kind}, page_title={page_title}, section_title={section_title}, "
            "generic_role={generic_role}, generated_role_name={role_name}, section_purpose={purpose}".format(
                idx=index,
                doc=record.document,
                page=record.page + 1,
                block=record.display_block_id,
                record_kind=record.record_kind,
                page_title=page_title,
                section_title=record.section_title or "unknown",
                generic_role=record.generic_role or "unknown",
                role_name=record.generated_role_name or "unknown",
                purpose=record.section_purpose or "unknown",
            )
        )
        output.append("[Anchor block]")
        output.append(_context_html(anchor))

        if prev_block is not None:
            output.append("[Previous context]")
            output.append(_context_html(prev_block))

        if next_block is not None:
            output.append("[Next context]")
            output.append(_context_html(next_block))

        output.append("")

    return "\n".join(output)


class ToolSearchSourceDocumentVer2:
    def __init__(self, docs: list[str], tracer: DecisionTracer | None = None):
        """컨텍스트 검색용 컬렉션과 메모리 인덱스를 준비한다."""
        super().__init__()

        self.docs = docs
        self.records_by_id: dict[str, SearchRecord] = {}
        self.blocks_by_anchor: dict[str, BlockContext] = {}
        self.page_blocks: dict[tuple[str, int], list[BlockContext]] = {}
        self.page_titles: dict[tuple[str, int], str | None] = {}
        self.tracer = tracer or DecisionTracer(enabled=False)

        self.description = {
            "type": "function",
            "name": "search_source_document",
            "description": (
                "Search source document with contextual retrieval. "
                "Returns top-3 matching source blocks with neighboring context."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The query for the document in form of question in natural language.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        }

        embedding_function: Any = OpenAIEmbeddingFunction(
            api_key=os.environ["OPENAI_EMBED_API_KEY"],
            api_base=os.environ["OPENAI_EMBED_BASE_URL"],
            model_name=os.environ["OPENAI_EMBED_MODEL"],
        )

        layout_analyzer = LayoutAnalyzer(data_root=DATA_ROOT)
        all_docs = _list_source_documents(DATA_ROOT)

        self.chroma = chromadb.RustClient(path="debug_chromadb_cache_ver2")
        try:
            self.collection = self.chroma.get_collection(
                name=COLLECTION_NAME,
                embedding_function=embedding_function,
            )
            assets = _build_search_assets(layout_analyzer, self.docs, artifacts_root=ARTIFACTS_ROOT)
        except chromadb.errors.NotFoundError:
            self.collection = self.chroma.create_collection(
                name=COLLECTION_NAME,
                embedding_function=embedding_function,
            )
            all_assets = _build_search_assets(layout_analyzer, all_docs, artifacts_root=ARTIFACTS_ROOT)
            _populate_collection(self.collection, all_assets.records_by_id.values())
            assets = SearchAssets(
                records_by_id={
                    record_id: record
                    for record_id, record in all_assets.records_by_id.items()
                    if record.document in self.docs
                },
                blocks_by_anchor={
                    anchor_key: block
                    for anchor_key, block in all_assets.blocks_by_anchor.items()
                    if block.document in self.docs
                },
                page_blocks={
                    page_key: blocks
                    for page_key, blocks in all_assets.page_blocks.items()
                    if page_key[0] in self.docs
                },
                page_titles={
                    page_key: title
                    for page_key, title in all_assets.page_titles.items()
                    if page_key[0] in self.docs
                },
            )
        finally:
            layout_analyzer.dispose()
            del layout_analyzer

        self.records_by_id = assets.records_by_id
        self.blocks_by_anchor = assets.blocks_by_anchor
        self.page_blocks = assets.page_blocks
        self.page_titles = assets.page_titles

    def invoke(self, param: str, call_id: str) -> FunctionCallOutput:
        """OpenAI function-call 인터페이스를 일반 검색 함수로 연결한다."""
        param_parsed = json.loads(param)
        query: str = param_parsed["query"]

        output = self.invoke_raw(query)
        return {"type": "function_call_output", "output": output, "call_id": call_id}

    def invoke_raw(self, query: str) -> str:
        """질의를 실행하고 문맥 중심으로 재정렬된 결과를 반환한다."""
        if 1 < len(self.docs):
            where_cond: Any = {"$or": [{"document": x} for x in self.docs]}
        elif 0 < len(self.docs):
            where_cond = {"document": self.docs[0]}
        else:
            raise ValueError("document list is empty")

        print(f"[search_source_document_ver2] {query}")

        retrieval_mode = "semantic"
        fallback_error: str | None = None
        candidates: list[tuple[SearchRecord, float]] = []

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=RETRIEVAL_LIMIT,
                where=where_cond,
                include=["metadatas", "distances"],
            )

            result_ids = results.get("ids") or [[]]
            distances = results.get("distances") or [[]]
            for record_id, distance in zip(result_ids[0], distances[0]):
                record = self.records_by_id.get(record_id)
                if record is None:
                    continue
                candidates.append((record, float(distance)))
        except Exception as exc:
            retrieval_mode = "fallback"
            fallback_error = f"{type(exc).__name__}: {exc}"
            self.tracer.event(
                "search.contextual_ver2",
                "query_fallback",
                {"query": query, "error": fallback_error},
            )

        if not candidates:
            retrieval_mode = "fallback"
            if fallback_error is None:
                fallback_error = "semantic query returned no candidates"
            candidates = _fallback_candidates(query, list(self.records_by_id.values()))

        if not candidates:
            self.tracer.append_jsonl(
                "search/contextual_ver2.jsonl",
                {
                    "query": query,
                    "docs": self.docs,
                    "retrieval_mode": retrieval_mode,
                    "fallback_error": fallback_error,
                    "retrieved_candidates": [],
                    "grouped_anchors": [],
                    "selected": [],
                },
            )
            return _format_search_output(
                [],
                blocks_by_anchor=self.blocks_by_anchor,
                page_blocks=self.page_blocks,
                page_titles=self.page_titles,
            )

        query_tokens = _tokenize(query)
        ranked_records = _rerank_records(query, candidates)[:SEARCH_RESULT_LIMIT]
        selected_ids = {record.record_id for record in ranked_records}

        retrieved_candidates = []
        grouped_debug: dict[str, dict[str, Any]] = {}
        for record, distance in candidates:
            metrics = _record_debug_metrics(
                record,
                distance=float(distance),
                query_tokens=query_tokens,
            )
            retrieved_candidates.append(
                {
                    "record_id": record.record_id,
                    "anchor_key": record.anchor_key,
                    "record_kind": record.record_kind,
                    "document": record.document,
                    "page": record.page + 1,
                    "display_block_id": record.display_block_id,
                    "distance": float(distance),
                    "lexical_score": metrics["lexical_score"],
                    "metadata_score": metrics["metadata_score"],
                    "role_confidence": record.role_confidence,
                    "multi_kind_count": 0,
                    "final_score": metrics["final_score"],
                    "selected": record.record_id in selected_ids,
                }
            )

            group = grouped_debug.get(record.anchor_key)
            if group is None:
                grouped_debug[record.anchor_key] = {
                    "anchor_key": record.anchor_key,
                    "best_record": {
                        "record_id": record.record_id,
                        "record_kind": record.record_kind,
                        "display_block_id": record.display_block_id,
                    },
                    "matched_kinds": {record.record_kind},
                    "best_distance": float(distance),
                    "best_score": metrics["final_score"],
                    "selected": False,
                }
                continue

            group["matched_kinds"].add(record.record_kind)
            if metrics["final_score"] < group["best_score"]:
                group["best_score"] = metrics["final_score"]
                group["best_distance"] = float(distance)
                group["best_record"] = {
                    "record_id": record.record_id,
                    "record_kind": record.record_kind,
                    "display_block_id": record.display_block_id,
                }
            else:
                group["best_distance"] = min(group["best_distance"], float(distance))

        selected_anchor_keys = {record.anchor_key for record in ranked_records}
        grouped_anchors = []
        for anchor_key, payload in grouped_debug.items():
            matched_kinds = sorted(payload["matched_kinds"])
            grouped_anchors.append(
                {
                    "anchor_key": anchor_key,
                    "best_record": payload["best_record"],
                    "matched_kinds": matched_kinds,
                    "best_distance": payload["best_distance"],
                    "multi_kind_count": len(matched_kinds),
                    "final_score": payload["best_score"],
                    "selected": anchor_key in selected_anchor_keys,
                }
            )

        for entry in retrieved_candidates:
            entry["multi_kind_count"] = len(
                next(
                    (
                        group["matched_kinds"]
                        for key, group in grouped_debug.items()
                        if key == entry["anchor_key"]
                    ),
                    set(),
                )
            )

        selected_payload = [
            {
                "record_id": record.record_id,
                "anchor_key": record.anchor_key,
                "record_kind": record.record_kind,
                "document": record.document,
                "page": record.page + 1,
                "display_block_id": record.display_block_id,
            }
            for record in ranked_records
        ]
        self.tracer.append_jsonl(
            "search/contextual_ver2.jsonl",
            {
                "query": query,
                "docs": self.docs,
                "retrieval_mode": retrieval_mode,
                "fallback_error": fallback_error,
                "retrieved_candidates": retrieved_candidates,
                "grouped_anchors": grouped_anchors,
                "selected": selected_payload,
            },
        )
        self.tracer.event(
            "search.contextual_ver2",
            "search_selected",
            {
                "query": query,
                "retrieval_mode": retrieval_mode,
                "selected": selected_payload,
            },
        )
        return _format_search_output(
            ranked_records,
            blocks_by_anchor=self.blocks_by_anchor,
            page_blocks=self.page_blocks,
            page_titles=self.page_titles,
        )


def main():
    from dotenv import load_dotenv

    load_dotenv()
    tool = ToolSearchSourceDocumentVer2(["financial2"])
    print(tool.invoke_raw("What is KMX?"))


if __name__ == "__main__":
    main()
