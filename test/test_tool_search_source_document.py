import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
LLM2DOC_ROOT = ROOT / "llm-to-document"
if str(LLM2DOC_ROOT) not in sys.path:
    sys.path.insert(0, str(LLM2DOC_ROOT))

from llm2doc.analyze_layout import BlockInfo, ParsedDocument, ParsedPage
from llm2doc.tool_search_source_document import (
    SearchRecord,
    _build_embedding_text,
    _build_fallback_records_for_document,
    _build_search_records_for_parsed_doc,
    _build_semantic_records_for_page,
    _format_search_output,
    _load_semantic_artifact_pages,
    _rerank_records,
    _sample_to_doc_page_index,
)


TMP_ROOT = ROOT / "test" / ".tmp_semantic_search"


class ToolSearchSourceDocumentHelpersTest(unittest.TestCase):
    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(TMP_ROOT, ignore_errors=True)

    def _case_dir(self, name: str) -> Path:
        case_dir = TMP_ROOT / f"{name}_{uuid.uuid4().hex}"
        case_dir.mkdir(parents=True, exist_ok=True)
        return case_dir

    def test_sample_id_page_index_mapping(self):
        self.assertEqual(_sample_to_doc_page_index("financial1-00", "financial1", 3, 1), 0)
        self.assertEqual(_sample_to_doc_page_index("financial1-02", "financial1", 3, 1), 2)
        self.assertEqual(_sample_to_doc_page_index("medical1", "medical1", 1, 1), 0)
        self.assertIsNone(_sample_to_doc_page_index("blog1-99", "blog1", 3, 1))

    def test_build_embedding_text_includes_semantic_fields(self):
        text = _build_embedding_text(
            document="financial1",
            page_id=2,
            content="Body paragraph",
            generic_role="body",
            domain_role="supporting_argument",
            generated_role_name="market_summary_heading",
            section_purpose="thesis",
        )

        self.assertIn("document_id: financial1", text)
        self.assertIn("page_id: 2", text)
        self.assertIn("generic_role: body", text)
        self.assertIn("generated_role_name: market_summary_heading", text)
        self.assertTrue(text.endswith("Body paragraph"))

    def test_build_semantic_records_keeps_short_heading_and_skips_placeholder(self):
        artifact_page = {
            "width": 1000,
            "height": 1000,
            "blocks": [
                {
                    "block_id": "financial1-00-short",
                    "text": "BUY",
                    "bbox_px": [10, 10, 80, 40],
                },
                {
                    "block_id": "financial1-00-image",
                    "text": "![Figure](figures/financial1-00_figure_000.png)",
                    "bbox_px": [10, 60, 80, 120],
                },
                {
                    "block_id": "financial1-00-table",
                    "text": "<table><tr><td>A</td><td>1</td></tr></table>",
                    "bbox_px": [100, 100, 400, 240],
                },
            ],
            "overlay_by_block_id": {
                "financial1-00-short": {
                    "generated_role_name": "investment_rating_label",
                    "section_purpose": "thesis",
                    "role_confidence": 0.95,
                },
                "financial1-00-table": {
                    "generated_role_name": "key_metrics_table",
                    "section_purpose": "supporting_argument",
                    "role_confidence": 0.8,
                },
            },
        }

        records = _build_semantic_records_for_page("financial1", 0, artifact_page)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].display_block_id, "financial1-00-short")
        self.assertEqual(records[0].generated_role_name, "investment_rating_label")
        self.assertIn("<table>", records[1].display_html)

    def test_build_fallback_records_uses_unknown_roles(self):
        parsed_doc = ParsedDocument(
            id="blog1",
            pages=[
                ParsedPage(
                    width=100,
                    height=100,
                    blocks=[
                        BlockInfo(
                            label="text",
                            content="Short heading",
                            bbox=[1, 2, 50, 20],
                            is_text=True,
                            is_image=False,
                            is_html=False,
                        )
                    ],
                    screenshot=Image.new("RGB", (100, 100)),
                    json="{}",
                    markdown="",
                    markdown_images={},
                )
            ],
            concatenated_markdown="",
        )

        records = _build_fallback_records_for_document("blog1", parsed_doc, set())

        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].generic_role)
        self.assertIn("generic_role: unknown", records[0].embedding_text)

    def test_load_semantic_artifact_pages_resolves_matching_sample_id(self):
        case_dir = self._case_dir("artifact_load")
        artifact_dir = case_dir / "financial1-00" / "01_reference"
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "canonical_pages.json").write_text(
            json.dumps(
                [
                    {
                        "page": 1,
                        "sample_id": "financial1-00",
                        "width": 100,
                        "height": 200,
                        "blocks": [
                            {
                                "block_id": "financial1-00-1",
                                "text": "Header",
                                "bbox_px": [1, 2, 50, 20],
                            }
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )
        (artifact_dir / "semantic_overlay.json").write_text(
            json.dumps(
                [
                    {
                        "block_id": "financial1-00-1",
                        "generated_role_name": "headline",
                        "section_purpose": "thesis",
                    }
                ]
            ),
            encoding="utf-8",
        )

        pages = _load_semantic_artifact_pages("financial1", 3, case_dir)

        self.assertIn(0, pages)
        self.assertEqual(pages[0]["sample_id"], "financial1-00")

    def test_build_search_records_for_parsed_doc_mixes_semantic_and_fallback_pages(self):
        parsed_doc = ParsedDocument(
            id="financial1",
            pages=[
                ParsedPage(
                    width=100,
                    height=100,
                    blocks=[
                        BlockInfo(
                            label="text",
                            content="Fallback page one",
                            bbox=[1, 1, 80, 20],
                            is_text=True,
                            is_image=False,
                            is_html=False,
                        )
                    ],
                    screenshot=Image.new("RGB", (100, 100)),
                    json="{}",
                    markdown="",
                    markdown_images={},
                ),
                ParsedPage(
                    width=100,
                    height=100,
                    blocks=[
                        BlockInfo(
                            label="text",
                            content="Fallback page two",
                            bbox=[1, 1, 80, 20],
                            is_text=True,
                            is_image=False,
                            is_html=False,
                        )
                    ],
                    screenshot=Image.new("RGB", (100, 100)),
                    json="{}",
                    markdown="",
                    markdown_images={},
                ),
            ],
            concatenated_markdown="",
        )

        case_dir = self._case_dir("mixed_records")
        artifact_dir = case_dir / "financial1-00" / "01_reference"
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "canonical_pages.json").write_text(
            json.dumps(
                [
                    {
                        "page": 1,
                        "sample_id": "financial1-00",
                        "width": 100,
                        "height": 100,
                        "blocks": [
                            {
                                "block_id": "financial1-00-heading",
                                "text": "BUY",
                                "bbox_px": [1, 1, 80, 20],
                            }
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )
        (artifact_dir / "semantic_overlay.json").write_text(
            json.dumps(
                [
                    {
                        "block_id": "financial1-00-heading",
                        "generated_role_name": "investment_rating_label",
                        "section_purpose": "thesis",
                        "role_confidence": 0.9,
                    }
                ]
            ),
            encoding="utf-8",
        )

        records = _build_search_records_for_parsed_doc("financial1", parsed_doc, case_dir)

        semantic_records = [record for record in records.values() if record.source_kind == "semantic"]
        fallback_records = [record for record in records.values() if record.source_kind == "fallback"]

        self.assertEqual(len(semantic_records), 1)
        self.assertEqual(len(fallback_records), 1)
        self.assertEqual(fallback_records[0].page, 1)

    def test_rerank_prefers_high_confidence_without_review_flag(self):
        high_confidence = SearchRecord(
            record_id="a",
            document="financial1",
            page=0,
            display_block_id="a",
            embedding_text="a",
            display_html="<div></div>",
            generic_role="body",
            domain_role=None,
            generated_role_name="headline",
            section_purpose="thesis",
            role_confidence=0.9,
            semantic_needs_review=False,
            source_kind="semantic",
        )
        low_confidence = SearchRecord(
            record_id="b",
            document="financial1",
            page=0,
            display_block_id="b",
            embedding_text="b",
            display_html="<div></div>",
            generic_role="body",
            domain_role=None,
            generated_role_name="headline",
            section_purpose="thesis",
            role_confidence=0.1,
            semantic_needs_review=True,
            source_kind="semantic",
        )

        ranked = _rerank_records([(low_confidence, 1.0), (high_confidence, 1.0)])

        self.assertEqual(ranked[0].record_id, "a")

    def test_format_search_output_includes_semantic_fields(self):
        record = SearchRecord(
            record_id="semantic:1",
            document="financial1",
            page=0,
            display_block_id="financial1-00-heading",
            embedding_text="x",
            display_html='<div id="financial1-00-heading"></div>',
            generic_role="section_heading",
            domain_role=None,
            generated_role_name="investment_rating_label",
            section_purpose="thesis",
            role_confidence=0.9,
            semantic_needs_review=False,
            source_kind="semantic",
        )

        output = _format_search_output([record])

        self.assertIn("generic_role=section_heading", output)
        self.assertIn("generated_role_name=investment_rating_label", output)
        self.assertIn("section_purpose=thesis", output)


if __name__ == "__main__":
    unittest.main()
