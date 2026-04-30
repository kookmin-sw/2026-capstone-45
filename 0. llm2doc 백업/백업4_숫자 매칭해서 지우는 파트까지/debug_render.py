import re
from typing import Any

from bs4 import BeautifulSoup


REGEX_OUTPUT_BLOCK_ID = re.compile(r"^output-page-(\d+)-block-(\d+)$")


def refresh_final_render_payload(final_render: dict[str, Any], document_html: str) -> tuple[dict[str, Any], dict[str, int]]:
    """Update rendered block HTML from a generated <document> block.

    This is intended for debug runs where final HTML was post-processed after
    rendering. It does not re-rasterize page backgrounds; it updates the overlay
    HTML blocks in final_render.json to match final_document_response.html.
    """
    block_html_by_render_id = _extract_render_block_html(document_html)
    updated = 0
    missing = 0

    for page in final_render.get("pages", []):
        if not isinstance(page, dict):
            continue
        for block in page.get("blocks", []):
            if not isinstance(block, dict):
                continue
            render_id = str(block.get("id") or "")
            if render_id in block_html_by_render_id:
                block["html"] = block_html_by_render_id[render_id]
                updated += 1
            else:
                missing += 1

    summary = {
        "html_block_count": len(block_html_by_render_id),
        "updated_render_block_count": updated,
        "missing_render_block_count": missing,
    }
    return final_render, summary


def _extract_render_block_html(document_html: str) -> dict[str, str]:
    soup = BeautifulSoup(document_html, "lxml")
    result: dict[str, str] = {}
    for block in soup.find_all("div", id=REGEX_OUTPUT_BLOCK_ID):
        output_id = str(block.get("id") or "")
        match = REGEX_OUTPUT_BLOCK_ID.match(output_id)
        if match is None:
            continue
        page_index = int(match.group(1))
        block_index = int(match.group(2)) - 1
        result[f"page-{page_index}-block-{block_index}"] = block.decode_contents()
    return result
