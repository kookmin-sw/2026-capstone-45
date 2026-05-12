import json
import os
import time
from typing import Any

from openai import OpenAI

from llm2doc.artifact.semantic.semantic_pipeline.semantic.semantic_types import SemanticConfig


SYSTEM_PROMPT = """
You group OCR blocks into semantic passages.

A passage is a coherent meaning unit useful for rewriting, retrieval, or evidence transfer.
A passage may include heading, body, table, chart, caption, and footnote blocks if they jointly express one idea.
Do not group blocks only because they are visually close.
Do not merge repeated headers, footers, page numbers, or decorative blocks into main content passages.
Use non_content_hints as weak evidence only.
Do not automatically exclude a block only because it has non_content_hints.
Every content block must appear in exactly one passage.
Return excluded_blocks for blocks that are not useful as retrieval or rewriting units.
If a block may need to be rewritten for the target document, keep it in a content passage.

Return JSON only.
Do not use markdown fences.
Do not invent block ids.
""".strip()


class PassageAPIBackend:
    backend_name = "qwen_api"

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_LITE_API_KEY"),
            base_url=os.getenv("OPENAI_LITE_BASE_URL"),
        )

    def group(self, payload: dict[str, Any], config: SemanticConfig) -> tuple[str, int]:
        user_payload = {
            "task": {
                "prompt_version": "passage-semantic-v1",
                "page": payload["page"],
            },
            "page_layout_hints": payload["page_layout_hints"],
            "blocks": payload["blocks"],
            "attachment_hints": payload["attachment_hints"],
            "instructions": [
                "Group only block_ids provided in blocks.",
                "Do not create cross-page passages.",
                "Use excluded_blocks only for blocks that are not useful retrieval or rewriting units.",
                "Every content_eligible block must be either in exactly one passage or in excluded_blocks.",
            ],
            "response_schema": {
                "passages": [
                    {
                        "block_ids": ["string"],
                        "title": "short passage title",
                        "summary": "short passage summary",
                        "main_function": "free text description of the passage function",
                    }
                ],
                "excluded_blocks": [{"block_id": "string", "reason": "short free text reason"}],
            },
        }
        started_at = time.perf_counter()
        response = self.client.chat.completions.create(
            model=(
                os.getenv("OPENAI_MODEL", "qwen-plus")
                if config.model_name == "Qwen/Qwen3.5-9B"
                else (os.getenv("OPENAI_MODEL") or config.model_name or "qwen-plus")
            ),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            temperature=config.temperature if config.do_sample else 0.0,
            max_tokens=max(config.max_new_tokens, 1200),
        )
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        return response.choices[0].message.content.strip(), latency_ms
