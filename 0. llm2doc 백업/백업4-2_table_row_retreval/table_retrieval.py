import json
import re
from dataclasses import dataclass
from typing import Any, Sequence

from bs4 import BeautifulSoup
from bs4.element import Tag

from llm2doc.artifact.ocr import OCRArtifact, OCRBlock, OCRPage
from llm2doc.context.write import WriteContext
from llm2doc.tool_search_source_document import RetrievalCandidate, ToolSearchSourceDocument


MAX_QUERY_TERMS = 8
MAX_FALLBACK_ROWS_PER_TABLE = 5
MAX_CANDIDATE_PAGES_PER_QUERY = 3
MAX_SOURCE_PAGES_PER_TABLE = 2
MAX_PREFETCH_SOURCE_PAGES = 8

REGEX_HAS_LETTER = re.compile(r"[A-Za-z가-힣]")
REGEX_YEAR_LABEL = re.compile(r"^\d{2,4}(?:[./-]\d{1,2})?(?:[A-Za-z])?$")
REGEX_TAG = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class TableProfile:
    target_block_id: str
    output_block_id: str
    page_id: int
    block_index: int
    title_hint: str
    row_labels: list[str]
    column_labels: list[str]
    query_terms: list[str]
    primary_query: str

    def to_summary(self) -> dict[str, Any]:
        return {
            "target_block_id": self.target_block_id,
            "output_block_id": self.output_block_id,
            "page_id": self.page_id,
            "block_index": self.block_index,
            "title_hint": self.title_hint,
            "row_labels": self.row_labels,
            "column_labels": self.column_labels,
            "query_terms": self.query_terms,
            "primary_query": self.primary_query,
        }


@dataclass(slots=True)
class PageRef:
    document_id: int
    page_id: int

    @property
    def key(self) -> tuple[int, int]:
        return (self.document_id, self.page_id)


@dataclass(slots=True)
class PrefetchedPage:
    document_id: int
    page_id: int
    html: str
    display_name: str | None = None
    actual_doc_id: int | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "page_id": self.page_id,
            "actual_doc_id": self.actual_doc_id,
            "display_name": self.display_name,
            "html_preview": _preview_text(self.html),
        }


def build_table_inventory(target_doc: OCRArtifact, query: str = "") -> list[TableProfile]:
    profiles: list[TableProfile] = []
    for page_index, page in enumerate(target_doc.pages, start=1):
        for block_index, block in enumerate(page.blocks, start=1):
            if not _looks_like_table_block(block):
                continue

            target_block_id = f"target-page-{page_index}-block-{block_index}"
            output_block_id = f"output-page-{page_index}-block-{block_index}"
            parsed = _parse_table_block(block.content)
            if parsed is None:
                continue

            row_labels, column_labels, table_title = parsed
            informative_rows = [label for label in row_labels if _is_informative_label(label)]
            if len(informative_rows) < 2:
                continue

            title_hint = table_title or _nearby_title_hint(page, block_index - 1)
            query_terms = _select_query_terms(informative_rows)
            primary_query = build_primary_query(query, title_hint, query_terms)
            profiles.append(
                TableProfile(
                    target_block_id=target_block_id,
                    output_block_id=output_block_id,
                    page_id=page_index,
                    block_index=block_index,
                    title_hint=title_hint,
                    row_labels=informative_rows,
                    column_labels=column_labels,
                    query_terms=query_terms,
                    primary_query=primary_query,
                )
            )
    return profiles


def build_primary_query(query: str, title_hint: str, query_terms: Sequence[str]) -> str:
    parts = [_clean_text(query), _clean_text(title_hint), *[_clean_text(term) for term in query_terms]]
    return " ".join(_dedupe([part for part in parts if part]))


def build_fallback_query(profile: TableProfile, missing_row: str) -> str:
    anchor_terms = profile.query_terms[:2]
    parts = [_clean_text(profile.title_hint), _clean_text(missing_row), *anchor_terms]
    return " ".join(_dedupe([part for part in parts if part]))


def compute_page_coverage(profile: TableProfile, source_page_html: str) -> dict[str, Any]:
    page_text = _compact_text(_visible_text(source_page_html))
    matched_rows: list[str] = []
    missing_rows: list[str] = []
    for row_label in profile.row_labels:
        compact = _compact_text(row_label)
        if compact and compact in page_text:
            matched_rows.append(row_label)
        else:
            missing_rows.append(row_label)

    total = len(profile.row_labels)
    coverage_ratio = len(matched_rows) / total if total else 0.0
    if coverage_ratio >= 0.6:
        status = "found"
    elif matched_rows:
        status = "partial"
    else:
        status = "missing"

    return {
        "target_block_id": profile.target_block_id,
        "output_block_id": profile.output_block_id,
        "status": status,
        "matched_rows": matched_rows,
        "missing_rows": missing_rows,
        "coverage_ratio": round(coverage_ratio, 4),
    }


async def run_table_retrieval_preflight(
    *,
    ctx: WriteContext | None,
    query: str,
    target_doc: OCRArtifact,
    src_docs: Sequence[OCRArtifact],
    search_tool: ToolSearchSourceDocument,
    source_doc_infos: Sequence[dict[str, Any]] | None = None,
    component: str = "create_document",
) -> dict[str, Any]:
    profiles = build_table_inventory(target_doc, query=query)
    report: dict[str, Any] = {
        "target_tables": [profile.to_summary() for profile in profiles],
        "table_coverage": [],
        "source_pages": [],
        "limits": {
            "max_query_terms": MAX_QUERY_TERMS,
            "max_fallback_rows_per_table": MAX_FALLBACK_ROWS_PER_TABLE,
            "max_candidate_pages_per_query": MAX_CANDIDATE_PAGES_PER_QUERY,
            "max_source_pages_per_table": MAX_SOURCE_PAGES_PER_TABLE,
            "max_prefetch_source_pages": MAX_PREFETCH_SOURCE_PAGES,
        },
    }
    await _append_trace(
        ctx,
        {
            "type": "target_table_inventory_created",
            "component": component,
            "table_count": len(profiles),
            "tables": [profile.to_summary() for profile in profiles],
        },
    )

    fetched_page_cache: dict[tuple[int, int], str] = {}
    selected_pages: dict[tuple[int, int], PrefetchedPage] = {}

    for profile in profiles:
        coverage = await _resolve_table_coverage(
            ctx=ctx,
            profile=profile,
            src_docs=src_docs,
            search_tool=search_tool,
            fetched_page_cache=fetched_page_cache,
            selected_pages=selected_pages,
            source_doc_infos=source_doc_infos,
            component=component,
        )
        report["table_coverage"].append(coverage)

    report["source_pages"] = [page.to_summary() for page in selected_pages.values()]
    report["context_text"] = build_table_retrieval_context(report, selected_pages.values())
    await _append_trace(
        ctx,
        {
            "type": "table_coverage_completed",
            "component": component,
            "table_count": len(report["table_coverage"]),
            "source_page_count": len(report["source_pages"]),
        },
    )
    return report


def build_table_retrieval_context(
    report: dict[str, Any],
    source_pages: Sequence[PrefetchedPage],
) -> str:
    if not report.get("target_tables"):
        return ""

    target_tables = report.get("target_tables", [])
    table_coverage = report.get("table_coverage", [])
    source_page_summaries = [page.to_summary() for page in source_pages]
    lines = [
        "# Preflight Table Retrieval Context",
        "",
        "This context was generated before writing.",
        "Use it as source evidence guidance for target tables.",
        "",
        "## Target Tables",
        json.dumps(target_tables, ensure_ascii=False, indent=2),
        "",
        "## Table Coverage",
        json.dumps(table_coverage, ensure_ascii=False, indent=2),
        "",
        "## Prefetched Source Page Summary",
        json.dumps(source_page_summaries, ensure_ascii=False, indent=2),
        "",
        "## Prefetched Source Pages",
    ]
    for page in source_pages:
        lines.append(f'<source_page document_id="{page.document_id}" page_id="{page.page_id}">')
        lines.append(page.html)
        lines.append("</source_page>")
        lines.append("")
    lines.extend(
        [
            "## Rules",
            "- Fill matched_rows only from the attached source pages.",
            '- Keep missing_rows as "-"; do not infer or estimate them.',
            "- target_block_id identifies the template block only.",
            "- In the final HTML, use output_block_id and output-page-* ids. Do not reuse target-page-* ids.",
            "- Preserve the target table structure.",
            "- Do not mix values from unrelated tables, units, years, or criteria.",
        ]
    )
    return "\n".join(lines).strip()


async def _resolve_table_coverage(
    *,
    ctx: WriteContext | None,
    profile: TableProfile,
    src_docs: Sequence[OCRArtifact],
    search_tool: ToolSearchSourceDocument,
    fetched_page_cache: dict[tuple[int, int], str],
    selected_pages: dict[tuple[int, int], PrefetchedPage],
    source_doc_infos: Sequence[dict[str, Any]] | None,
    component: str,
) -> dict[str, Any]:
    selected_for_table: dict[tuple[int, int], dict[str, Any]] = {}
    primary_candidates = await search_tool.search_candidates(profile.primary_query)
    await _append_trace(
        ctx,
        {
            "type": "table_primary_search_completed",
            "component": component,
            "target_block_id": profile.target_block_id,
            "output_block_id": profile.output_block_id,
            "query": profile.primary_query,
            "candidate_count": len(primary_candidates),
        },
    )

    await _inspect_candidate_pages(
        ctx=ctx,
        profile=profile,
        candidates=primary_candidates,
        src_docs=src_docs,
        fetched_page_cache=fetched_page_cache,
        selected_pages=selected_pages,
        selected_for_table=selected_for_table,
        source_doc_infos=source_doc_infos,
        component=component,
    )

    aggregate = _aggregate_table_coverage(profile, selected_for_table.values())
    fallback_queries: list[dict[str, Any]] = []
    for missing_row in aggregate["missing_rows"][:MAX_FALLBACK_ROWS_PER_TABLE]:
        if len(selected_for_table) >= MAX_SOURCE_PAGES_PER_TABLE:
            break
        if len(selected_pages) >= MAX_PREFETCH_SOURCE_PAGES:
            break

        fallback_query = build_fallback_query(profile, missing_row)
        fallback_candidates = await search_tool.search_candidates(fallback_query)
        fallback_queries.append(
            {
                "row_label": missing_row,
                "query": fallback_query,
                "candidate_count": len(fallback_candidates),
            }
        )
        await _append_trace(
            ctx,
            {
                "type": "table_row_fallback_search_completed",
                "component": component,
                "target_block_id": profile.target_block_id,
                "output_block_id": profile.output_block_id,
                "row_label": missing_row,
                "query": fallback_query,
                "candidate_count": len(fallback_candidates),
            },
        )
        await _inspect_candidate_pages(
            ctx=ctx,
            profile=profile,
            candidates=fallback_candidates,
            src_docs=src_docs,
            fetched_page_cache=fetched_page_cache,
            selected_pages=selected_pages,
            selected_for_table=selected_for_table,
            source_doc_infos=source_doc_infos,
            component=component,
        )
        aggregate = _aggregate_table_coverage(profile, selected_for_table.values())
        if aggregate["status"] == "found":
            break

    aggregate.update(
        {
            "primary_query": profile.primary_query,
            "fallback_queries": fallback_queries,
            "source_pages": [
                {
                    "document_id": document_id,
                    "page_id": page_id,
                    "matched_rows": coverage["matched_rows"],
                    "coverage_ratio": coverage["coverage_ratio"],
                }
                for (document_id, page_id), coverage in selected_for_table.items()
            ],
        }
    )
    return aggregate


async def _inspect_candidate_pages(
    *,
    ctx: WriteContext | None,
    profile: TableProfile,
    candidates: Sequence[RetrievalCandidate],
    src_docs: Sequence[OCRArtifact],
    fetched_page_cache: dict[tuple[int, int], str],
    selected_pages: dict[tuple[int, int], PrefetchedPage],
    selected_for_table: dict[tuple[int, int], dict[str, Any]],
    source_doc_infos: Sequence[dict[str, Any]] | None,
    component: str,
) -> None:
    for page_ref in _candidate_page_refs(candidates)[:MAX_CANDIDATE_PAGES_PER_QUERY]:
        if page_ref.key in selected_for_table:
            continue
        html = _get_source_page_html(src_docs, page_ref, fetched_page_cache)
        if html is None:
            continue
        coverage = compute_page_coverage(profile, html)
        if not coverage["matched_rows"]:
            continue
        if len(selected_for_table) >= MAX_SOURCE_PAGES_PER_TABLE:
            break
        if page_ref.key not in selected_pages and len(selected_pages) >= MAX_PREFETCH_SOURCE_PAGES:
            break

        selected_for_table[page_ref.key] = coverage
        if page_ref.key not in selected_pages:
            page = _make_prefetched_page(page_ref, html, source_doc_infos)
            selected_pages[page_ref.key] = page
            await _append_trace(
                ctx,
                {
                    "type": "table_source_page_prefetched",
                    "component": component,
                    "target_block_id": profile.target_block_id,
                    "output_block_id": profile.output_block_id,
                    "document_id": page_ref.document_id,
                    "page_id": page_ref.page_id,
                    "matched_rows": coverage["matched_rows"],
                    "coverage_ratio": coverage["coverage_ratio"],
                },
            )


def _aggregate_table_coverage(
    profile: TableProfile,
    page_coverages: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    matched_rows = _dedupe(
        [
            row
            for coverage in page_coverages
            for row in coverage.get("matched_rows", [])
            if isinstance(row, str)
        ]
    )
    missing_rows = [row for row in profile.row_labels if row not in set(matched_rows)]
    total = len(profile.row_labels)
    coverage_ratio = len(matched_rows) / total if total else 0.0
    if coverage_ratio >= 0.6:
        status = "found"
    elif matched_rows:
        status = "partial"
    else:
        status = "missing"
    return {
        "target_block_id": profile.target_block_id,
        "output_block_id": profile.output_block_id,
        "status": status,
        "matched_rows": matched_rows,
        "missing_rows": missing_rows,
        "coverage_ratio": round(coverage_ratio, 4),
    }


def _candidate_page_refs(candidates: Sequence[RetrievalCandidate]) -> list[PageRef]:
    refs: list[PageRef] = []
    seen: set[tuple[int, int]] = set()
    for candidate in candidates:
        ref = PageRef(candidate.record.doc_id, candidate.record.page + 1)
        if ref.key in seen:
            continue
        seen.add(ref.key)
        refs.append(ref)
    return refs


def _get_source_page_html(
    src_docs: Sequence[OCRArtifact],
    page_ref: PageRef,
    fetched_page_cache: dict[tuple[int, int], str],
) -> str | None:
    if page_ref.key in fetched_page_cache:
        return fetched_page_cache[page_ref.key]
    doc_index = page_ref.document_id - 1
    page_index = page_ref.page_id - 1
    if doc_index < 0 or doc_index >= len(src_docs):
        return None
    doc = src_docs[doc_index]
    if page_index < 0 or page_index >= len(doc.pages):
        return None
    html = doc.pages[page_index].to_structured_html(page_id=f"source-page-{page_ref.page_id}")
    fetched_page_cache[page_ref.key] = html
    return html


def _make_prefetched_page(
    page_ref: PageRef,
    html: str,
    source_doc_infos: Sequence[dict[str, Any]] | None,
) -> PrefetchedPage:
    info: dict[str, Any] = {}
    if source_doc_infos and 0 <= page_ref.document_id - 1 < len(source_doc_infos):
        info = source_doc_infos[page_ref.document_id - 1]
    actual_doc_id = info.get("doc_id")
    return PrefetchedPage(
        document_id=page_ref.document_id,
        page_id=page_ref.page_id,
        html=html,
        actual_doc_id=int(actual_doc_id) if isinstance(actual_doc_id, int) else None,
        display_name=info.get("display_name") if isinstance(info.get("display_name"), str) else None,
    )


def _looks_like_table_block(block: OCRBlock) -> bool:
    return block.label == "table" or bool(BeautifulSoup(block.content or "", "lxml").find("table"))


def _parse_table_block(content: str) -> tuple[list[str], list[str], str] | None:
    soup = BeautifulSoup(content or "", "lxml")
    table = soup.find("table")
    if table is None:
        return None
    rows = table.find_all("tr")
    if not rows:
        return None

    row_cells = [_row_cells(row) for row in rows]
    header_index, header_cells = _select_header_row(row_cells)
    column_labels = [_clean_text(_cell_text(cell)) for cell in header_cells[1:]]
    column_labels = [label for label in column_labels if label]

    row_labels: list[str] = []
    for cells in row_cells[header_index + 1 :]:
        if not cells:
            continue
        label = _clean_text(_cell_text(cells[0]))
        if label:
            row_labels.append(label)

    title = _table_title_from_preheader(row_cells[:header_index])
    return _dedupe(row_labels), _dedupe(column_labels), title


def _select_header_row(row_cells: list[list[Tag]]) -> tuple[int, list[Tag]]:
    max_cell_count = max((len(cells) for cells in row_cells), default=0)
    for index, cells in enumerate(row_cells):
        if len(cells) == max_cell_count and max_cell_count > 1:
            return index, cells
    return 0, row_cells[0] if row_cells else []


def _table_title_from_preheader(rows: Sequence[list[Tag]]) -> str:
    candidates: list[str] = []
    for cells in rows:
        text = _clean_text(" ".join(_cell_text(cell) for cell in cells))
        if text and 2 <= len(text) <= 80 and REGEX_HAS_LETTER.search(text):
            candidates.append(text)
    return candidates[-1] if candidates else ""


def _nearby_title_hint(page: OCRPage, block_zero_index: int) -> str:
    start = max(0, block_zero_index - 2)
    for prev_index in range(block_zero_index - 1, start - 1, -1):
        text = _clean_text(_block_text(page.blocks[prev_index]))
        if not text or len(text) > 80:
            continue
        if REGEX_HAS_LETTER.search(text):
            return text
    return ""


def _block_text(block: OCRBlock) -> str:
    if block.label == "table":
        return _visible_text(block.content)
    return REGEX_TAG.sub(" ", block.content or "")


def _row_cells(row: Tag) -> list[Tag]:
    return [cell for cell in row.find_all(["th", "td"], recursive=False) if isinstance(cell, Tag)]


def _cell_text(cell: Tag) -> str:
    return cell.get_text(" ", strip=True)


def _select_query_terms(row_labels: Sequence[str]) -> list[str]:
    selected: list[str] = []
    for label in row_labels:
        if not _is_informative_label(label):
            continue
        selected.append(label)
        if len(selected) >= MAX_QUERY_TERMS:
            break
    return _dedupe(selected)


def _is_informative_label(label: str) -> bool:
    text = _clean_text(label)
    compact = _compact_text(text)
    if len(compact) < 2:
        return False
    if text in {"-", "N/A", "n/a"}:
        return False
    if REGEX_YEAR_LABEL.match(text):
        return False
    return bool(REGEX_HAS_LETTER.search(text))


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _compact_text(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value or "").lower()


def _visible_text(value: str) -> str:
    soup = BeautifulSoup(value or "", "lxml")
    text = soup.get_text(" ", strip=True)
    return _clean_text(text)


def _preview_text(value: str, max_chars: int = 260) -> str:
    text = _visible_text(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


async def _append_trace(ctx: WriteContext | None, payload: dict[str, Any]) -> None:
    if ctx is not None:
        await ctx.append_trace(payload)
