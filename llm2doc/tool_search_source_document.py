"""semantic overlay 기반의 원본 문서 검색 도구.

이 버전은 단순 텍스트 블록만 쓰지 않고, 외부 artifact에 저장된 역할 정보
(`generic_role`, `section_purpose` 등)를 함께 인덱싱한다. 따라서 질의와
텍스트 내용뿐 아니라 문서 구조적 역할까지 반영한 검색이 가능하다.
"""

import json
import os
import re
import asyncio
import chromadb
import chromadb.errors

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from openai import AsyncOpenAI

from llm2doc.artifact.ocr import OCRArtifact
from llm2doc.artifact.semantic import SemanticArtifact
from llm2doc.bm25_search import BM25Document, BM25SearchClient, LocalBM25SearchClient
from llm2doc.context.write import WriteContext
from llm2doc.debug_trace import GenerationTracer


COLLECTION_NAME = "docs_v2_semantic"
COLLECTION_BATCH_SIZE = 20
RETRIEVAL_LIMIT = 12
FIRST_STAGE_LIMIT = 12
TOOL_DISPLAY_LIMIT = 12

ROLE_CONFIDENCE_WEIGHT = 0.05
NEEDS_REVIEW_PENALTY = 0.02

REGEX_NEWLINE = re.compile(r"[\r\n]+")
REGEX_PLACEHOLDER_IMAGE = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$")
REGEX_TABLE_HTML = re.compile(r"^\s*<table(?:\s|>)", re.IGNORECASE)
REGEX_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
REGEX_UPPER_ENTITY = re.compile(r"\b[A-Z][A-Z0-9&.\-/]{1,20}\b")
REGEX_NUMERIC_CODE = re.compile(r"\b\d{4,8}\b")
REGEX_NUMBER_WITH_UNIT = re.compile(
    r"\b\d[\d,]*(?:\.\d+)?(?:%|원|달러|만원|억원|천원|십억원|백만원|조원)\b",
    re.IGNORECASE,
)
REGEX_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
REGEX_HTML_TAG = re.compile(r"<[^>]+>")

SEMANTIC_QUERY_TOP_K = 6
SEMANTIC_QUERY_LIMIT = 3
BM25_QUERY_TOP_K = 8
ENTITY_GROUNDING_LIMIT = 6

QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "document",
    "documents",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "please",
    "query",
    "source",
    "the",
    "to",
    "with",
    "기반",
    "기반으로",
    "내용",
    "대한",
    "문서",
    "문서를",
    "분석해줘",
    "설명",
    "설명해줘",
    "요청",
    "작성",
    "작성해줘",
    "정보",
    "정리",
    "정리해줘",
    "질문",
    "찾아줘",
    "쿼리",
    "해줘",
}

PROMPT_QUERY_EXPANSION = """
You generate retrieval queries for a document search system.

Output only a single JSON object. Do not use markdown fences.
Use exactly these top-level keys:
- entities: array of strings
- semantic_queries: array of strings
- lexical_queries: array of strings

Rules:
- Preserve the original meaning of the user query.
- Do not invent new entities that are not implied by the query.
- Keep semantic_queries to at most 2 short natural-language queries.
- Keep lexical_queries to at most 1 keyword-dense query.
- If you are unsure, return empty arrays instead of guessing.

User query:
{query}

Source documents:
{source_documents}
""".strip()


@dataclass(slots=True)
class SearchRecord:
    """Chroma에 적재되는 단일 검색 레코드.

    같은 블록이라도 검색용 텍스트와 실제 표시용 HTML은 목적이 다르므로
    둘을 분리해 저장한다.
    """

    record_id: str
    doc_id: int
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


@dataclass(slots=True)
class QueryProfile:
    raw_query: str
    normalized_query: str
    query_tokens: list[str]
    entity_candidates: list[str]
    grounded_entities: list[str]
    semantic_queries: list[str]
    lexical_queries: list[str]


@dataclass(slots=True)
class RetrievalCandidate:
    record: SearchRecord
    channels: set[str]
    semantic_distance: float | None = None
    bm25_score: float | None = None
    entity_score: float = 0.0
    matched_terms: list[str] | None = None
    first_stage_score: float = 0.0

    @property
    def is_entity_only(self) -> bool:
        return self.channels == {"entity"}


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


def _normalize_query_text(query: str) -> str:
    return " ".join(query.strip().split())


def _extract_query_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in REGEX_TOKEN.findall(query):
        lowered = token.lower()
        if len(lowered) < 2:
            continue
        if lowered in QUERY_STOPWORDS:
            continue
        if lowered not in seen:
            seen.add(lowered)
            tokens.append(lowered)
    return tokens


def _extract_entity_candidates(query: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for regex in (REGEX_UPPER_ENTITY, REGEX_NUMERIC_CODE, REGEX_NUMBER_WITH_UNIT):
        for match in regex.findall(query):
            candidate = match.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)

    return candidates


def _build_fallback_lexical_query(query_tokens: Sequence[str], entity_candidates: Sequence[str]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for item in list(entity_candidates) + list(query_tokens):
        normalized = item.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        parts.append(normalized)
    return " ".join(parts)


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _coerce_text(item).strip()
        if text:
            result.append(text)
    return result


def _extract_response_text(response: Any) -> str:
    try:
        parts: list[str] = []
        if hasattr(response, "output") and isinstance(response.output, list):
            for item in response.output:
                if getattr(item, "type", "") != "message":
                    continue
                for content in getattr(item, "content", []) or []:
                    if getattr(content, "type", "") == "output_text" and getattr(content, "text", None):
                        parts.append(content.text)
        text = "".join(parts).strip()
        if text:
            return text
    except Exception:
        pass
    return _coerce_text(getattr(response, "output_text", "")).strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    fence_match = REGEX_JSON_FENCE.fullmatch(stripped)
    if fence_match is not None:
        stripped = fence_match.group(1).strip()

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            parsed, end_index = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if index + end_index == len(stripped) and isinstance(parsed, dict):
            return parsed
    return None


def _response_to_jsonable(response: Any) -> Any:
    try:
        return json.loads(response.model_dump_json())
    except Exception:
        return {"output_text": _extract_response_text(response)}


def _normalize_query_expansion_payload(payload: dict[str, Any] | None) -> dict[str, list[str]]:
    payload = payload or {}
    entities = _coerce_str_list(payload.get("entities"))
    semantic_queries = _coerce_str_list(payload.get("semantic_queries"))[:2]
    lexical_queries = _coerce_str_list(payload.get("lexical_queries"))[:1]
    return {
        "entities": entities,
        "semantic_queries": semantic_queries,
        "lexical_queries": lexical_queries,
    }


def _build_bm25_documents(records: Sequence[SearchRecord]) -> list[BM25Document]:
    documents: list[BM25Document] = []
    for record in records:
        lexical_text = "\n".join(
            [
                record.embedding_text,
                record.generated_role_name or "",
                record.section_purpose or "",
                record.generic_role or "",
            ]
        )
        documents.append(
            BM25Document(
                record_id=record.record_id,
                document_id=str(record.doc_id),
                page_id=record.page + 1,
                block_id=record.display_block_id,
                text=lexical_text,
            )
        )
    return documents


def _semantic_proximity(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return max(0.0, 1.0 - min(distance, 1.5))


def _bm25_signal(score: float | None, *, max_score: float) -> float:
    if score is None or max_score <= 0.0:
        return 0.0
    return score / max_score


def _entity_attenuation(match_count: int, total_records: int) -> tuple[float, float, bool]:
    if total_records <= 0:
        return 1.0, 0.0, False

    match_ratio = match_count / total_records
    if match_count > 12 or match_ratio > 0.30:
        return 0.0, match_ratio, True
    if match_count > 6 or match_ratio > 0.15:
        return 0.5, match_ratio, True
    return 1.0, match_ratio, False


def _build_embedding_text(
    doc_id: int,
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
            f"doc_id: {doc_id}",
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
        "doc_id": record.doc_id,
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


def _build_search_records(
    src_docs: dict[int, OCRArtifact],
    semantic_docs: dict[int, SemanticArtifact] | None = None,
) -> dict[str, SearchRecord]:
    records: dict[str, SearchRecord] = {}

    for doc_id, ocr_artifact in src_docs.items():
        sem_artifact = semantic_docs.get(doc_id) if semantic_docs else None

        for page_index, ocr_page in enumerate(ocr_artifact.pages):
            sem_page = None
            if sem_artifact and page_index < len(sem_artifact.canonical_pages):
                sem_page = sem_artifact.canonical_pages[page_index]

            if sem_page:
                for block_index, sem_block in enumerate(sem_page.blocks, start=1):
                    text = sem_block.text or ""
                    if not _should_index_text(text):
                        continue

                    display_block_id = f"page-{page_index + 1}-block-{block_index}"
                    ocr_block = (
                        ocr_page.blocks[block_index - 1]
                        if block_index <= len(ocr_page.blocks)
                        else None
                    )

                    records[f"semantic:{doc_id}:{page_index + 1}:{block_index}"] = SearchRecord(
                        record_id=f"semantic:{doc_id}:{page_index + 1}:{block_index}",
                        doc_id=doc_id,
                        page=page_index,
                        display_block_id=display_block_id,
                        embedding_text=_build_embedding_text(
                            doc_id=doc_id,
                            page_id=page_index + 1,
                            content=text,
                            generic_role=sem_block.generic_role,
                            domain_role=sem_block.domain_role,
                            generated_role_name=sem_block.generated_role_name,
                            section_purpose=sem_block.section_purpose,
                        ),
                        display_html=(
                            ocr_block.to_structured_html(ocr_page, block_id=display_block_id)
                            if ocr_block
                            else ""
                        ),
                        generic_role=sem_block.generic_role,
                        domain_role=sem_block.domain_role,
                        generated_role_name=sem_block.generated_role_name,
                        section_purpose=sem_block.section_purpose,
                        role_confidence=sem_block.role_confidence or 0.0,
                        semantic_needs_review=sem_block.semantic_needs_review or False,
                        source_kind="semantic",
                    )
            else:
                for block_index, block in enumerate(ocr_page.blocks, start=1):
                    text = block.content or ""
                    if not _should_index_text(text):
                        continue

                    display_block_id = f"page-{page_index + 1}-block-{block_index}"
                    records[f"fallback:{doc_id}:{page_index + 1}:{block_index}"] = SearchRecord(
                        record_id=f"fallback:{doc_id}:{page_index + 1}:{block_index}",
                        doc_id=doc_id,
                        page=page_index,
                        display_block_id=display_block_id,
                        embedding_text=_build_embedding_text(
                            doc_id=doc_id,
                            page_id=page_index + 1,
                            content=text,
                            generic_role=None,
                            domain_role=None,
                            generated_role_name=None,
                            section_purpose=None,
                        ),
                        display_html=block.to_structured_html(
                            ocr_page,
                            block_id=display_block_id,
                        ),
                        generic_role=None,
                        domain_role=None,
                        generated_role_name=None,
                        section_purpose=None,
                        role_confidence=0.0,
                        semantic_needs_review=False,
                        source_kind="fallback",
                    )

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


def _preview_text(html_text: str, *, max_chars: int = 240) -> str:
    text = REGEX_HTML_TAG.sub(" ", html_text)
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _dedupe_texts(values: Sequence[str], *, limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
        if limit is not None and len(result) >= limit:
            break
    return result


class ToolSearchSourceDocument:
    def __init__(
        self,
        src_docs: Sequence[OCRArtifact],
        client: AsyncOpenAI,
        ctx: WriteContext | None = None,
        tracer: GenerationTracer | None = None,
        bm25_client: BM25SearchClient | None = None,
        *,
        semantic_artifacts: Sequence[SemanticArtifact | None] | None = None,
        force_rebuild: bool = False,
        records_override: dict[str, SearchRecord] | None = None,
        collection_override: Any = None,
    ):
        """컬렉션을 로드하거나 생성하고, 현재 검색 대상 문서의 레코드를 준비한다."""
        super().__init__()

        self.client = client
        self.records_by_id: dict[str, SearchRecord] = {}
        self.ctx = ctx
        self.tracer = tracer
        self.collection: Any = collection_override
        self.chroma: Any = None
        self._snapshot_counter = 0
        self.force_rebuild = force_rebuild
        self.doc_ids = list(range(1, len(src_docs) + 1))
        src_docs_dict = {i: doc for i, doc in enumerate(src_docs, start=1)}
        semantic_docs_dict = (
            {i: sem for i, sem in enumerate(semantic_artifacts, start=1) if sem is not None}
            if semantic_artifacts
            else {}
        )

        self.description = {
            "type": "function",
            "function": {
                "name": "search_source_document",
                "description": (
                    "Collect first-stage source document candidates relevant to the query. "
                    "Returns ranked candidate blocks for deciding what document/page to fetch next."
                ),
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "A natural-language search query for discovering useful source document candidates.",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        }

        if records_override is not None:
            self.records_by_id = records_override
        else:
            embedding_function: Any = OpenAIEmbeddingFunction(
                api_key=os.environ["OPENAI_EMBED_API_KEY"],
                api_base=os.environ["OPENAI_EMBED_BASE_URL"],
                model_name=os.environ["OPENAI_EMBED_MODEL"],
            )

            self.chroma = chromadb.RustClient(path="debug_chromadb_cache")
            try:
                if self.force_rebuild and self.collection is None:
                    try:
                        self.chroma.delete_collection(name=COLLECTION_NAME)
                    except Exception:
                        pass

                if self.collection is None and not self.force_rebuild:
                    self.collection = self.chroma.get_collection(
                        name=COLLECTION_NAME,
                        embedding_function=embedding_function,
                    )
                    self.records_by_id = _build_search_records(src_docs_dict, semantic_docs_dict)
                else:
                    raise chromadb.errors.NotFoundError("Collection rebuild requested.")
            except chromadb.errors.NotFoundError:
                self.collection = self.chroma.create_collection(
                    name=COLLECTION_NAME,
                    embedding_function=embedding_function,
                )
                all_records = _build_search_records(src_docs_dict, semantic_docs_dict)
                _populate_collection(self.collection, all_records.values())
                self.records_by_id = all_records

        self.bm25_client = bm25_client or LocalBM25SearchClient(
            _build_bm25_documents(list(self.records_by_id.values()))
        )

    async def invoke(self, param: str, call_id: str) -> dict[str, Any]:
        """OpenAI function-call 인터페이스를 일반 검색 함수로 연결한다."""
        param_parsed = json.loads(param)
        query: str = param_parsed["query"]

        output = await self.invoke_raw(query)
        return {"type": "function_call_output", "output": output, "call_id": call_id}

    def _trace_event(self, event: str, payload: dict[str, Any]) -> None:
        if self.ctx is not None:
            self.ctx.append_trace_sync({"type": event, "component": "search.first_stage", **payload})
        elif self.tracer is not None:
            self.tracer.event("search.first_stage", event, payload)
            self.tracer.record_search_event(event, payload)

    def _save_snapshot(self, kind: str, payload: Any) -> None:
        self._snapshot_counter += 1
        if self.ctx is not None:
            self.ctx.append_log_sync(kind, file=json.dumps(payload, ensure_ascii=False, indent=2))
        elif self.tracer is not None:
            self.tracer.write_json(f"search/{kind}_{self._snapshot_counter:03d}.json", payload)

    def _build_query_profile(self, query: str) -> QueryProfile:
        normalized_query = _normalize_query_text(query)
        query_tokens = _extract_query_tokens(normalized_query)
        entity_candidates = _extract_entity_candidates(normalized_query)
        lexical_query = _build_fallback_lexical_query(query_tokens, entity_candidates)
        profile = QueryProfile(
            raw_query=query,
            normalized_query=normalized_query,
            query_tokens=query_tokens,
            entity_candidates=entity_candidates,
            grounded_entities=[],
            semantic_queries=[normalized_query] if normalized_query else [],
            lexical_queries=[lexical_query] if lexical_query else [],
        )
        self._trace_event(
            "query_preprocessed",
            {
                "query": profile.raw_query,
                "normalized_query": profile.normalized_query,
                "query_tokens": profile.query_tokens,
                "entity_candidates": profile.entity_candidates,
                "grounded_entities": profile.grounded_entities,
                "semantic_queries": profile.semantic_queries,
                "lexical_queries": profile.lexical_queries,
            },
        )
        return profile

    async def _request_query_expansion(self, profile: QueryProfile) -> dict[str, list[str]]:
        if self.client is None:
            self._trace_event(
                "llm_expansion_failed",
                {"query": profile.raw_query, "reason": "client_unavailable"},
            )
            return {"entities": [], "semantic_queries": [], "lexical_queries": []}

        prompt = PROMPT_QUERY_EXPANSION.format(
            query=profile.raw_query,
            source_documents=", ".join([str(x) for x in self.doc_ids]),
        )
        self._trace_event(
            "llm_expansion_requested",
            {"query": profile.raw_query, "source_documents": self.doc_ids},
        )
        model_name = (
            os.environ.get("OPENAI_QUERY_EXPANSION_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or "gpt-4.1-mini"
        )
        response = await self.client.responses.create(
            model=model_name,
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
        )
        self._save_snapshot("llm_query_expansion", _response_to_jsonable(response))
        output_text = _extract_response_text(response)
        payload = _normalize_query_expansion_payload(_extract_json_object(output_text))
        if not any(payload.values()):
            self._trace_event(
                "llm_expansion_failed",
                {"query": profile.raw_query, "reason": "invalid_or_empty_json", "preview": output_text[:500]},
            )
            return {"entities": [], "semantic_queries": [], "lexical_queries": []}

        self._trace_event(
            "llm_expansion_saved",
            {
                "query": profile.raw_query,
                "entities": payload["entities"],
                "semantic_queries": payload["semantic_queries"],
                "lexical_queries": payload["lexical_queries"],
            },
        )
        return payload

    def _apply_query_expansion(
        self,
        profile: QueryProfile,
        expansion_payload: dict[str, list[str]],
    ) -> QueryProfile:
        semantic_queries = _dedupe_texts(
            [profile.normalized_query, *expansion_payload["semantic_queries"]],
            limit=SEMANTIC_QUERY_LIMIT,
        )
        lexical_queries = _dedupe_texts(
            [*profile.lexical_queries, *expansion_payload["lexical_queries"]],
            limit=2,
        )
        entity_candidates = _dedupe_texts(
            [*profile.entity_candidates, *expansion_payload["entities"]],
            limit=ENTITY_GROUNDING_LIMIT,
        )
        return QueryProfile(
            raw_query=profile.raw_query,
            normalized_query=profile.normalized_query,
            query_tokens=profile.query_tokens,
            entity_candidates=entity_candidates,
            grounded_entities=profile.grounded_entities,
            semantic_queries=semantic_queries,
            lexical_queries=lexical_queries,
        )

    def _where_condition(self) -> Any:
        if len(self.doc_ids) > 1:
            return {"$or": [{"doc_id": doc_id} for doc_id in self.doc_ids]}
        if len(self.doc_ids) == 1:
            return {"doc_id": self.doc_ids[0]}
        raise ValueError("document list is empty")

    def _collect_semantic_candidates(self, profile: QueryProfile) -> dict[str, RetrievalCandidate]:
        candidates: dict[str, RetrievalCandidate] = {}
        query_payloads: list[dict[str, Any]] = []

        if self.collection is None:
            self._trace_event(
                "semantic_retrieval_completed",
                {"queries": profile.semantic_queries, "hits": [], "error": "collection_unavailable"},
            )
            return candidates

        for semantic_query in profile.semantic_queries:
            hits_for_query: list[dict[str, Any]] = []
            try:
                results = self.collection.query(
                    query_texts=[semantic_query],
                    n_results=SEMANTIC_QUERY_TOP_K,
                    where=self._where_condition(),
                    include=["metadatas", "distances"],
                )
                result_ids = results.get("ids") or [[]]
                distances = results.get("distances") or [[]]
                for record_id, distance in zip(result_ids[0], distances[0]):
                    record = self.records_by_id.get(record_id)
                    if record is None:
                        continue
                    distance_value = float(distance)
                    existing = candidates.get(record_id)
                    if existing is None or existing.semantic_distance is None or distance_value < existing.semantic_distance:
                        candidates[record_id] = RetrievalCandidate(
                            record=record,
                            channels={"semantic"},
                            semantic_distance=distance_value,
                        )
                    else:
                        existing.channels.add("semantic")

                    hits_for_query.append(
                        {
                            "record_id": record.record_id,
                            "doc_id": record.doc_id,
                            "page_id": record.page + 1,
                            "block_id": record.display_block_id,
                            "distance": distance_value,
                            "generic_role": record.generic_role,
                            "generated_role_name": record.generated_role_name,
                            "section_purpose": record.section_purpose,
                        }
                    )
            except Exception as exc:
                hits_for_query.append({"error": f"{type(exc).__name__}: {exc}"})
            query_payloads.append({"query": semantic_query, "hits": hits_for_query})

        self._trace_event(
            "semantic_retrieval_completed",
            {"queries": query_payloads, "candidate_count": len(candidates)},
        )
        return candidates

    async def _collect_bm25_candidates(self, profile: QueryProfile) -> dict[str, RetrievalCandidate]:
        candidates: dict[str, RetrievalCandidate] = {}
        query_payloads: list[dict[str, Any]] = []

        for lexical_query in profile.lexical_queries:
            try:
                hits = await asyncio.to_thread(
                    self.bm25_client.search,
                    query=lexical_query,
                    docs=[str(x) for x in self.doc_ids],
                    top_k=BM25_QUERY_TOP_K,
                )
                self._save_snapshot(
                    "bm25_hits",
                    {
                        "query": lexical_query,
                        "hits": [
                            {
                                "record_id": hit.record_id,
                                "score": hit.score,
                                "matched_terms": hit.matched_terms,
                                "doc_id": int(hit.document_id),
                                "page_id": hit.page_id,
                                "block_id": hit.block_id,
                            }
                            for hit in hits
                        ],
                    },
                )

                payload_hits: list[dict[str, Any]] = []
                for hit in hits:
                    record = self.records_by_id.get(hit.record_id)
                    if record is None:
                        continue
                    existing = candidates.get(hit.record_id)
                    if existing is None or existing.bm25_score is None or hit.score > existing.bm25_score:
                        candidates[hit.record_id] = RetrievalCandidate(
                            record=record,
                            channels={"bm25"},
                            bm25_score=hit.score,
                            matched_terms=hit.matched_terms,
                        )
                    else:
                        existing.channels.add("bm25")
                    payload_hits.append(
                        {
                            "record_id": hit.record_id,
                            "score": hit.score,
                            "matched_terms": hit.matched_terms,
                            "doc_id": record.doc_id,
                            "page_id": hit.page_id,
                            "block_id": hit.block_id,
                        }
                    )
                query_payloads.append({"query": lexical_query, "hits": payload_hits})
            except Exception as exc:
                self._trace_event(
                    "bm25_retrieval_failed",
                    {"query": lexical_query, "error": f"{type(exc).__name__}: {exc}"},
                )

        self._trace_event(
            "bm25_retrieval_completed",
            {"queries": query_payloads, "candidate_count": len(candidates)},
        )
        return candidates

    async def _collect_entity_candidates(self, profile: QueryProfile) -> dict[str, RetrievalCandidate]:
        hits_by_record: dict[str, RetrievalCandidate] = {}
        grounded_entities: list[str] = []
        trace_entities: list[dict[str, Any]] = []
        total_records = len(self.records_by_id)

        def do_iteration():
            local_hits: list[tuple[str, list[str], float, float, bool]] = []
            for entity in profile.entity_candidates:
                normalized = entity.lower()
                matched_record_ids: list[str] = []
                for record in self.records_by_id.values():
                    if normalized not in record.embedding_text.lower():
                        continue
                    matched_record_ids.append(record.record_id)

                attenuation_factor, match_ratio, is_common_entity = _entity_attenuation(
                    len(matched_record_ids), total_records
                )
                local_hits.append((entity, matched_record_ids, attenuation_factor, match_ratio, is_common_entity))
            return local_hits

        results = await asyncio.to_thread(do_iteration)

        for entity, matched_record_ids, attenuation_factor, match_ratio, is_common_entity in results:
            if matched_record_ids and attenuation_factor > 0.0:
                entity_signal = min(1.0, attenuation_factor)
                for record_id in matched_record_ids:
                    record = self.records_by_id[record_id]
                    existing = hits_by_record.get(record.record_id)
                    if existing is None:
                        hits_by_record[record.record_id] = RetrievalCandidate(
                            record=record,
                            channels={"entity"},
                            entity_score=entity_signal,
                        )
                    else:
                        existing.channels.add("entity")
                        existing.entity_score = min(1.0, existing.entity_score + entity_signal)
                grounded_entities.append(entity)
            trace_entities.append(
                {
                    "entity": entity,
                    "matched_record_ids": matched_record_ids[:ENTITY_GROUNDING_LIMIT],
                    "match_count": len(matched_record_ids),
                    "match_ratio": match_ratio,
                    "attenuation_factor": attenuation_factor,
                    "is_common_entity": is_common_entity,
                }
            )

        profile.grounded_entities = grounded_entities[:ENTITY_GROUNDING_LIMIT]
        self._trace_event(
            "entity_grounding_completed",
            {
                "entity_candidates": profile.entity_candidates,
                "grounded_entities": profile.grounded_entities,
                "matches": trace_entities,
            },
        )
        return hits_by_record

    def _merge_candidates(
        self,
        *candidate_maps: dict[str, RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        merged: dict[str, RetrievalCandidate] = {}
        for candidate_map in candidate_maps:
            for record_id, candidate in candidate_map.items():
                existing = merged.get(record_id)
                if existing is None:
                    merged[record_id] = RetrievalCandidate(
                        record=candidate.record,
                        channels=set(candidate.channels),
                        semantic_distance=candidate.semantic_distance,
                        bm25_score=candidate.bm25_score,
                        entity_score=candidate.entity_score,
                        matched_terms=list(candidate.matched_terms or []),
                    )
                    continue

                existing.channels.update(candidate.channels)
                if candidate.semantic_distance is not None and (
                    existing.semantic_distance is None
                    or candidate.semantic_distance < existing.semantic_distance
                ):
                    existing.semantic_distance = candidate.semantic_distance
                if candidate.bm25_score is not None and (
                    existing.bm25_score is None or candidate.bm25_score > existing.bm25_score
                ):
                    existing.bm25_score = candidate.bm25_score
                existing.entity_score = max(existing.entity_score, candidate.entity_score)
                if candidate.matched_terms:
                    existing.matched_terms = sorted(
                        set(existing.matched_terms or []).union(candidate.matched_terms)
                    )

        merged_candidates = list(merged.values())
        self._trace_event(
            "candidate_merge_completed",
            {
                "candidate_count": len(merged_candidates),
                "candidates": [
                    {
                        "record_id": candidate.record.record_id,
                        "doc_id": candidate.record.doc_id,
                        "page_id": candidate.record.page + 1,
                        "block_id": candidate.record.display_block_id,
                        "channels": sorted(candidate.channels),
                        "semantic_distance": candidate.semantic_distance,
                        "bm25_score": candidate.bm25_score,
                        "entity_score": candidate.entity_score,
                        "is_entity_only": candidate.is_entity_only,
                    }
                    for candidate in merged_candidates
                ],
            },
        )
        return merged_candidates

    def _order_candidates(self, candidates: Sequence[RetrievalCandidate]) -> list[RetrievalCandidate]:
        max_bm25 = max((candidate.bm25_score or 0.0) for candidate in candidates) if candidates else 0.0
        signal_candidates: list[RetrievalCandidate] = []
        entity_only_candidates: list[RetrievalCandidate] = []
        for candidate in candidates:
            if candidate.is_entity_only:
                candidate.first_stage_score = (
                    (candidate.entity_score * 0.20)
                    + (candidate.record.role_confidence * 0.05)
                    - (NEEDS_REVIEW_PENALTY if candidate.record.semantic_needs_review else 0.0)
                )
                entity_only_candidates.append(candidate)
                continue

            candidate.first_stage_score = (
                (_semantic_proximity(candidate.semantic_distance) * 0.45)
                + (_bm25_signal(candidate.bm25_score, max_score=max_bm25) * 0.35)
                + (candidate.entity_score * 0.05)
                + (candidate.record.role_confidence * 0.10)
                - (NEEDS_REVIEW_PENALTY if candidate.record.semantic_needs_review else 0.0)
            )
            signal_candidates.append(candidate)

        signal_candidates.sort(
            key=lambda candidate: (
                -candidate.first_stage_score,
                candidate.semantic_distance if candidate.semantic_distance is not None else 999.0,
                -(candidate.bm25_score or 0.0),
                candidate.record.doc_id,
                candidate.record.page,
                candidate.record.display_block_id,
            )
        )
        entity_only_candidates.sort(
            key=lambda candidate: (
                -candidate.first_stage_score,
                candidate.record.doc_id,
                candidate.record.page,
                candidate.record.display_block_id,
            )
        )

        ordered = list(signal_candidates[:FIRST_STAGE_LIMIT])
        if len(ordered) < FIRST_STAGE_LIMIT:
            ordered.extend(entity_only_candidates[: FIRST_STAGE_LIMIT - len(ordered)])

        self._trace_event(
            "first_stage_ordered",
            {
                "candidate_count": len(ordered),
                "candidates": [
                    {
                        "record_id": candidate.record.record_id,
                        "channels": sorted(candidate.channels),
                        "first_stage_score": candidate.first_stage_score,
                        "semantic_distance": candidate.semantic_distance,
                        "bm25_score": candidate.bm25_score,
                        "entity_score": candidate.entity_score,
                        "is_entity_only": candidate.is_entity_only,
                    }
                    for candidate in ordered
                ],
            },
        )
        return ordered

    def _format_search_output(self, candidates: Sequence[RetrievalCandidate]) -> str:
        if not candidates:
            return "First-stage search result: no matching source candidates found."

        output = [
            "First-stage candidate bundle:",
            "Use these candidates to decide which document_id/page_id should be fetched next.",
            "",
        ]
        for index, candidate in enumerate(candidates[:TOOL_DISPLAY_LIMIT], start=1):
            record = candidate.record
            output.append(
                "Candidate #{idx}: record_id={record_id}, doc_id={doc_id}, page_id={page_id}, "
                "block_id={block_id}, channels={channels}, first_stage_score={score:.4f}".format(
                    idx=index,
                    record_id=record.record_id,
                    doc_id=record.doc_id,
                    page_id=record.page + 1,
                    block_id=record.display_block_id,
                    channels=",".join(sorted(candidate.channels)),
                    score=candidate.first_stage_score,
                )
            )
            output.append(
                "semantic_distance={semantic_distance}, bm25_score={bm25_score}, entity_score={entity_score:.2f}, "
                "generic_role={generic_role}, generated_role_name={role_name}, section_purpose={purpose}".format(
                    semantic_distance=(
                        f"{candidate.semantic_distance:.4f}"
                        if candidate.semantic_distance is not None
                        else "n/a"
                    ),
                    bm25_score=(
                        f"{candidate.bm25_score:.4f}" if candidate.bm25_score is not None else "n/a"
                    ),
                    entity_score=candidate.entity_score,
                    generic_role=record.generic_role or "unknown",
                    role_name=record.generated_role_name or "unknown",
                    purpose=record.section_purpose or "unknown",
                )
            )
            if candidate.matched_terms:
                output.append(f"matched_terms={', '.join(candidate.matched_terms)}")
            output.append(f"preview={_preview_text(record.display_html)}")
            output.append("")

        return "\n".join(output)

    async def invoke_raw(self, query: str) -> str:
        """질의를 실행하고 1차 후보 10~12개를 반환한다."""
        if not self.doc_ids:
            raise ValueError("document list is empty")

        print(f"[search_source_document] {query}")

        profile = self._build_query_profile(query)
        expansion_payload = await self._request_query_expansion(profile)
        profile = self._apply_query_expansion(profile, expansion_payload)

        semantic_candidates = self._collect_semantic_candidates(profile)
        bm25_candidates = await self._collect_bm25_candidates(profile)
        entity_candidates = await self._collect_entity_candidates(profile)
        merged_candidates = self._merge_candidates(
            semantic_candidates,
            bm25_candidates,
            entity_candidates,
        )
        ordered_candidates = self._order_candidates(merged_candidates)

        self._trace_event(
            "first_stage_returned",
            {
                "query": query,
                "candidate_count": len(ordered_candidates),
                "grounded_entities": profile.grounded_entities,
                "semantic_queries": profile.semantic_queries,
                "lexical_queries": profile.lexical_queries,
            },
        )
        return self._format_search_output(ordered_candidates)
