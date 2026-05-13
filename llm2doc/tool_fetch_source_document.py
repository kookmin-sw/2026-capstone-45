"""LLM이 원본 문서의 특정 페이지를 직접 조회할 수 있게 해주는 툴.

`search_source_document`가 후보 블록을 찾는 역할이라면, 이 툴은
정확한 문서/페이지를 지정해 전체 페이지 구조를 가져오는 역할을 맡는다.
"""

import json
import re

from typing import Any, Sequence

from llm2doc.artifact.ocr import OCRArtifact
from llm2doc.context.write import WriteContext


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "call"


class ToolFetchSourceDocument:
    def __init__(
        self,
        docs: Sequence[OCRArtifact],
        *,
        ctx: WriteContext | None = None,
        source_doc_infos: Sequence[dict[str, Any]] | None = None,
    ):
        """미리 파싱해 둔 문서를 문서 ID 기준으로 조회 가능하게 준비한다."""
        super().__init__()

        self.docs = docs
        self.ctx = ctx
        self.source_doc_infos = list(source_doc_infos or [])

        self.description = {
            "type": "function",
            "function": {
                "name": "fetch_source_document",
                "description": "Fetch source document.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "number",
                            "description": "The id of the document. Starts from 1.",
                        },
                        "page_id": {
                            "type": "number",
                            "description": "The page_id of the document. This is different from semantic page number (if any) and strictly counts up from 1.",
                        },
                    },
                    "required": ["document_id", "page_id"],
                    "additionalProperties": False,
                },
            },
        }

    async def invoke(self, param: str, call_id: str) -> dict[str, Any]:
        """LLM 함수 호출 포맷을 받아 페이지 HTML을 반환한다.

        입력 검증을 이 함수에서 모두 처리하므로, 잘못된 문서 ID나 페이지 번호가
        들어오더라도 예외를 터뜨리기보다 읽기 쉬운 오류 문자열을 돌려준다.
        """
        param_parsed = json.loads(param)
        doc_idx = int(param_parsed["document_id"]) - 1
        try:
            page_id = int(param_parsed["page_id"])
        except (TypeError, ValueError):
            return {
                "type": "function_call_output",
                "output": "Error: page_id must be an integer starting from 1.",
                "call_id": call_id,
            }

        if doc_idx < 0 or len(self.docs) <= doc_idx:
            return {
                "type": "function_call_output",
                "output": f"Error: {param_parsed['document_id']} is not a valid document ID.",
                "call_id": call_id,
            }

        doc = self.docs[doc_idx]

        if page_id < 1 or len(doc.pages) < page_id:
            return {
                "type": "function_call_output",
                "output": f"Error: Given document only has page_id from 1 to {len(doc.pages)}.",
                "call_id": call_id,
            }

        page = doc.pages[page_id - 1]
        page_html = page.to_structured_html()
        info = self.source_doc_infos[doc_idx] if doc_idx < len(self.source_doc_infos) else {}
        fetch_payload = {
            "tool_document_id": doc_idx + 1,
            "actual_doc_id": info.get("doc_id"),
            "display_name": info.get("display_name"),
            "page_id": page_id,
            "block_count": len(page.blocks),
            "call_id": call_id,
        }
        if self.ctx is not None and self.ctx.tracer is not None:
            safe_call_id = _safe_name(call_id)
            self.ctx.tracer.write_json(f"retrieval/fetch_{safe_call_id}.json", {**fetch_payload, "html": page_html})
            self.ctx.tracer.write_text(f"retrieval/fetch_{safe_call_id}.html", page_html)
            self.ctx.tracer.event("retrieval", "source_page_fetched", fetch_payload)

        return {
            "type": "function_call_output",
            "output": f"Contents of document_id={param_parsed['document_id']}, page_id={page_id}:\n{page_html}\n",
            "call_id": call_id,
        }
