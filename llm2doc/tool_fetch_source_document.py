"""LLM이 원본 문서의 특정 페이지를 직접 조회할 수 있게 해주는 툴.

`search_source_document`가 후보 블록을 찾는 역할이라면, 이 툴은
정확한 문서/페이지를 지정해 전체 페이지 구조를 가져오는 역할을 맡는다.
"""

import json

from typing import Sequence
from openai.types.responses.response_input_param import FunctionCallOutput

from llm2doc.artifact.ocr import OCRArtifact


class ToolFetchSourceDocument:
    def __init__(self, docs: Sequence[OCRArtifact]):
        """미리 파싱해 둔 문서를 문서 ID 기준으로 조회 가능하게 준비한다."""
        super().__init__()

        self.docs = docs

        self.description = {
            "type": "function",
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
        }

    async def invoke(self, param: str, call_id: str) -> FunctionCallOutput:
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

        return {
            "type": "function_call_output",
            "output": f"Contents of document_id={param_parsed['document_id']}, page_id={page_id}:\n{page_html}\n",
            "call_id": call_id,
        }
