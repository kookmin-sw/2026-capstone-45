"""Chroma 임베딩 검색을 이용하는 가장 단순한 벡터 검색 버전.

문서 블록의 순수 텍스트만 인덱싱하며, semantic overlay 같은 추가 문맥은
사용하지 않는다. 검색 품질은 비교적 단순하지만 구조가 직관적이라
실험용/기본형 구현으로 이해하기 쉽다.
"""

import json
import os
from typing import Any

import chromadb
import chromadb.errors
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from openai.types.responses.response_input_param import FunctionCallOutput

from .analyze_layout import LayoutAnalyzer


COLLECTION_NAME = "docs_v1_plain"
MIN_TEXT_LENGTH = 10
SEARCH_RESULT_LIMIT = 3
EMBED_BATCH_SIZE = 10


def make_collection(
    chroma: chromadb.RustClient,
    layout_analyzer: LayoutAnalyzer,
    docs: list[str],
):
    """주어진 문서들의 텍스트 블록을 Chroma 컬렉션에 적재한다.

    페이지와 블록 번호를 메타데이터로 저장해, 검색 후 어떤 원본 위치에서
    결과가 나왔는지 다시 추적할 수 있게 한다.
    """
    collection = chroma.create_collection(
        name=COLLECTION_NAME,
        embedding_function=OpenAIEmbeddingFunction(
            api_key=os.environ["OPENAI_EMBED_API_KEY"],
            api_base=os.environ["OPENAI_EMBED_BASE_URL"],
            model_name=os.environ["OPENAI_EMBED_MODEL"],
        ),
    )

    for doc in docs:
        parsed_doc = layout_analyzer(doc)

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, int | str]] = []

        for page_idx, page in enumerate(parsed_doc.pages):
            for block_idx, block in enumerate(page.blocks):
                if block.label not in {"text", "table"}:
                    continue

                text = (block.content or "").strip()
                if len(text) < MIN_TEXT_LENGTH:
                    continue

                ids.append(f"{doc}-{page_idx + 1}-{block_idx + 1}")
                documents.append(text)
                metadatas.append(
                    {
                        "document": doc,
                        "page": page_idx + 1,
                        "block": block_idx + 1,
                    }
                )

        if ids:
            for start in range(0, len(ids), EMBED_BATCH_SIZE):
                end = start + EMBED_BATCH_SIZE
                collection.add(
                    ids=ids[start:end],
                    documents=documents[start:end],
                    metadatas=metadatas[start:end],
                )

    return collection


class ToolSearchSourceDocumentPlain:
    def __init__(self, docs: list[str]):
        """컬렉션이 있으면 재사용하고, 없으면 전체 문서를 새로 인덱싱한다."""
        super().__init__()

        self.docs = docs
        self.description = {
            "type": "function",
            "name": "search_source_document",
            "description": "Search source document using plain block text only. Returns top-3 matching blocks among all source documents.",
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

        self.layout_analyzer = LayoutAnalyzer()
        all_docs = [
            name
            for name in os.listdir("data")
            if os.path.isdir(os.path.join("data", name))
        ]
        all_docs.sort()

        self.chroma = chromadb.RustClient(path="debug_chromadb_cache_plain")
        try:
            self.collection = self.chroma.get_collection(
                name=COLLECTION_NAME,
                embedding_function=OpenAIEmbeddingFunction(
                    api_key=os.environ["OPENAI_EMBED_API_KEY"],
                    api_base=os.environ["OPENAI_EMBED_BASE_URL"],
                    model_name=os.environ["OPENAI_EMBED_MODEL"],
                ),
            )
        except chromadb.errors.NotFoundError:
            self.collection = make_collection(
                self.chroma,
                self.layout_analyzer,
                all_docs,
            )

    def invoke(self, param: str, call_id: str) -> FunctionCallOutput:
        """LLM function-call 규약을 일반 검색 함수로 연결하는 진입점."""
        param_parsed = json.loads(param)
        query: str = param_parsed["query"]
        output = self.invoke_raw(query)
        return {
            "type": "function_call_output",
            "output": output,
            "call_id": call_id,
        }

    def invoke_raw(self, query: str) -> str:
        """질의를 Chroma에 전달하고 사람이 읽기 쉬운 문자열로 포맷팅한다."""
        if 1 < len(self.docs):
            where_cond: Any = {"$or": [{"document": x} for x in self.docs]}
        elif 0 < len(self.docs):
            where_cond = {"document": self.docs[0]}
        else:
            raise ValueError("document list is empty")

        print(f"[search_source_document_plain] {query}")

        result = self.collection.query(
            query_texts=[query],
            n_results=SEARCH_RESULT_LIMIT,
            where=where_cond,
        )

        output = "Search result:"

        result_documents = result.get("documents") or [[]]
        result_metadatas = result.get("metadatas") or [[]]

        for idx, (content, metadata) in enumerate(
            zip(result_documents[0], result_metadatas[0]),
            start=1,
        ):
            output += (
                f"\nMatch #{idx}: document_id={metadata['document']}, "
                f"page_id={metadata['page']}, block_id={metadata['block']}\n"
            )
            output += f"{content}\n"

        return output

    def dispose(self) -> None:
        """내부에서 들고 있는 LayoutAnalyzer 자원을 정리한다."""
        self.layout_analyzer.dispose()


def main():
    from dotenv import load_dotenv

    load_dotenv()
    tool = ToolSearchSourceDocumentPlain(["financial2"])
    try:
        print(tool.invoke_raw("What is KMX?"))
    finally:
        tool.dispose()


if __name__ == "__main__":
    main()
