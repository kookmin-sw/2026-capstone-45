import json
from typing import Sequence
from openai.types.responses.response_input_param import FunctionCallOutput

from .util import image_as_data_uri
from .analyze_layout import ParsedDocument


class ToolFetchSourceDocument:
    def __init__(self, docs: Sequence[ParsedDocument]):
        super().__init__()

        self.docs: dict[str, ParsedDocument] = dict()

        for doc in docs:
            self.docs[doc.id] = doc

        self.description = {
            "type": "function",
            "name": "fetch_source_document",
            "description": "Fetch source document.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "The id of the document.",
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

    def invoke(self, param: str, call_id: str) -> FunctionCallOutput:
        param_parsed = json.loads(param)
        document_id: str = param_parsed["document_id"]
        page_id: int = param_parsed["page_id"]

        if document_id not in self.docs:
            return {
                "type": "function_call_output",
                "output": f"Error: {document_id} is not a valid document ID.",
                "call_id": call_id,
            }

        doc = self.docs[document_id]

        if len(doc.pages) < page_id:
            return {
                "type": "function_call_output",
                "output": f"Error: Given document only has page_id from 1 to {len(doc.pages) + 1}.",
                "call_id": call_id,
            }

        page = doc.pages[page_id - 1]
        page_html = page.to_structured_html()

        return {
            "type": "function_call_output",
            "output": f"Contents of document_id={document_id}, page_id={page_id}:\n{page_html}\n",
            "call_id": call_id,
        }

        # LMStudio 미지원
        # return {
        #     "type": "function_call_output",
        #     "output": [
        #         {
        #             "type": "input_text",
        #             "text": f"Contents of document_id={document_id}, page_id={page_id}:\n{page_html}\nScreenshot (for visual reference):\n",
        #         },
        #         {
        #             "type": "input_image",
        #             "image_url": image_as_data_uri(page.screenshot),
        #         },
        #     ],
        #     "call_id": call_id,
        # }
