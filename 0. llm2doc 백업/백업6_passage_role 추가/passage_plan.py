import json
from typing import Any

from llm2doc.artifact.semantic import SemanticArtifact


def build_target_passage_plans(semantic_artifact: SemanticArtifact) -> list[dict[str, Any]]:
    location_map = _build_block_location_map(semantic_artifact)
    plans: list[dict[str, Any]] = []
    for passage in semantic_artifact.passages:
        block_layouts: list[dict[str, Any]] = []
        source_block_ids: list[str] = []
        output_block_ids: list[str] = []
        for block_id in passage.block_ids:
            location = location_map.get(block_id)
            if location is None:
                continue
            page_index, block_index, structural_kind, text = location
            target_block_id = f"target-page-{page_index}-block-{block_index}"
            output_block_id = f"output-page-{page_index}-block-{block_index}"
            normalized_text = " ".join(text.split())
            source_block_ids.append(target_block_id)
            output_block_ids.append(output_block_id)
            block_layouts.append(
                {
                    "output_block_id": output_block_id,
                    "source_block_id": target_block_id,
                    "structural_kind": structural_kind,
                    "target_text_chars": len(normalized_text),
                    "target_line_hint": max(1, text.count("\n") + 1) if normalized_text else 0,
                    "fill_requirement": _fill_requirement(len(normalized_text)),
                }
            )
        if not output_block_ids:
            continue
        plans.append(
            {
                "target_passage_id": f"target-{passage.passage_id}",
                "output_block_ids": output_block_ids,
                "source_block_ids": source_block_ids,
                "passage_role": getattr(passage, "passage_role", None) or passage.main_function,
                "block_layouts": block_layouts,
                "writing_goal": (
                    "Distribute selected source passage evidence across the fixed output blocks. "
                    "Use target_text_chars/fill_requirement as approximate slot budgets, not content to copy."
                ),
            }
        )
    return plans


def build_target_excluded_blocks(semantic_artifact: SemanticArtifact) -> list[dict[str, str]]:
    location_map = _build_block_location_map(semantic_artifact)
    text_map = {
        block.block_id: block.text
        for page in semantic_artifact.canonical_pages
        for block in page.blocks
    }
    excluded: list[dict[str, str]] = []
    for item in semantic_artifact.excluded_blocks:
        location = location_map.get(item.block_id)
        if location is None:
            continue
        page_index, block_index, _, _ = location
        excluded.append(
            {
                "output_block_id": f"output-page-{page_index}-block-{block_index}",
                "source_block_id": f"target-page-{page_index}-block-{block_index}",
                "text": text_map.get(item.block_id, ""),
                "reason": item.reason,
            }
        )
    return excluded


def build_target_passage_prompt_context(semantic_artifact: SemanticArtifact) -> str:
    plans = build_target_passage_plans(semantic_artifact)
    excluded_blocks = build_target_excluded_blocks(semantic_artifact)
    if not plans and not excluded_blocks:
        return ""
    payload = {
        "target_passage_plan": plans,
        "target_excluded_blocks": excluded_blocks,
    }
    return "\n".join(
        [
            "# Target Passage Plan",
            "",
            "Use this plan to preserve the target document's passage-level writing flow.",
            "Use target passages only for passage_role, layout, tone, format, and approximate length.",
            "Do not treat target passage topics, entities, numbers, years, table cell text, titles, or summaries as facts to preserve.",
            "If source evidence discusses a different concrete topic, retarget the output block to the source-backed topic while preserving the same passage_role.",
            "Each output_block_id is a fixed-position slot. Fill paragraph_or_meta slots with enough real text for their target_text_chars/fill_requirement budget.",
            "For multi-block passages, continue the narrative across consecutive output blocks; do not leave one block mostly empty while a later block starts far below.",
            "Do not use target_excluded_blocks to form retrieval queries.",
            "Still emit output_block_id entries for target_excluded_blocks when they exist in the target layout.",
            "For excluded blocks, choose empty, rewrite, or keep according to the new document context; do not blindly copy stale template text.",
            "",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )


def _fill_requirement(char_count: int) -> str:
    if char_count <= 0:
        return "empty_or_non_text"
    if char_count < 40:
        return "short_label_or_meta"
    if char_count < 140:
        return "short_paragraph"
    if char_count < 320:
        return "medium_paragraph"
    return "long_paragraph"


def _build_block_location_map(semantic_artifact: SemanticArtifact) -> dict[str, tuple[int, int, str, str]]:
    result: dict[str, tuple[int, int, str, str]] = {}
    for page_index, page in enumerate(semantic_artifact.canonical_pages, start=1):
        for block_index, block in enumerate(page.blocks, start=1):
            result[block.block_id] = (page_index, block_index, block.canonical_label, block.text)
    return result
