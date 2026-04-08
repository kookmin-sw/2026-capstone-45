from typing import Dict, List, Optional

from .semantic_types import RoleDecision
from .types import CanonicalBlock, FusedPage, PageAnalysis
from .utils import EMAIL_RE, TICKER_RE, clean_text


def make_unknown_decision(block: CanonicalBlock, reason: str = "No heuristic rule matched.") -> RoleDecision:
    return RoleDecision(
        block_id=block.block_id,
        generic_role="unknown",
        domain_role=None,
        role_confidence=0.0,
        section_purpose=None,
        used_for_generation=False,
        reason=reason,
        needs_review=False,
    )


def _matches_any(text: str, keywords: List[str]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _find_next_block(blocks: List[CanonicalBlock], start_index: int, labels: List[str]) -> Optional[CanonicalBlock]:
    for candidate in blocks[start_index + 1 :]:
        if candidate.canonical_label in labels:
            return candidate
    return None


def _assign(
    decisions: Dict[str, RoleDecision],
    block: CanonicalBlock,
    generic_role: str,
    domain_role: Optional[str],
    confidence: float,
    used_for_generation: bool,
    reason: str,
    allow_domain: bool = True,
    section_purpose: Optional[str] = None,
) -> None:
    decisions[block.block_id] = RoleDecision(
        block_id=block.block_id,
        generic_role=generic_role,
        domain_role=domain_role if allow_domain else None,
        role_confidence=round(confidence, 4),
        section_purpose=section_purpose,
        used_for_generation=used_for_generation,
        reason=reason,
        needs_review=False,
    )


def compute_financial_safety_rules(page: FusedPage, analysis: PageAnalysis) -> Dict[str, RoleDecision]:
    decisions: Dict[str, RoleDecision] = {}
    allow_domain = analysis.quality_score >= 0.55
    blocks = sorted(page.blocks, key=lambda block: (block.reading_order, block.bbox_px[1], block.bbox_px[0]))

    for block in blocks:
        text = clean_text(block.text)
        in_top_meta = block.bbox_norm[3] <= 0.14

        if not text and block.raw_label != "list":
            continue

        if EMAIL_RE.search(text) or _matches_any(text, ["analyst", "ra "]):
            _assign(
                decisions,
                block,
                "author_info",
                "analyst_info",
                0.95,
                True,
                "Matched analyst identity or email pattern.",
                allow_domain=allow_domain,
            )
            continue

        if _matches_any(text, ["compliance notice", "투자판단", "중요 내용", "유동성공급자", "면책"]) or block.raw_label == "list":
            _assign(
                decisions,
                block,
                "disclaimer",
                "disclaimer_block",
                0.94,
                True,
                "Matched disclaimer or compliance cues.",
                allow_domain=allow_domain,
                section_purpose="disclaimer",
            )
            continue

        if in_top_meta and _matches_any(text, ["기업분석", "report", "기업", "202", "2026", "2025"]):
            _assign(
                decisions,
                block,
                "metadata",
                "report_header_meta",
                0.76,
                True,
                "Matched top metadata cues for report header.",
                allow_domain=allow_domain,
            )
            continue

        if _matches_any(text, ["리서치센터", "research center", "research ai"]):
            _assign(
                decisions,
                block,
                "metadata",
                "research_center_meta",
                0.88,
                True,
                "Matched research center metadata cues.",
                allow_domain=allow_domain,
            )

    return decisions


def compute_financial_rule_decisions(page: FusedPage, analysis: PageAnalysis) -> Dict[str, RoleDecision]:
    decisions: Dict[str, RoleDecision] = {}
    allow_domain = analysis.quality_score >= 0.55
    blocks = sorted(page.blocks, key=lambda block: (block.reading_order, block.bbox_px[1], block.bbox_px[0]))
    report_title_seen = False

    for index, block in enumerate(blocks):
        text = clean_text(block.text)
        in_left_sidebar = block.bbox_norm[2] <= 0.35
        in_main_body = block.bbox_norm[0] >= 0.32
        in_top_meta = block.bbox_norm[3] <= 0.14
        in_bottom_meta = block.bbox_norm[1] >= 0.78

        if not text and block.canonical_label not in {"table", "chart", "image"}:
            continue

        if in_top_meta and _matches_any(text, ["기업분석", "report", "기업", "202", "2026", "2025"]):
            _assign(
                decisions,
                block,
                "metadata",
                "report_header_meta",
                0.76,
                True,
                "Matched top metadata cues for report header.",
                allow_domain=allow_domain,
            )
            continue

        if EMAIL_RE.search(text) or _matches_any(text, ["analyst", "ra "]):
            _assign(
                decisions,
                block,
                "author_info",
                "analyst_info",
                0.95,
                True,
                "Matched analyst identity or email pattern.",
                allow_domain=allow_domain,
            )
            continue

        if _matches_any(text, ["리서치센터", "research center", "research ai"]):
            _assign(
                decisions,
                block,
                "metadata",
                "research_center_meta",
                0.88,
                True,
                "Matched research center metadata cues.",
                allow_domain=allow_domain,
            )
            continue

        if _matches_any(text, ["compliance notice", "투자판단", "중요 내용", "유동성공급자", "면책"]) or block.raw_label == "list":
            _assign(
                decisions,
                block,
                "disclaimer",
                "disclaimer_block",
                0.94,
                True,
                "Matched disclaimer or compliance cues.",
                allow_domain=allow_domain,
                section_purpose="disclaimer",
            )
            continue

        if in_left_sidebar and _matches_any(text, ["buy", "sell", "hold", "목표주가", "현재주가", "상승여력", "유지", "상향", "하향"]):
            _assign(
                decisions,
                block,
                "summary",
                "investment_opinion_box",
                0.96,
                True,
                "Matched investment opinion keywords in the sidebar.",
                allow_domain=allow_domain,
                section_purpose="investment_summary",
            )
            continue

        if in_left_sidebar and _matches_any(text, ["key data"]):
            _assign(
                decisions,
                block,
                "section_heading",
                "key_data_box",
                0.98,
                True,
                "Matched sidebar key data heading.",
                allow_domain=allow_domain,
                section_purpose="evidence_panel",
            )
            next_block = _find_next_block(blocks, index, ["table"])
            if next_block and next_block.bbox_norm[2] <= 0.4:
                _assign(
                    decisions,
                    next_block,
                    "evidence",
                    "key_data_box",
                    0.92,
                    False,
                    "Attached the next sidebar table to the key data panel.",
                    allow_domain=allow_domain,
                    section_purpose="evidence_panel",
                )
            continue

        if in_left_sidebar and _matches_any(text, ["consensus data"]):
            _assign(
                decisions,
                block,
                "section_heading",
                "consensus_box",
                0.98,
                True,
                "Matched sidebar consensus heading.",
                allow_domain=allow_domain,
                section_purpose="evidence_panel",
            )
            next_block = _find_next_block(blocks, index, ["table"])
            if next_block and next_block.bbox_norm[2] <= 0.4:
                _assign(
                    decisions,
                    next_block,
                    "evidence",
                    "consensus_box",
                    0.92,
                    False,
                    "Attached the next sidebar table to the consensus panel.",
                    allow_domain=allow_domain,
                    section_purpose="evidence_panel",
                )
            continue

        if in_left_sidebar and _matches_any(text, ["stock price"]):
            _assign(
                decisions,
                block,
                "section_heading",
                "price_chart_block",
                0.98,
                True,
                "Matched sidebar stock price heading.",
                allow_domain=allow_domain,
                section_purpose="evidence_panel",
            )
            next_block = _find_next_block(blocks, index, ["chart", "image"])
            if next_block and next_block.bbox_norm[2] <= 0.4:
                _assign(
                    decisions,
                    next_block,
                    "evidence",
                    "price_chart_block",
                    0.92,
                    False,
                    "Attached the next sidebar visual to the price chart panel.",
                    allow_domain=allow_domain,
                    section_purpose="evidence_panel",
                )
            continue

        if block.canonical_label == "table" and in_main_body and _matches_any(
            text,
            ["financial data", "매출액", "영업이익", "eps", "bps", "roe", "per"],
        ):
            _assign(
                decisions,
                block,
                "evidence",
                "financial_table_block",
                0.9,
                False,
                "Matched financial evidence table in the main body.",
                allow_domain=allow_domain,
                section_purpose="evidence_panel",
            )
            continue

        if in_main_body and (
            TICKER_RE.search(text)
            or (
                block.canonical_label in {"document_title", "section_heading", "paragraph"}
                and len(text) <= 80
                and text.count("\n") <= 2
                and block.bbox_norm[1] <= 0.35
            )
        ):
            if TICKER_RE.search(text) or block.canonical_label == "document_title":
                _assign(
                    decisions,
                    block,
                    "main_title",
                    "report_title",
                    0.94,
                    True,
                    "Matched main title or ticker-like report title pattern.",
                    allow_domain=allow_domain,
                    section_purpose="main_argument",
                )
                report_title_seen = True
                continue
            if report_title_seen and len(text) <= 70:
                _assign(
                    decisions,
                    block,
                    "section_heading",
                    "thesis_heading",
                    0.86,
                    True,
                    "Matched thesis heading after the report title.",
                    allow_domain=allow_domain,
                    section_purpose="thesis",
                )
                continue

        if in_main_body and block.canonical_label in {"paragraph", "paragraph_or_meta"} and len(text) >= 40:
            _assign(
                decisions,
                block,
                "body",
                "supporting_argument",
                0.82,
                True,
                "Matched a long main-body paragraph.",
                allow_domain=allow_domain,
                section_purpose="supporting_argument",
            )
            continue

        if block.canonical_label in {"table", "chart", "image"}:
            _assign(
                decisions,
                block,
                "evidence",
                "unsupported_evidence",
                0.6,
                False,
                "Matched a visual or evidence block without stronger panel evidence.",
                allow_domain=allow_domain,
                section_purpose="evidence_panel",
            )
            continue

        if in_bottom_meta and text:
            _assign(
                decisions,
                block,
                "metadata",
                None,
                0.55,
                False,
                "Matched bottom metadata text.",
                allow_domain=False,
            )

    return decisions
