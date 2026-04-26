import json
import shutil
import unittest
import uuid
from pathlib import Path

from llm2doc.bm25_search import BM25Document, LocalBM25SearchClient
from llm2doc.create_document import normalize_analysis_payload
from llm2doc.debug_trace import DecisionTracer
from llm2doc.tool_search_source_document import (
    SearchRecord,
    ToolSearchSourceDocument,
    _build_fallback_lexical_query,
    _extract_entity_candidates,
    _extract_query_tokens,
)


class FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.output = []

    def model_dump_json(self) -> str:
        return json.dumps({"output_text": self.output_text}, ensure_ascii=False)


class FakeResponses:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)

    def create(self, **_: object) -> FakeResponse:
        if not self._responses:
            raise AssertionError("No fake responses left")
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = FakeResponses(responses)


class FakeCollection:
    def __init__(self, hits_by_query: dict[str, list[tuple[str, float]]]) -> None:
        self.hits_by_query = hits_by_query

    def query(self, query_texts, n_results, where, include):  # type: ignore[no-untyped-def]
        del where, include
        query = query_texts[0]
        hits = self.hits_by_query.get(query, [])[:n_results]
        return {
            "ids": [[record_id for record_id, _ in hits]],
            "distances": [[distance for _, distance in hits]],
        }


class RaisingBM25Client:
    def search(self, query: str, docs: list[str], top_k: int):  # type: ignore[no-untyped-def]
        del query, docs, top_k
        raise RuntimeError("bm25 unavailable")


def make_record(
    record_id: str,
    document: str,
    page: int,
    block_id: str,
    text: str,
    *,
    role_name: str | None = None,
    section_purpose: str | None = None,
    role_confidence: float = 0.0,
) -> SearchRecord:
    return SearchRecord(
        record_id=record_id,
        document=document,
        page=page,
        display_block_id=block_id,
        embedding_text=text,
        display_html=f'<div id="{block_id}"><p>{text}</p></div>',
        generic_role=None,
        domain_role=None,
        generated_role_name=role_name,
        section_purpose=section_purpose,
        role_confidence=role_confidence,
        semantic_needs_review=False,
        source_kind="semantic",
    )


class ToolSearchSourceDocumentTests(unittest.TestCase):
    def make_tempdir(self) -> Path:
        base_dir = Path.cwd() / "build" / "test_tool_search_source_document"
        base_dir.mkdir(parents=True, exist_ok=True)
        tmpdir = base_dir / f"case-{uuid.uuid4().hex[:8]}"
        tmpdir.mkdir(parents=True, exist_ok=False)
        return tmpdir

    def make_records(self) -> dict[str, SearchRecord]:
        records = [
            make_record(
                "semantic:financial2:block-1",
                "financial2",
                0,
                "block-1",
                "KMW 032500 목표주가 현재주가 투자 포인트",
                role_name="investment_thesis_header",
                section_purpose="thesis",
                role_confidence=0.8,
            ),
            make_record(
                "semantic:financial2:block-2",
                "financial2",
                1,
                "block-2",
                "매출 영업이익 EPS PER PBR 재무 지표",
                role_name="financial_metrics_table",
                section_purpose="metrics",
                role_confidence=0.7,
            ),
            make_record(
                "fallback:financial3:1:1",
                "financial3",
                0,
                "block-3",
                "다른 기업에 대한 설명",
            ),
        ]
        return {record.record_id: record for record in records}

    def read_event_names(self, tmpdir: Path) -> list[str]:
        search_log = next((tmpdir / "trace").glob("*/search/first_stage.jsonl"))
        with search_log.open("rt", encoding="utf-8") as f:
            return [json.loads(line)["event"] for line in f if line.strip()]

    def test_extract_query_tokens_removes_stopwords(self) -> None:
        tokens = _extract_query_tokens("financial2 문서를 기반으로 KMW 기업 분석 보고서 작성해줘")
        self.assertIn("financial2", tokens)
        self.assertIn("kmw", tokens)
        self.assertNotIn("문서를", tokens)
        self.assertNotIn("작성해줘", tokens)

    def test_extract_entity_candidates_excludes_korean_named_tokens(self) -> None:
        candidates = _extract_entity_candidates("케이엠더블유 KMW 032500 50,000원 분석")
        self.assertIn("KMW", candidates)
        self.assertIn("032500", candidates)
        self.assertIn("50,000원", candidates)
        self.assertNotIn("케이엠더블유", candidates)

    def test_build_fallback_lexical_query(self) -> None:
        lexical_query = _build_fallback_lexical_query(["kmw", "재무", "정보"], ["KMW", "032500"])
        self.assertIn("KMW", lexical_query)
        self.assertIn("032500", lexical_query)
        self.assertIn("재무", lexical_query)

    def test_local_bm25_ranks_exact_hits(self) -> None:
        client = LocalBM25SearchClient(
            [
                BM25Document("r1", "financial2", 1, "b1", "KMW 032500 목표주가 재무 지표"),
                BM25Document("r2", "financial2", 1, "b2", "다른 기업 소개"),
            ]
        )
        hits = client.search("KMW 재무", ["financial2"], top_k=5)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0].record_id, "r1")

    def test_invoke_raw_collects_candidates_and_traces_events(self) -> None:
        tmpdir = self.make_tempdir()
        try:
            tracer = DecisionTracer.create(tmpdir, enabled=True, run_id="run-1")
            records = self.make_records()
            collection = FakeCollection(
                {
                    "KMW 재무 정보": [("semantic:financial2:block-1", 0.18)],
                    "KMW financial metrics": [("semantic:financial2:block-2", 0.22)],
                }
            )
            client = FakeClient(
                [
                    FakeResponse(
                        json.dumps(
                            {
                                "entities": ["KMW", "032500"],
                                "semantic_queries": ["KMW financial metrics"],
                                "lexical_queries": ["KMW 032500 매출 영업이익 EPS PER PBR"],
                            },
                            ensure_ascii=False,
                        )
                    )
                ]
            )
            tool = ToolSearchSourceDocument(
                ["financial2", "financial3"],
                client=client,
                tracer=tracer,
                records_override=records,
                collection_override=collection,
            )

            output = tool.invoke_raw("KMW 재무 정보")

            self.assertIn("First-stage candidate bundle:", output)
            self.assertIn("Candidate #1:", output)
            self.assertIn("channels=", output)
            self.assertIn("preview=", output)

            events = self.read_event_names(tmpdir)
            self.assertIn("query_preprocessed", events)
            self.assertIn("llm_expansion_saved", events)
            self.assertIn("semantic_retrieval_completed", events)
            self.assertIn("bm25_retrieval_completed", events)
            self.assertIn("entity_grounding_completed", events)
            self.assertIn("candidate_merge_completed", events)
            self.assertIn("first_stage_ordered", events)
            self.assertIn("first_stage_returned", events)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invoke_raw_falls_back_when_expansion_json_is_invalid(self) -> None:
        tmpdir = self.make_tempdir()
        try:
            tracer = DecisionTracer.create(tmpdir, enabled=True, run_id="run-2")
            records = self.make_records()
            collection = FakeCollection({"KMW 재무 정보": [("semantic:financial2:block-1", 0.15)]})
            tool = ToolSearchSourceDocument(
                ["financial2"],
                client=FakeClient([FakeResponse("not-json")]),
                tracer=tracer,
                records_override=records,
                collection_override=collection,
            )

            output = tool.invoke_raw("KMW 재무 정보")

            self.assertIn("First-stage candidate bundle:", output)
            self.assertIn("Candidate #1:", output)
            events = self.read_event_names(tmpdir)
            self.assertIn("llm_expansion_failed", events)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invoke_raw_continues_when_bm25_fails(self) -> None:
        tmpdir = self.make_tempdir()
        try:
            tracer = DecisionTracer.create(tmpdir, enabled=True, run_id="run-3")
            records = self.make_records()
            collection = FakeCollection({"KMW 재무 정보": [("semantic:financial2:block-1", 0.10)]})
            tool = ToolSearchSourceDocument(
                ["financial2"],
                client=FakeClient(
                    [
                        FakeResponse(
                            json.dumps(
                                {
                                    "entities": ["KMW"],
                                    "semantic_queries": [],
                                    "lexical_queries": ["KMW 재무"],
                                },
                                ensure_ascii=False,
                            )
                        )
                    ]
                ),
                tracer=tracer,
                bm25_client=RaisingBM25Client(),
                records_override=records,
                collection_override=collection,
            )

            output = tool.invoke_raw("KMW 재무 정보")

            self.assertIn("First-stage candidate bundle:", output)
            events = self.read_event_names(tmpdir)
            self.assertIn("bm25_retrieval_failed", events)
            self.assertIn("first_stage_returned", events)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_common_entity_is_attenuated_and_entity_only_candidates_do_not_lead(self) -> None:
        tmpdir = self.make_tempdir()
        try:
            tracer = DecisionTracer.create(tmpdir, enabled=True, run_id="run-4")
            records = {
                f"fallback:news1:1:{idx}": make_record(
                    f"fallback:news1:1:{idx}",
                    "news1",
                    0,
                    f"block-{idx}",
                    f"트럼프 관련 일반 기사 {idx}",
                )
                for idx in range(1, 15)
            }
            records["semantic:news1:block-strong"] = make_record(
                "semantic:news1:block-strong",
                "news1",
                0,
                "block-strong",
                "트럼프 미국 대통령 핵심 정책 발표",
                role_confidence=0.6,
            )
            collection = FakeCollection({"트럼프 미국 대통령 정책": [("semantic:news1:block-strong", 0.12)]})
            tool = ToolSearchSourceDocument(
                ["news1"],
                client=FakeClient(
                    [
                        FakeResponse(
                            json.dumps(
                                {
                                    "entities": ["트럼프", "미국"],
                                    "semantic_queries": [],
                                    "lexical_queries": [],
                                },
                                ensure_ascii=False,
                            )
                        )
                    ]
                ),
                tracer=tracer,
                records_override=records,
                collection_override=collection,
            )

            output = tool.invoke_raw("트럼프 미국 대통령 정책")

            self.assertIn("Candidate #1: record_id=semantic:news1:block-strong", output)

            search_log = next((tmpdir / "trace").glob("*/search/first_stage.jsonl"))
            with search_log.open("rt", encoding="utf-8") as f:
                rows = [json.loads(line) for line in f if line.strip()]

            entity_row = next(row for row in rows if row["event"] == "entity_grounding_completed")
            trump_match = next(item for item in entity_row["payload"]["matches"] if item["entity"] == "트럼프")
            self.assertEqual(trump_match["attenuation_factor"], 0.0)
            self.assertTrue(trump_match["is_common_entity"])

            ordered_row = next(row for row in rows if row["event"] == "first_stage_ordered")
            self.assertFalse(ordered_row["payload"]["candidates"][0]["is_entity_only"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_entity_only_candidates_fill_tail_only_when_signal_candidates_are_short(self) -> None:
        tmpdir = self.make_tempdir()
        try:
            tracer = DecisionTracer.create(tmpdir, enabled=True, run_id="run-5")
            records = {
                "semantic:news1:block-1": make_record(
                    "semantic:news1:block-1",
                    "news1",
                    0,
                    "block-1",
                    "KMW 정책 핵심 발표",
                    role_confidence=0.4,
                ),
                "fallback:news1:1:2": make_record(
                    "fallback:news1:1:2",
                    "news1",
                    0,
                    "block-2",
                    "KMW 관련 보조 기사",
                ),
                "fallback:news1:1:3": make_record(
                    "fallback:news1:1:3",
                    "news1",
                    0,
                    "block-3",
                    "다른 보조 기사",
                ),
            }
            for idx in range(4, 11):
                records[f"fallback:news1:1:{idx}"] = make_record(
                    f"fallback:news1:1:{idx}",
                    "news1",
                    0,
                    f"block-{idx}",
                    f"무관한 문맥 {idx}",
                )
            collection = FakeCollection({"트럼프 정책": [("semantic:news1:block-1", 0.10)]})
            tool = ToolSearchSourceDocument(
                ["news1"],
                client=FakeClient(
                    [
                        FakeResponse(
                            json.dumps(
                                {
                                    "entities": ["KMW"],
                                    "semantic_queries": [],
                                    "lexical_queries": [],
                                },
                                ensure_ascii=False,
                            )
                        )
                    ]
                ),
                tracer=tracer,
                records_override=records,
                collection_override=collection,
            )

            tool.invoke_raw("트럼프 정책")

            search_log = next((tmpdir / "trace").glob("*/search/first_stage.jsonl"))
            with search_log.open("rt", encoding="utf-8") as f:
                rows = [json.loads(line) for line in f if line.strip()]

            ordered_row = next(row for row in rows if row["event"] == "first_stage_ordered")
            candidates = ordered_row["payload"]["candidates"]
            self.assertEqual(candidates[0]["record_id"], "semantic:news1:block-1")
            self.assertTrue(any(candidate["is_entity_only"] for candidate in candidates[1:]))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_entity_attenuation_records_half_strength_for_mid_frequency_entities(self) -> None:
        tmpdir = self.make_tempdir()
        try:
            tracer = DecisionTracer.create(tmpdir, enabled=True, run_id="run-6")
            records: dict[str, SearchRecord] = {}
            for idx in range(1, 31):
                text = "트럼프 일반 문맥" if idx <= 7 else "다른 문맥"
                records[f"fallback:news1:1:{idx}"] = make_record(
                    f"fallback:news1:1:{idx}",
                    "news1",
                    0,
                    f"block-{idx}",
                    text,
                )
            collection = FakeCollection({})
            tool = ToolSearchSourceDocument(
                ["news1"],
                client=FakeClient(
                    [
                        FakeResponse(
                            json.dumps(
                                {
                                    "entities": ["트럼프"],
                                    "semantic_queries": [],
                                    "lexical_queries": [],
                                },
                                ensure_ascii=False,
                            )
                        )
                    ]
                ),
                tracer=tracer,
                records_override=records,
                collection_override=collection,
            )

            tool.invoke_raw("트럼프")

            search_log = next((tmpdir / "trace").glob("*/search/first_stage.jsonl"))
            with search_log.open("rt", encoding="utf-8") as f:
                rows = [json.loads(line) for line in f if line.strip()]

            entity_row = next(row for row in rows if row["event"] == "entity_grounding_completed")
            trump_match = next(item for item in entity_row["payload"]["matches"] if item["entity"] == "트럼프")
            self.assertEqual(trump_match["attenuation_factor"], 0.5)
            self.assertTrue(trump_match["is_common_entity"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_normalize_analysis_payload_promotes_and_dedupes_matched_via(self) -> None:
        normalized = normalize_analysis_payload(
            {
                "evidence": [
                    {
                        "document_id": "news1",
                        "page_id": 1,
                        "block_id": "block-1",
                        "matched_via": "entity",
                        "used_for": "headline",
                        "why_selected": "single string",
                    },
                    {
                        "document_id": "news1",
                        "page_id": 2,
                        "block_id": "block-2",
                        "matched_via": ["semantic", "bm25", "entity", "bm25"],
                        "used_for": "body",
                        "why_selected": "array input",
                    },
                ]
            },
            query="트럼프",
            source_doc_ids=["news1"],
        )

        self.assertEqual(normalized["evidence"][0]["matched_via"], ["entity"])
        self.assertEqual(normalized["evidence"][1]["matched_via"], ["semantic", "bm25", "entity"])


if __name__ == "__main__":
    unittest.main()
