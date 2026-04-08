import json
import time
from typing import Dict, List, Tuple

from ..generation_types import GenerationConfig, SlotWritePayload
from ..semantic_backends.qwen_transformers import QwenTransformersBackend


class QwenGenerationBackend:
    backend_name = "qwen_generation_transformers"

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
        user_prompt = (
            "Write content for one document slot.\n"
            "Use the supplied source facts only.\n"
            "Return one JSON object only.\n\n"
            "%s" % json.dumps(user_payload, ensure_ascii=False, indent=2)
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def write_slot(self, payload: SlotWritePayload, config: GenerationConfig) -> Tuple[str, int]:
        import torch

        tokenizer, model = QwenTransformersBackend._load(config.model_name, device=config.device)
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
