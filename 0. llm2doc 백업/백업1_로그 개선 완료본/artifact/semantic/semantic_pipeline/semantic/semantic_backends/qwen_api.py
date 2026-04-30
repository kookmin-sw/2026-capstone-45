import os
import json
import time
from typing import Dict, List, Tuple
from openai import OpenAI

from llm2doc.artifact.semantic.semantic_pipeline.semantic.semantic_types import BlockContextPayload, SemanticConfig

class QwenAPIBackend:
    backend_name = "qwen_api"

    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
        )

    @staticmethod
    def _build_messages(payload: BlockContextPayload, config: SemanticConfig) -> List[Dict[str, str]]:
        system_prompt = (
            "You infer semantic roles for OCR blocks from reference documents. "
            "Return JSON only. "
            "Your first output character must be '{' and your last output character must be '}'. "
            "Do not output thinking, analysis, markdown fences, or any text outside JSON. "
            "First infer an open generated role name that best describes the function of the block. "
            "Then provide legacy generic_role and domain_role only as compatibility hints using allowed enum values. "
            "The generated role name may be new, but generic_role and domain_role must follow the allowed lists. "
            "Use OCR labels as low-level hints, not as the final semantic answer. "
            "If uncertain, keep the generated role conservative, choose generic_role='unknown' or leave domain_role null, and set needs_review=true."
        )
        user_payload = {
            "task": {
                "prompt_version": config.prompt_version,
                "document_family": payload.document_family,
                "page_archetype": payload.page_archetype,
                "page_quality_score": payload.page_quality_score,
            },
            "allowed_roles": payload.allowed_roles,
            "target_block": payload.target_block,
            "page_context": payload.page_context,
            "local_neighbors": payload.local_neighbors,
            "structural_relations": payload.structural_relations,
            "response_schema": {
                "block_id": "string",
                "generated_role_name": "short snake_case role name describing the block function",
                "generated_role_description": "one short sentence describing the block function",
                "generated_parent_role_name": "short snake_case parent role name or null",
                "generated_role_level": "document | section | block",
                "generic_role": "allowed generic role",
                "domain_role": "allowed domain role or null",
                "role_confidence": "float between 0 and 1",
                "section_purpose": "string or null",
                "used_for_generation": "boolean or null",
                "reason": "one short sentence",
                "needs_review": "boolean",
            },
            "instructions": [
                "Do not explain outside JSON.",
                "Do not output a thinking process.",
                "Do not output markdown code fences.",
                "Start directly with a JSON object.",
                "Generate a semantic role name instead of copying OCR labels verbatim.",
                "Use OCR labels, raw text, relative layout, and structural relations together.",
                "Legacy generic_role and domain_role are compatibility fields only.",
                "If the domain role is uncertain, keep generic_role only and set domain_role to null.",
                "If the whole role is uncertain, keep generated_role_name conservative and set needs_review to true.",
            ],
        }
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
        ]
    def assign(self, payload: BlockContextPayload, config: SemanticConfig) -> Tuple[str, int]:
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
