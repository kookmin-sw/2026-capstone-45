import json
import time
from typing import Dict, List, Tuple

from ..semantic_types import BlockContextPayload, SemanticConfig


class QwenTransformersBackend:
    backend_name = "qwen_transformers"
    _loaded_model_name = None
    _tokenizer = None
    _model = None

    @classmethod
    def _load(cls, model_name: str, device: str = "auto"):
        if cls._model is not None and cls._tokenizer is not None and cls._loaded_model_name == model_name:
            return cls._tokenizer, cls._model
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            trust_remote_code=True,
            torch_dtype="auto",
            device_map=device,
        )
        model.eval()
        cls._loaded_model_name = model_name
        cls._tokenizer = tokenizer
        cls._model = model
        return tokenizer, model

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
        user_prompt = (
            "Infer the semantic function of the target OCR block\n"
            "Use the surrounding context, OCR labels, raw geometry, and structural relations.\n"
            "Return only one JSON object.\n\n"
            "%s" % json.dumps(user_payload, ensure_ascii=False, indent=2)
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def assign(self, payload: BlockContextPayload, config: SemanticConfig) -> Tuple[str, int]:
        import torch

        tokenizer, model = self._load(config.model_name, device=config.device)
        messages = self._build_messages(payload, config)
        if getattr(tokenizer, "chat_template", None):
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        else:
            prompt = "%s\n\n%s" % (messages[0]["content"], messages[1]["content"])

        inputs = tokenizer(prompt, return_tensors="pt")
        device = next(model.parameters()).device
        inputs = {name: tensor.to(device) for name, tensor in inputs.items()}
        generation_kwargs = {
            "max_new_tokens": config.max_new_tokens,
            "do_sample": config.do_sample,
            "pad_token_id": tokenizer.pad_token_id or tokenizer.eos_token_id,
        }
        if config.do_sample:
            generation_kwargs["temperature"] = config.temperature

        started_at = time.perf_counter()
        with torch.no_grad():
            output_ids = model.generate(**inputs, **generation_kwargs)
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        generated_ids = output_ids[0][inputs["input_ids"].shape[1] :]
        response = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
        return response, latency_ms
