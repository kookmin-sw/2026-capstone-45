import os
import json
import chromadb
import chromadb.errors
from typing import Any
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from openai.types.responses.response_input_param import FunctionCallOutput

from .util import validate_type
from .analyze_layout import LayoutAnalyzer, ParsedDocument


def make_collection(collection: chromadb.Collection, layout_analyzer: LayoutAnalyzer):
    metadatas = []
    ids = []
    texts = []

    for doc in os.listdir("data"):
        if not os.path.isdir(f"data/{doc}"):
            continue

        layout = layout_analyzer(doc)

        for i, page in enumerate(layout.pages):
            for j, block in enumerate(page.blocks):
                if block.label not in {"text", "table"}:
                    continue
                if len(block.content.strip()) < 10:
                    continue

                ids.append(f"{doc}-{i}-{j}")
                texts.append(block.content)
                metadatas.append(
                    {
                        "document": doc,
                        "page": i,
                        "block": j,
                    }
                )

    collection.add(ids, documents=texts, metadatas=metadatas)


class ToolSearchSourceDocument:
    def __init__(self, docs: list[str]):
        super().__init__()

        self.docs = docs
        self.parsed_docs: dict[str, ParsedDocument] = dict()

        layout_analyzer = LayoutAnalyzer()
        for doc in self.docs:
            self.parsed_docs[doc] = layout_analyzer(doc)

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

        self.chroma = chromadb.RustClient(path="debug_chromadb_cache")
        try:
            self.collection = self.chroma.get_collection(name="docs_v1", embedding_function=embedding_function)
        except chromadb.errors.NotFoundError:
            self.collection = self.chroma.create_collection(name="docs_v1", embedding_function=embedding_function)
            make_collection(self.collection, layout_analyzer)

        layout_analyzer.dispose()
        del layout_analyzer

    def invoke(self, param: str, call_id: str) -> FunctionCallOutput:
        param_parsed = json.loads(param)
        query: str = param_parsed["query"]

        output = self.invoke_raw(query)
        return {"type": "function_call_output", "output": output, "call_id": call_id}

    def invoke_raw(self, query: str) -> str:
        if 1 < len(self.docs):
            where_cond: Any = {"$or": [{"document": x} for x in self.docs]}
        elif 0 < len(self.docs):
            where_cond = {"document": self.docs[0]}
        else:
            raise ValueError("document list is empty")

        print(f"[검색] {query}")

        results = self.collection.query(
            query_texts=[query],
            n_results=3,
            where=where_cond,
        )

        assert results["metadatas"] is not None

        output = ["Search result:"]

        for i, metadata in enumerate(results["metadatas"][0]):
            doc = validate_type(metadata["document"], str)
            page = validate_type(metadata["page"], int)
            block = validate_type(metadata["block"], int)

            parsed_page = self.parsed_docs[doc].pages[page]
            parsed_block = parsed_page.blocks[block]

            output.append(f"Match #{i + 1}: document_id={doc}, page_id={page + 1}, block_id={block + 1}")
            output.append(
                parsed_block.to_structured_html(parsed_page, block_id=f"{doc}-page-{page + 1}-block-{block + 1}")
            )
            output.append("")

        return "\n".join(output)


def main():
    tool = ToolSearchSourceDocument(["financial2"])
    print(tool.invoke_raw("What is KMX?"))


if __name__ == "__main__":
    main()
