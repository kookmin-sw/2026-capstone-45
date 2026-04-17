"""가장 단순한 형태의 원본 문서 검색 도구.

이 버전은 임베딩/벡터 DB에 의존하지 않고, OCR로 추출한 블록 텍스트를
토큰 단위로 비교해 상위 후보를 찾는다. 외부 임베딩 서비스가 불안정할 때
최소 기능을 유지하기 위한 안정적인 fallback 용도로 적합하다.
"""

import json
import re
from dataclasses import dataclass

from openai.types.responses.response_input_param import FunctionCallOutput

from .analyze_layout import LayoutAnalyzer, ParsedDocument
from .util import validate_type


REGEX_TOKEN = re.compile(r"[0-9A-Za-z\u3131-\u318E\uAC00-\uD7A3]+")
MIN_TEXT_LENGTH = 10
SEARCH_RESULT_LIMIT = 3


@dataclass(slots=True)
class SearchEntry:
    """검색 대상이 되는 단일 블록 정보를 보관한다."""

    document: str
    page: int
    block: int
    text: str
    tokens: set[str]


def _tokenize(text: str) -> set[str]:
    """한글/영문/숫자 토큰만 뽑아 소문자 집합으로 정규화한다."""
    return {token.lower() for token in REGEX_TOKEN.findall(text)}


def _score_entry(query: str, query_tokens: set[str], entry: SearchEntry) -> tuple[float, int, int, int, str]:
    """질의와 블록 사이의 단순 lexical 점수를 계산한다.

    정렬은 오름차순으로 수행되므로, 겹치는 토큰 수가 많을수록 더 작은 값이
    되도록 음수로 뒤집어 반환한다. 같은 점수라면 부분 문자열 일치 여부,
    길이 차이, 페이지 순서 등을 tie-breaker로 사용한다.
    """
    overlap = len(query_tokens & entry.tokens)
    substring_bonus = 1 if query and query.lower() in entry.text.lower() else 0
    length_penalty = abs(len(entry.text) - max(len(query), 1))
    return (-float(overlap + (substring_bonus * 2)), -substring_bonus, length_penalty, entry.page, entry.document)


class ToolSearchSourceDocument:
    def __init__(self, docs: list[str]):
        """검색 대상 문서의 모든 블록을 메모리 위 인덱스로 준비한다."""
        super().__init__()

        self.docs = docs
        self.parsed_docs: dict[str, ParsedDocument] = {}
        self.entries: list[SearchEntry] = []

        layout_analyzer = LayoutAnalyzer()
        try:
            for doc in self.docs:
                parsed_doc = layout_analyzer(doc)
                self.parsed_docs[doc] = parsed_doc

                for page_idx, page in enumerate(parsed_doc.pages):
                    for block_idx, block in enumerate(page.blocks):
                        if block.label not in {"text", "table"}:
                            continue

                        text = (block.content or "").strip()
                        if len(text) < MIN_TEXT_LENGTH:
                            continue

                        self.entries.append(
                            SearchEntry(
                                document=doc,
                                page=page_idx,
                                block=block_idx,
                                text=text,
                                tokens=_tokenize(text),
                            )
                        )
        finally:
            layout_analyzer.dispose()
            del layout_analyzer

        self.description = {
            "type": "function",
            "name": "search_source_document",
            "description": (
                "Search source document using lexical block matching. "
                "Returns top-3 matching pages among all source documents."
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

    def invoke(self, param: str, call_id: str) -> FunctionCallOutput:
        """OpenAI function-call 형식의 입력을 받아 검색 결과 문자열을 반환한다."""
        param_parsed = json.loads(param)
        query: str = param_parsed["query"]

        output = self.invoke_raw(query)
        return {"type": "function_call_output", "output": output, "call_id": call_id}

    def invoke_raw(self, query: str) -> str:
        """질의를 받아 상위 블록을 구조화된 HTML 조각과 함께 반환한다."""
        if not self.docs:
            raise ValueError("document list is empty")

        print(f"[search_source_document_original] {query}")
        query_tokens = _tokenize(query)

        ranked_entries = sorted(
            self.entries,
            key=lambda entry: _score_entry(query, query_tokens, entry),
        )[:SEARCH_RESULT_LIMIT]

        output = ["Search result:"]

        for i, entry in enumerate(ranked_entries, start=1):
            doc = validate_type(entry.document, str)
            page = validate_type(entry.page, int)
            block = validate_type(entry.block, int)

            parsed_page = self.parsed_docs[doc].pages[page]
            parsed_block = parsed_page.blocks[block]

            output.append(
                f"Match #{i}: document_id={doc}, page_id={page + 1}, block_id={block + 1}"
            )
            output.append(
                parsed_block.to_structured_html(
                    parsed_page, block_id=f"{doc}-page-{page + 1}-block-{block + 1}"
                )
            )
            output.append("")

        if len(output) == 1:
            output.append("No matching source blocks found.")

        return "\n".join(output)


def main():
    from dotenv import load_dotenv

    load_dotenv()
    tool = ToolSearchSourceDocument(["financial2"])
    print(tool.invoke_raw("What is KMX?"))


if __name__ == "__main__":
    main()
