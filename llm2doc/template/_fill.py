import re
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from llm2doc.hwp import HwpFile
from llm2doc.template._template_1 import Template1Data


def format_date_dots(d: date) -> str:
    return f"{d.year}.{d.month}.{d.day}"


def format_date_slash(d: date) -> str:
    return f"{str(d.year)[2:]}/{d.month}/{d.day}"


def format_num(v: Decimal, decimal_places: int = 0, suffix: str = "") -> str:
    """Format decimal with thousands separator and optional suffix."""
    fmt = f",.{decimal_places}f"
    return f"{v:{fmt}}{suffix}"


def fill_template(output_path: str | list[str], template_id: int, data: BaseModel):
    assert template_id == 1
    assert isinstance(data, Template1Data)

    with HwpFile.open("data/template_1.hwp", debug=True) as hwp:
        # Get shapes BEFORE replacing templates to ensure they haven't been deleted yet
        shape_heading = hwp.get_template_charshape("반복_본문_소제목")
        shape_content = hwp.get_template_charshape("반복_본문_내용")

        # --- Field Mappings ---
        fp = data.valuation.forecast_period
        field_mapping = {
            # Simple text fields
            "제목": data.header.title,
            "애널리스트_이름": data.header.analyst_name or "",
            "애널리스트_이메일": data.header.analyst_email or "",
            "기업이름": data.company.name,
            "주식이름": data.company.name,
            "종목번호": data.company.ticker,
            "섹터명": data.company.sector,
            # Dynamic parenthetical fields
            "투자의견": f"({data.rating.rating_modifier})" if data.rating.rating_modifier else "",
            "목표주가": f"({data.rating.rating_modifier})" if data.rating.rating_modifier else "",
            "Consensus_영업이익": f"({fp},십억원)",
            "EPS_성장률": f"({fp},%)",
            "MKT_EPS_성장률": f"({fp},%)",
            "PE": f"({fp},x)",
            "MKT_PE": f"({fp},x)",
            # Value fields (...값)
            "투자의견값": data.rating.rating,
            "목표주가값": format_num(data.rating.target_price, suffix="원"),
            "현재주가값": format_num(data.rating.current_price, suffix="원"),
            "상승여력값": format_num(data.rating.upside_potential, decimal_places=1, suffix="%"),
            "영업이익값": format_num(data.valuation.operating_profit_estimate),
            "Consensus_영업이익값": format_num(data.valuation.operating_profit_consensus),
            "EPS_성장률값": format_num(data.valuation.eps_growth, decimal_places=1),
            "MKT_EPS_성장률값": format_num(data.valuation.market_eps_growth, decimal_places=1),
            "PE값": format_num(data.valuation.pe_ratio, decimal_places=1),
            "MKT_PE값": format_num(data.valuation.market_pe_ratio, decimal_places=1),
            "시가총액값": format_num(data.market_data.market_cap),
            "발행주식수값": format_num(data.market_data.shares_outstanding),
            "유동주식비율값": format_num(data.market_data.free_float_ratio, decimal_places=1),
            "외국인보유비중값": format_num(data.market_data.foreign_ownership_ratio, decimal_places=1),
            "베타일간수익률값": format_num(data.market_data.beta_12m, decimal_places=2),
            "52주최고가값": format_num(data.market_data.price_52w_high),
            "52주최저가값": format_num(data.market_data.price_52w_low),
            "KOSPI값": format_num(data.market_data.kospi_index, decimal_places=2),
            "절대주가_1M값": format_num(data.performance.absolute_1m, decimal_places=1),
            "절대주가_6M값": format_num(data.performance.absolute_6m, decimal_places=1),
            "절대주가_12M값": format_num(data.performance.absolute_12m, decimal_places=1),
            "상대주가_1M값": format_num(data.performance.relative_1m, decimal_places=1),
            "상대주가_6M값": format_num(data.performance.relative_6m, decimal_places=1),
            "상대주가_12M값": format_num(data.performance.relative_12m, decimal_places=1),
            # Date fields
            "YYYY.M.D": format_date_dots(data.header.publish_date),
            "YY/M/D": format_date_slash(data.header.publish_date),
        }

        def write_html(html: str, shape: Any = None):
            def _writer(h: HwpFile):
                h.act_write_text_rich(html, shape)

            return _writer

        text_mapping = {
            "반복_본문_소제목": write_html(data.body_sections[0].heading, shape_heading),
            "반복_본문_내용": write_html(data.body_sections[0].content, shape_content),
            "기타본문": "",
            "주가지수그래프": "",
        }

        # --- Table Text Template Mappings ---
        table_mapping = {
            "표:컨센서스": data.financial_summary.periods,
            "표:매출액": [format_num(x) for x in data.financial_summary.revenue],
            "표:영업이익": [format_num(x) for x in data.financial_summary.operating_profit],
            "표:이익률": [format_num(x, 1) for x in data.financial_summary.operating_margin],
            "표:순이익": [format_num(x) for x in data.financial_summary.net_income],
            "표:EPS": [format_num(x) for x in data.financial_summary.eps],
            "표:ROE": [format_num(x, 1) for x in data.financial_summary.roe],
            "표:PE": [format_num(x, 1) for x in data.financial_summary.pe],
            "표:PB": [format_num(x, 1) for x in data.financial_summary.pb],
            "표:배당수익": [format_num(x, 1) for x in data.financial_summary.dividend_yield],
        }

        # --- Execute Replacements ---
        hwp.replace_templates({**field_mapping, **text_mapping})
        hwp.replace_table_templates(table_mapping)

        if isinstance(output_path, str):
            hwp.save_as(output_path)
        else:
            for path in output_path:
                hwp.save_as(path)
