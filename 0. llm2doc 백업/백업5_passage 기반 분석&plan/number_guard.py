import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag


REGEX_PAGE_HTML = re.compile(r"<page\b[^>]*>.*?</page>", re.IGNORECASE | re.DOTALL)
REGEX_DOCUMENT_HTML = re.compile(r"<document\b[^>]*>.*?</document>", re.IGNORECASE | re.DOTALL)
REGEX_SOURCE_PAGE_HTML = re.compile(r"<source_page\b[^>]*>.*?</source_page>", re.IGNORECASE | re.DOTALL)
REGEX_RESULT_BLOCK_ID = re.compile(r"^(?:output|target)-page-\d+-block-\d+$")
REGEX_NUMBER = re.compile(r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?(?![A-Za-z0-9_])")


@dataclass(frozen=True)
class NumberMatch:
    original: str
    normalized: str
    start: int
    end: int


def extract_source_evidence_text(input_items: Any) -> str:
    """Collect visible source evidence text from completed tool outputs."""
    fragments: list[str] = []
    for output in _iter_function_outputs(input_items):
        fragments.extend(_extract_output_fragments(output))
    for source_page in _iter_preflight_source_pages(input_items):
        fragments.append(_visible_text(source_page))
    return "\n".join(fragment for fragment in fragments if fragment.strip())


def extract_normalized_numbers(text: str) -> set[str]:
    return {match.normalized for match in iter_normalized_numbers(text)}


def extract_supported_source_numbers(text: str) -> tuple[set[str], set[str]]:
    exact_numbers = extract_normalized_numbers(text)
    decimal_truncation_aliases = _decimal_truncation_aliases(exact_numbers)
    decimal_integer_aliases = _decimal_integer_aliases(exact_numbers)
    unsigned_aliases = decimal_truncation_aliases | decimal_integer_aliases
    sign_aliases = _sign_aliases(exact_numbers | unsigned_aliases)
    aliases = unsigned_aliases | sign_aliases
    return exact_numbers | aliases, aliases


def iter_normalized_numbers(text: str) -> list[NumberMatch]:
    matches: list[NumberMatch] = []
    for match in REGEX_NUMBER.finditer(text or ""):
        normalized = normalize_number(match.group(0))
        if not normalized:
            continue
        matches.append(
            NumberMatch(
                original=match.group(0),
                normalized=normalized,
                start=match.start(),
                end=match.end(),
            )
        )
    return matches


def normalize_number(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    cleaned = cleaned.rstrip("%").replace(",", "").replace("+", "")
    if cleaned in {"", "-", "."}:
        return ""
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return ""
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), "f")


def sanitize_unsupported_numbers(
    document_html: str,
    source_text: str,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    source_numbers = extract_normalized_numbers(source_text)
    supported_source_numbers, source_number_aliases = extract_supported_source_numbers(source_text)
    if not source_text.strip():
        return (
            document_html,
            [],
            {
                "source_number_count": 0,
                "checked_item_count": 0,
                "blocked_item_count": 0,
                "unsupported_number_count": 0,
                "skipped": True,
                "reason": "source evidence text is empty",
            },
        )

    soup = BeautifulSoup(document_html, "lxml")
    details: list[dict[str, Any]] = []
    source_lines = _source_lines(source_text)
    checked_item_count = 0

    for block in soup.find_all("div", id=REGEX_RESULT_BLOCK_ID):
        if not isinstance(block, Tag):
            continue
        block_id = str(block.get("id", ""))
        tables = block.find_all("table")
        if tables:
            for table in tables:
                checked_item_count += _sanitize_table(
                    table,
                    block_id,
                    supported_source_numbers,
                    source_lines,
                    details,
                )
        else:
            for text_tag in block.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6"]):
                checked = _sanitize_text_tag(
                    text_tag,
                    block_id,
                    supported_source_numbers,
                    source_lines,
                    details,
                )
                checked_item_count += int(checked)

    document = soup.find("document")
    sanitized_html = str(document) if document is not None else str(soup)
    unsupported_number_count = sum(len(item["unsupported_numbers"]) for item in details)
    summary = {
        "source_number_count": len(source_numbers),
        "source_supported_number_count": len(supported_source_numbers),
        "source_number_alias_count": len(source_number_aliases),
        "checked_item_count": checked_item_count,
        "blocked_item_count": len(details),
        "unsupported_number_count": unsupported_number_count,
        "skipped": False,
    }
    return sanitized_html, details, summary


def group_number_guard_details(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for detail in details:
        block_id = str(detail.get("block_id") or "")
        if not block_id:
            block_id = "unknown"
        block = grouped.setdefault(
            block_id,
            {
                "block_id": block_id,
                "item_count": 0,
                "unsupported_number_count": 0,
                "unsupported_numbers": [],
                "source_excerpts": [],
                "items": [],
            },
        )
        unsupported_numbers = [str(number) for number in detail.get("unsupported_numbers", [])]
        block["item_count"] += 1
        block["unsupported_number_count"] += len(unsupported_numbers)
        block["unsupported_numbers"] = _dedupe([*block["unsupported_numbers"], *unsupported_numbers])
        block["source_excerpts"] = _dedupe(
            [*block["source_excerpts"], *[str(excerpt) for excerpt in detail.get("source_excerpts", [])]]
        )[:5]
        block["items"].append(detail)
    return list(grouped.values())


def build_number_guard_report(
    summary: dict[str, Any],
    details: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "summary": summary,
        "blocks": group_number_guard_details(details),
        "details": details,
    }


def _decimal_integer_aliases(numbers: set[str]) -> set[str]:
    aliases: set[str] = set()
    for value in numbers:
        if "." not in value:
            continue
        try:
            number = Decimal(value)
        except InvalidOperation:
            continue
        aliases.add(str(int(number)))
    return aliases


def _decimal_truncation_aliases(numbers: set[str]) -> set[str]:
    aliases: set[str] = set()
    for value in numbers:
        if "." not in value:
            continue
        sign = "-" if value.startswith("-") else ""
        unsigned = value[1:] if sign else value
        integer, fraction = unsigned.split(".", 1)
        max_removed_digits = min(2, len(fraction) - 1)
        for removed_digits in range(1, max_removed_digits + 1):
            kept_fraction = fraction[: len(fraction) - removed_digits]
            if kept_fraction:
                aliases.add(f"{sign}{integer}.{kept_fraction}")
    return aliases


def _sign_aliases(numbers: set[str]) -> set[str]:
    aliases: set[str] = set()
    for value in numbers:
        if value.startswith("-"):
            aliases.add(value[1:])
        else:
            aliases.add(f"-{value}")
    return aliases


def _iter_function_outputs(input_items: Any) -> list[str]:
    outputs: list[str] = []
    if not isinstance(input_items, list):
        return outputs
    for item in input_items:
        if isinstance(item, dict):
            if item.get("type") == "function_call_output":
                output = item.get("output")
                if isinstance(output, str):
                    outputs.append(output)
            continue
        if getattr(item, "type", None) == "function_call_output":
            output = getattr(item, "output", None)
            if isinstance(output, str):
                outputs.append(output)
    return outputs


def _iter_preflight_source_pages(input_items: Any) -> list[str]:
    pages: list[str] = []
    if not isinstance(input_items, list):
        return pages
    for item in input_items:
        if not isinstance(item, dict):
            continue
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if not isinstance(text, str) or "<source_page" not in text:
                continue
            pages.extend(REGEX_SOURCE_PAGE_HTML.findall(text))
    return pages


def _extract_output_fragments(output: str) -> list[str]:
    stripped = (output or "").strip()
    if not stripped or stripped.startswith("Error:"):
        return []

    html_fragments = REGEX_PAGE_HTML.findall(stripped) or REGEX_DOCUMENT_HTML.findall(stripped)
    if html_fragments:
        return [_visible_text(fragment) for fragment in html_fragments]

    preview_fragments: list[str] = []
    for line in stripped.splitlines():
        if "preview=" not in line:
            continue
        preview_fragments.append(line.split("preview=", 1)[1].strip())
    if preview_fragments:
        return [_visible_text(fragment) for fragment in preview_fragments]

    return [_visible_text(stripped)]


def _visible_text(value: str) -> str:
    soup = BeautifulSoup(value or "", "lxml")
    text = soup.get_text("\n", strip=True)
    return text if text else value


def _sanitize_table(
    table: Tag,
    block_id: str,
    source_numbers: set[str],
    source_lines: list[str],
    details: list[dict[str, Any]],
) -> int:
    rows = table.find_all("tr", recursive=False)
    if not rows:
        rows = table.find_all("tr")
    if not rows:
        return 0

    header_row_index, header_cells = _select_header_row(rows)
    checked = 0
    for row_index, row in enumerate(rows):
        cells = _row_cells(row)
        if not cells:
            continue
        row_label = _cell_text(cells[0])
        for col_index, cell in enumerate(cells):
            if row_index <= header_row_index or col_index == 0:
                continue
            text = _cell_text(cell)
            detected_numbers = _dedupe([match.normalized for match in iter_normalized_numbers(text)])
            if not detected_numbers:
                continue
            checked += 1
            unsupported_numbers = [number for number in detected_numbers if number not in source_numbers]
            if not unsupported_numbers:
                continue

            column_label = _cell_text(header_cells[col_index]) if col_index < len(header_cells) else ""
            details.append(
                {
                    "type": "unsupported_number",
                    "block_id": block_id,
                    "kind": "table_cell",
                    "text": text,
                    "result_text_before": text,
                    "result_text_after": "-",
                    "detected_numbers": detected_numbers,
                    "unsupported_numbers": unsupported_numbers,
                    "row_label": row_label,
                    "column_label": column_label,
                    "source_excerpts": _find_source_excerpts(
                        source_lines,
                        " ".join(part for part in [row_label, column_label, text] if part),
                    ),
                    "action": "empty_cell",
                }
            )
            cell.clear()
            cell.append("-")
    return checked


def _sanitize_text_tag(
    tag: Tag,
    block_id: str,
    source_numbers: set[str],
    source_lines: list[str],
    details: list[dict[str, Any]],
) -> bool:
    text = tag.get_text(" ", strip=True)
    detected_numbers = _dedupe([match.normalized for match in iter_normalized_numbers(text)])
    if not detected_numbers:
        return False

    unsupported_numbers = [number for number in detected_numbers if number not in source_numbers]
    if not unsupported_numbers:
        return True

    for node in list(tag.descendants):
        if isinstance(node, NavigableString):
            replaced = _replace_unsupported_numbers(str(node), set(unsupported_numbers))
            if replaced != str(node):
                node.replace_with(replaced)
    result_text_after = tag.get_text(" ", strip=True)

    details.append(
        {
            "type": "unsupported_number",
            "block_id": block_id,
            "kind": tag.name or "text",
            "text": text,
            "result_text_before": text,
            "result_text_after": result_text_after,
            "detected_numbers": detected_numbers,
            "unsupported_numbers": unsupported_numbers,
            "source_excerpts": _find_source_excerpts(source_lines, text),
            "action": "replace_numbers",
        }
    )
    return True


def _replace_unsupported_numbers(text: str, unsupported_numbers: set[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        normalized = normalize_number(match.group(0))
        if normalized in unsupported_numbers:
            return "-"
        return match.group(0)

    return REGEX_NUMBER.sub(replace, text)


def _row_cells(row: Tag) -> list[Tag]:
    return [cell for cell in row.find_all(["th", "td"], recursive=False) if isinstance(cell, Tag)]


def _select_header_row(rows: list[Tag]) -> tuple[int, list[Tag]]:
    row_cells = [_row_cells(row) for row in rows]
    max_cell_count = max((len(cells) for cells in row_cells), default=0)
    for index, cells in enumerate(row_cells):
        if len(cells) == max_cell_count and max_cell_count > 1:
            return index, cells
    return 0, row_cells[0] if row_cells else []


def _cell_text(cell: Tag) -> str:
    return cell.get_text(" ", strip=True)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _source_lines(source_text: str) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in (source_text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if len(line) < 8 or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def _find_source_excerpts(source_lines: list[str], query_text: str, *, limit: int = 3) -> list[str]:
    tokens = _keyword_tokens(query_text)
    if not tokens:
        return []

    scored: list[tuple[int, int, str]] = []
    for index, line in enumerate(source_lines):
        line_lower = line.lower()
        score = sum(1 for token in tokens if token.lower() in line_lower)
        if score <= 0:
            continue
        scored.append((score, index, line))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [_clip_excerpt(line) for _score, _index, line in scored[:limit]]


def _keyword_tokens(text: str) -> list[str]:
    token_text = re.sub(r"[·./_-]+", " ", text or "")
    raw_tokens = re.findall(r"[가-힣A-Za-z][가-힣A-Za-z]{1,}", token_text)
    stopwords = {
        "현재",
        "상황",
        "자료",
        "기준",
        "전망",
        "예상",
        "협상",
        "진행",
        "중",
    }
    tokens: list[str] = []
    seen: set[str] = set()
    for token in raw_tokens:
        cleaned = token.strip("·./_-").lower()
        if len(cleaned) < 2 or cleaned in stopwords or cleaned in seen:
            continue
        seen.add(cleaned)
        tokens.append(token.strip("·./_-"))
    return tokens[:12]


def _clip_excerpt(text: str, *, max_chars: int = 260) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
