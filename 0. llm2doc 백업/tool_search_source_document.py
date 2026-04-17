"""semantic overlay 기반의 원본 문서 검색 도구.

이 버전은 단순 텍스트 블록만 쓰지 않고, 외부 artifact에 저장된 역할 정보
(`generic_role`, `section_purpose` 등)를 함께 인덱싱한다. 따라서 질의와
텍스트 내용뿐 아니라 문서 구조적 역할까지 반영한 검색이 가능하다.
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

COLLECTION_NAME = "docs_v2_semantic"
COLLECTION_BATCH_SIZE = 20
SEARCH_RESULT_LIMIT = 3
RETRIEVAL_LIMIT = 12

ROLE_CONFIDENCE_WEIGHT = 0.05
NEEDS_REVIEW_PENALTY = 0.02

REGEX_NEWLINE = re.compile(r"[\r\n]+")
REGEX_PLACEHOLDER_IMAGE = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$")
REGEX_TABLE_HTML = re.compile(r"^\s*<table(?:\s|>)", re.IGNORECASE)
REGEX_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")


@dataclass(slots=True)
class SearchRecord:
    """Chroma에 적재되는 단일 검색 레코드.

    같은 블록이라도 검색용 텍스트와 실제 표시용 HTML은 목적이 다르므로
    둘을 분리해 저장한다.
    """

    record_id: str
    document: str
    page: int
    display_block_id: str
    embedding_text: str
    display_html: str
    generic_role: str | None
    domain_role: str | None
    generated_role_name: str | None
    section_purpose: str | None
    role_confidence: float
    semantic_needs_review: bool
    source_kind: str


def _list_source_documents(data_root: Path = DATA_ROOT) -> list[str]:
    """데이터 루트 아래의 문서 폴더 목록을 정렬해 반환한다."""
    docs = [path.name for path in data_root.iterdir() if path.is_dir()]
    docs.sort()
    return docs


def _load_json(path: Path) -> Any:
    """UTF-8 JSON 파일을 읽어 파이썬 객체로 반환한다."""
    with path.open("rt", encoding="utf-8") as f:
        return json.load(f)


# 아래 coercion 계열 함수들은 artifact JSON처럼 타입이 불안정한 입력을
# 안전한 내부 표현으로 정규화하는 역할을 맡는다.
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
        bbox = [int(float(value[0])), int(float(value[1])), int(float(value[2])), int(float(value[3]))]
    except (TypeError, ValueError):
        return None

    return bbox


def _is_placeholder_block_text(text: str) -> bool:
    return bool(REGEX_PLACEHOLDER_IMAGE.match(text))


def _should_index_text(text: str) -> bool:
    return bool(text.strip()) and not _is_placeholder_block_text(text)


def _looks_like_table_html(text: str) -> bool:
    return bool(REGEX_TABLE_HTML.match(text))


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


def _build_embedding_text(
    document: str,
    page_id: int,
    content: str,
    generic_role: str | None,
    domain_role: str | None,
    generated_role_name: str | None,
    section_purpose: str | None,
) -> str:
    """벡터 검색용 텍스트를 구성한다.

    실제 문서 내용뿐 아니라 페이지 번호와 역할 메타데이터도 함께 넣어
    의미 검색이 단순 문자열 유사도보다 풍부한 단서를 활용하게 한다.
    """
    return "\n".join(
        [
            f"document_id: {document}",
            f"page_id: {page_id}",
            f"generic_role: {generic_role or 'unknown'}",
            f"domain_role: {domain_role or 'unknown'}",
            f"generated_role_name: {generated_role_name or 'unknown'}",
            f"section_purpose: {section_purpose or 'unknown'}",
            "",
            "content:",
            content,
        ]
    )


def _collection_metadata(record: SearchRecord) -> dict[str, Any]:
    return {
        "document": record.document,
        "page": record.page,
        "display_block_id": record.display_block_id,
        "generic_role": record.generic_role or "unknown",
        "domain_role": record.domain_role or "unknown",
        "generated_role_name": record.generated_role_name or "unknown",
        "section_purpose": record.section_purpose or "unknown",
        "role_confidence": record.role_confidence,
        "semantic_needs_review": record.semantic_needs_review,
        "source_kind": record.source_kind,
    }


# semantic artifact가 존재하면 더 풍부한 블록 정보를 쓰고,
# 없으면 OCR 원본 블록을 fallback으로 사용한다.
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


def _build_semantic_records_for_page(
    doc: str,
    page_index: int,
    artifact_page: dict[str, Any],
) -> list[SearchRecord]:
    width = int(artifact_page["width"])
    height = int(artifact_page["height"])
    overlay_by_block_id = artifact_page["overlay_by_block_id"]
    records: list[SearchRecord] = []

    for ordinal, block in enumerate(artifact_page["blocks"], start=1):
        if not isinstance(block, dict):
            continue

        text = _coerce_text(block.get("text"))
        if not _should_index_text(text):
            continue

        bbox = _coerce_bbox(block.get("bbox_px"))
        if bbox is None:
            continue

        display_block_id = _coerce_text(block.get("block_id")).strip() or f"{doc}-page-{page_index + 1}-block-{ordinal}"
        overlay = overlay_by_block_id.get(display_block_id, {})

        generic_role = _coerce_role(overlay.get("generic_role") if isinstance(overlay, dict) else None) or _coerce_role(block.get("generic_role"))
        domain_role = _coerce_role(overlay.get("domain_role") if isinstance(overlay, dict) else None) or _coerce_role(block.get("domain_role"))
        generated_role_name = _coerce_role(overlay.get("generated_role_name") if isinstance(overlay, dict) else None) or _coerce_role(block.get("generated_role_name"))
        section_purpose = _coerce_role(overlay.get("section_purpose") if isinstance(overlay, dict) else None) or _coerce_role(block.get("section_purpose"))
        role_confidence = _coerce_float(overlay.get("role_confidence") if isinstance(overlay, dict) else None)
        if role_confidence == 0.0:
            role_confidence = _coerce_float(block.get("role_confidence"))
        semantic_needs_review = _coerce_bool(overlay.get("semantic_needs_review") if isinstance(overlay, dict) else None)
        if not semantic_needs_review:
            semantic_needs_review = _coerce_bool(block.get("semantic_needs_review"))

        records.append(
            SearchRecord(
                record_id=f"semantic:{doc}:{display_block_id}",
                document=doc,
                page=page_index,
                display_block_id=display_block_id,
                embedding_text=_build_embedding_text(
                    document=doc,
                    page_id=page_index + 1,
                    content=text,
                    generic_role=generic_role,
                    domain_role=domain_role,
                    generated_role_name=generated_role_name,
                    section_purpose=section_purpose,
                ),
                display_html=_render_structured_html(
                    display_block_id,
                    bbox,
                    width,
                    height,
                    text,
                    is_html=_looks_like_table_html(text),
                ),
                generic_role=generic_role,
                domain_role=domain_role,
                generated_role_name=generated_role_name,
                section_purpose=section_purpose,
                role_confidence=role_confidence,
                semantic_needs_review=semantic_needs_review,
                source_kind="semantic",
            )
        )

    return records


def _build_fallback_records_for_document(
    doc: str,
    parsed_doc: ParsedDocument,
    covered_pages: set[int],
) -> list[SearchRecord]:
    records: list[SearchRecord] = []

    for page_index, page in enumerate(parsed_doc.pages):
        if page_index in covered_pages:
            continue

        for block_index, block in enumerate(page.blocks, start=1):
            text = block.content or ""
            if not _should_index_text(text):
                continue

            display_block_id = f"page-{page_index + 1}-block-{block_index}"
            records.append(
                SearchRecord(
                    record_id=f"fallback:{doc}:{page_index + 1}:{block_index}",
                    document=doc,
                    page=page_index,
                    display_block_id=display_block_id,
                    embedding_text=_build_embedding_text(
                        document=doc,
                        page_id=page_index + 1,
                        content=text,
                        generic_role=None,
                        domain_role=None,
                        generated_role_name=None,
                        section_purpose=None,
                    ),
                    display_html=_render_structured_html(
                        display_block_id,
                        block.bbox,
                        page.width,
                        page.height,
                        text,
                        is_html=block.is_html,
                    ),
                    generic_role=None,
                    domain_role=None,
                    generated_role_name=None,
                    section_purpose=None,
                    role_confidence=0.0,
                    semantic_needs_review=False,
                    source_kind="fallback",
                )
            )

    return records


def _build_search_records_for_parsed_doc(
    doc: str,
    parsed_doc: ParsedDocument,
    artifacts_root: Path = ARTIFACTS_ROOT,
) -> dict[str, SearchRecord]:
    records: dict[str, SearchRecord] = {}
    semantic_pages = _load_semantic_artifact_pages(doc, len(parsed_doc.pages), artifacts_root=artifacts_root)
    covered_pages: set[int] = set()

    for page_index, artifact_page in semantic_pages.items():
        page_records = _build_semantic_records_for_page(doc, page_index, artifact_page)
        if not page_records:
            continue
        covered_pages.add(page_index)
        for record in page_records:
            records[record.record_id] = record

    for record in _build_fallback_records_for_document(doc, parsed_doc, covered_pages):
        records[record.record_id] = record

    return records


def _build_search_records(
    layout_analyzer: LayoutAnalyzer,
    docs: Sequence[str],
    artifacts_root: Path = ARTIFACTS_ROOT,
) -> dict[str, SearchRecord]:
    records: dict[str, SearchRecord] = {}

    for doc in docs:
        parsed_doc = layout_analyzer(doc)
        records.update(_build_search_records_for_parsed_doc(doc, parsed_doc, artifacts_root=artifacts_root))

    return records


def _populate_collection(
    collection: chromadb.Collection,
    records: Iterable[SearchRecord],
) -> None:
    """검색 레코드를 Chroma 컬렉션에 적재한다."""
    for record in records:
        try:
            collection.add(
                ids=[record.record_id],
                documents=[record.embedding_text],
                metadatas=[_collection_metadata(record)],
            )
        except Exception as e:
            print(f"[Warning] Failed to add record {record.record_id}: {e}")
            print(f"Content preview (first 100 chars): {record.embedding_text[:100]}")


def _record_rerank_score(record: SearchRecord, distance: float) -> float:
    return (
        distance
        - (record.role_confidence * ROLE_CONFIDENCE_WEIGHT)
        + (NEEDS_REVIEW_PENALTY if record.semantic_needs_review else 0.0)
    )


def _rerank_records(
    candidates: Sequence[tuple[SearchRecord, float]],
) -> list[SearchRecord]:
    """벡터 거리와 역할 신뢰도를 함께 고려해 최종 순위를 조정한다."""
    ranked = sorted(
        candidates,
        key=lambda item: (
            _record_rerank_score(item[0], item[1]),
            item[1],
            item[0].document,
            item[0].page,
            item[0].display_block_id,
        ),
    )
    return [record for record, _ in ranked]


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
            record.embedding_text,
            record.generated_role_name,
            record.section_purpose,
            record.generic_role,
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
            - (metadata_score * 0.15)
            - (record.role_confidence * 0.05),
        )
        scored.append((record, pseudo_distance))

    scored.sort(
        key=lambda item: (
            item[1],
            item[0].document,
            item[0].page,
            item[0].display_block_id,
        )
    )
    return scored[:RETRIEVAL_LIMIT]


def _format_search_output(records: Sequence[SearchRecord]) -> str:
    """LLM이 바로 읽을 수 있는 텍스트 형태로 검색 결과를 직렬화한다."""
    if not records:
        return "Search result: no matching source blocks found."

    output = ["Search result:"]
    for index, record in enumerate(records, start=1):
        output.append(
            "Match #{idx}: document_id={doc}, page_id={page}, block_id={block}, "
            "generic_role={generic_role}, generated_role_name={role_name}, section_purpose={purpose}".format(
                idx=index,
                doc=record.document,
                page=record.page + 1,
                block=record.display_block_id,
                generic_role=record.generic_role or "unknown",
                role_name=record.generated_role_name or "unknown",
                purpose=record.section_purpose or "unknown",
            )
        )
        output.append(record.display_html)
        output.append("")

    return "\n".join(output)


class ToolSearchSourceDocument:
    def __init__(self, docs: list[str], tracer: DecisionTracer | None = None):
        """컬렉션을 로드하거나 생성하고, 현재 검색 대상 문서의 레코드를 준비한다."""
        super().__init__()

        self.docs = docs
        self.records_by_id: dict[str, SearchRecord] = {}
        self.tracer = tracer or DecisionTracer(enabled=False)

        self.description = {
            "type": "function",
            "name": "search_source_document",
            "description": "Search source document. Returns top-3 matching pages among all source documents.",
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

        self.chroma = chromadb.RustClient(path="debug_chromadb_cache")
        try:
            self.collection = self.chroma.get_collection(
                name=COLLECTION_NAME,
                embedding_function=embedding_function,
            )
            self.records_by_id = _build_search_records(layout_analyzer, self.docs, artifacts_root=ARTIFACTS_ROOT)
        except chromadb.errors.NotFoundError:
            self.collection = self.chroma.create_collection(
                name=COLLECTION_NAME,
                embedding_function=embedding_function,
            )
            all_records = _build_search_records(layout_analyzer, all_docs, artifacts_root=ARTIFACTS_ROOT)
            _populate_collection(self.collection, all_records.values())
            self.records_by_id = {
                record_id: record
                for record_id, record in all_records.items()
                if record.document in self.docs
            }
        finally:
            layout_analyzer.dispose()
            del layout_analyzer

    def invoke(self, param: str, call_id: str) -> FunctionCallOutput:
        """OpenAI function-call 인터페이스를 일반 검색 함수로 연결한다."""
        param_parsed = json.loads(param)
        query: str = param_parsed["query"]

        output = self.invoke_raw(query)
        return {"type": "function_call_output", "output": output, "call_id": call_id}

    def invoke_raw(self, query: str) -> str:
        """질의를 실행하고 재정렬된 상위 결과 3개를 반환한다."""
        if 1 < len(self.docs):
            where_cond: Any = {"$or": [{"document": x} for x in self.docs]}
        elif 0 < len(self.docs):
            where_cond = {"document": self.docs[0]}
        else:
            raise ValueError("document list is empty")

        print(f"[search_source_document] {query}")

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
                "search.semantic",
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
                "search/semantic.jsonl",
                {
                    "query": query,
                    "docs": self.docs,
                    "retrieval_mode": retrieval_mode,
                    "fallback_error": fallback_error,
                    "candidates": [],
                    "selected": [],
                },
            )
            return _format_search_output([])

        ranked_records = _rerank_records(candidates)[:SEARCH_RESULT_LIMIT]
        selected_ids = {record.record_id for record in ranked_records}
        candidate_payload = [
            {
                "record_id": record.record_id,
                "document": record.document,
                "page": record.page + 1,
                "display_block_id": record.display_block_id,
                "distance": float(distance),
                "generic_role": record.generic_role,
                "generated_role_name": record.generated_role_name,
                "section_purpose": record.section_purpose,
                "role_confidence": record.role_confidence,
                "semantic_needs_review": record.semantic_needs_review,
                "rerank_score": _record_rerank_score(record, float(distance)),
                "selected": record.record_id in selected_ids,
            }
            for record, distance in candidates
        ]
        selected_payload = [
            {
                "record_id": record.record_id,
                "document": record.document,
                "page": record.page + 1,
                "display_block_id": record.display_block_id,
            }
            for record in ranked_records
        ]
        self.tracer.append_jsonl(
            "search/semantic.jsonl",
            {
                "query": query,
                "docs": self.docs,
                "retrieval_mode": retrieval_mode,
                "fallback_error": fallback_error,
                "candidates": candidate_payload,
                "selected": selected_payload,
            },
        )
        self.tracer.event(
            "search.semantic",
            "search_selected",
            {
                "query": query,
                "retrieval_mode": retrieval_mode,
                "selected": selected_payload,
            },
        )
        return _format_search_output(ranked_records)


def main():
    from dotenv import load_dotenv
    load_dotenv()
    
    tool = ToolSearchSourceDocument(["financial2"])
    print(tool.invoke_raw("What is KMX?"))


if __name__ == "__main__":
    main()
