import os
import json
import time
from typing import Dict, List, Tuple
from openai import OpenAI

from ..generation_types import GenerationConfig, SlotWritePayload

class QwenGenerationAPIBackend:
    backend_name = "qwen_generation_api"

    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
        )

    @staticmethod
    def _build_messages(payload: SlotWritePayload, config: GenerationConfig) -> List[Dict[str, str]]:
        system_prompt = (
            "You write document content to fill a reference template slot using supplied source facts only. "
            "Return JSON only. "
            "Your first output character must be '{' and your last output character must be '}'. "
            "Do not output thinking, markdown fences, or text outside JSON. "
            "Preserve the functional role of the reference slot, but do not copy the reference topic unless the slot says to preserve it. "
            "Do not invent numbers, companies, analyst names, dates, or claims that are absent from the source facts. "
            "If the facts are insufficient, keep the text conservative and set needs_review=true."
        )
        user_payload = {
            "task": {
                "prompt_version": config.prompt_version,
                "document_family": payload.document_family,
                "source_language": payload.source_language,
            },
            "slot": payload.slot,
            "selected_facts": payload.selected_facts,
            "style_tokens": payload.style_tokens,
            "response_schema": {
                "slot_id": "string",
                "text": "text for the slot only",
                "citations": ["fact_id", "fact_id"],
                "rationale": "one short sentence explaining which facts were used",
                "needs_review": "boolean",
            },
            "instructions": [
                "Use only the selected facts.",
                "Keep the text close to the target length.",
                "When the selected facts contain tabular values, you may turn them into prose.",
                "Return exactly one JSON object.",
            ],
        }
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
        ]
    def write_slot(self, payload: SlotWritePayload, config: GenerationConfig) -> Tuple[str, int]:
        messages = self._build_messages(payload, config)
        
        started_at = time.perf_counter()
        response = self.client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "qwen-plus") if config.model_name == "Qwen/Qwen3.5-9B" else (os.getenv("OPENAI_MODEL") or config.model_name or "qwen-plus"),
            messages=messages,
            temperature=config.temperature if config.do_sample else 0.0,
            max_tokens=config.max_new_tokens,
        )
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        
        return response.choices[0].message.content.strip(), latency_ms
