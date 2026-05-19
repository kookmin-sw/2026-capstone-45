from datetime import date
from decimal import Decimal
from pydantic import BaseModel


class ReportHeader(BaseModel):
    publish_date: date
    """리포트 발행 일자 (ex: 2000-01-01)"""
    title: str
    """리포트의 메인 제목 (ex: '새로운 시작')"""
    analyst_name: str | None
    """담당 애널리스트 이름 (ex: '홍길동')"""
    analyst_email: str | None
    """담당 애널리스트 이메일 주소 (ex: 'gildong@example.com')"""


class CompanyProfile(BaseModel):
    name: str
    """기업의 공식 명칭 (ex: '삼성전자')"""
    ticker: str
    """주식 종목 코드 (ex: '005930')"""
    sector: str
    """소속 산업 또는 섹터 명 (ex: '반도체')"""


class InvestmentRating(BaseModel):
    rating: str
    """투자의견 (ex: '매수', 'Hold')"""
    rating_modifier: str | None = None
    """투자의견 변동 (ex: '유지', '상향')"""
    target_price: Decimal
    """제시된 목표 주가"""
    current_price: Decimal
    """기준일 현재 주가"""
    upside_potential: Decimal
    """현재 주가 대비 목표 주가까지의 상승 여력 백분율"""


class ValuationMetrics(BaseModel):
    forecast_period: str
    """예상 실적 기준 연도 (ex: '26F')"""
    operating_profit_estimate: Decimal
    """해당 연도(ex: 26F) 영업이익 추정치 (단위: 십억원)"""
    operating_profit_consensus: Decimal
    """시장 컨센서스 영업이익 (단위: 십억원)"""
    eps_growth: Decimal
    """주당순이익(EPS) 성장률 추정치 (%)"""
    market_eps_growth: Decimal
    """시장(MKT) 전체의 EPS 성장률 (%)"""
    pe_ratio: Decimal
    """주가수익비율(PER) 추정치 (배)"""
    market_pe_ratio: Decimal
    """시장(MKT) 전체의 주가수익비율 (배)"""


class MarketStatistics(BaseModel):
    market_cap: Decimal
    """시가총액 (단위: 십억원)"""
    shares_outstanding: Decimal
    """총 발행 주식 수 (단위: 백만주)"""
    free_float_ratio: Decimal
    """유동 주식 비율 (%)"""
    foreign_ownership_ratio: Decimal
    """외국인 보유 지분율 (%)"""
    beta_12m: Decimal
    """최근 12개월 기준 주가 변동성(베타) 일간수익률"""
    price_52w_high: Decimal
    """최근 52주 최고 주가"""
    price_52w_low: Decimal
    """최근 52주 최저 주가"""
    kospi_index: Decimal
    """리포트 기준일의 코스피 지수"""


class StockPerformance(BaseModel):
    absolute_1m: Decimal
    """최근 1개월 절대 주가 수익률 (%)"""
    absolute_6m: Decimal
    """최근 6개월 절대 주가 수익률 (%)"""
    absolute_12m: Decimal
    """최근 12개월 절대 주가 수익률 (%)"""
    relative_1m: Decimal
    """최근 1개월 시장(KOSPI 등) 대비 상대 수익률 (%)"""
    relative_6m: Decimal
    """최근 6개월 시장(KOSPI 등) 대비 상대 수익률 (%)"""
    relative_12m: Decimal
    """최근 12개월 시장(KOSPI 등) 대비 상대 수익률 (%)"""


class FinancialStatementSummary(BaseModel):
    periods: list[str]
    """결산기 헤더 리스트 (ex: ['12/23', '12/24F', '12/25F', '12/26F'])"""
    revenue: list[Decimal]
    """해당 결산기별 매출액 리스트 (단위: 십억원)"""
    operating_profit: list[Decimal]
    """해당 결산기별 영업이익 리스트 (단위: 십억원)"""
    operating_margin: list[Decimal]
    """해당 결산기별 영업이익률 리스트 (%)"""
    net_income: list[Decimal]
    """해당 결산기별 지배주주 귀속 순이익 리스트 (단위: 십억원)"""
    eps: list[Decimal]
    """해당 결산기별 주당순이익 리스트 (원)"""
    roe: list[Decimal]
    """해당 결산기별 자기자본이익률 리스트 (%)"""
    pe: list[Decimal]
    """해당 결산기별 주가수익비율(PER) 리스트 (배)"""
    pb: list[Decimal]
    """해당 결산기별 주가순자산비율(PBR) 리스트 (배)"""
    dividend_yield: list[Decimal]
    """해당 결산기별 배당수익률 리스트 (%)"""


class ReportBodySection(BaseModel):
    heading: str
    """본문 섹션의 소제목"""
    content: str
    """본문 섹션의 상세 내용 (HTML 태그 일부 지원)"""


class Template1Data(BaseModel):
    header: ReportHeader
    """리포트 메타데이터 및 애널리스트 정보"""
    company: CompanyProfile
    """분석 대상 기업의 식별 정보"""
    rating: InvestmentRating
    """투자의견 및 주가 데이터"""
    valuation: ValuationMetrics
    """이익 추정치 및 밸류에이션 데이터"""
    market_data: MarketStatistics
    """시가총액, 주식수 등 시장 통계"""
    performance: StockPerformance
    """기간별 절대/상대 주가 수익률"""
    chart_data: dict[date, Decimal]
    """주가지수 그래프 렌더링을 위한 일자별 주가 시계열 데이터"""
    body_sections: list[ReportBodySection]
    """본문의 소제목과 내용이 반복되는 섹션 리스트"""
    financial_summary: FinancialStatementSummary
    """리포트 하단의 연도별 재무 및 컨센서스 요약 테이블 데이터"""


def D(value: str | int | float) -> Decimal:
    return Decimal(str(value))


EXAMPLE_1 = Template1Data(
    header=ReportHeader(
        publish_date=date(2030, 5, 15),
        title="차세대 AI 반도체의 패러다임 전환",
        analyst_name="홍길동",
        analyst_email="example@example.com",
    ),
    company=CompanyProfile(name="(주)예시", ticker="999999", sector="반도체"),
    rating=InvestmentRating(
        rating="매수", rating_modifier="유지", target_price=D(500000), current_price=D(250000), upside_potential=D(100)
    ),
    valuation=ValuationMetrics(
        forecast_period="26F",
        operating_profit_estimate=D(1500),
        operating_profit_consensus=D(1400),
        eps_growth=D(25.5),
        market_eps_growth=D(8.0),
        pe_ratio=D(15.2),
        market_pe_ratio=D(12.0),
    ),
    market_data=MarketStatistics(
        market_cap=D(50000),
        shares_outstanding=D(200),
        free_float_ratio=D(60.5),
        foreign_ownership_ratio=D(30.0),
        beta_12m=D(1.05),
        price_52w_high=D(300000),
        price_52w_low=D(150000),
        kospi_index=D(3500.50),
    ),
    performance=StockPerformance(
        absolute_1m=D(5.0),
        absolute_6m=D(15.0),
        absolute_12m=D(30.0),
        relative_1m=D(2.0),
        relative_6m=D(10.0),
        relative_12m=D(20.0),
    ),
    chart_data={date(2030, 5, 13): D(248000), date(2030, 5, 14): D(249500), date(2030, 5, 15): D(250000)},
    body_sections=[
        ReportBodySection(
            heading="제목1",
            content="본문내용1. <u>밑줄</u>. <b>볼드</b>.",
        ),
        ReportBodySection(
            heading="제목2",
            content="본문내용2",
        ),
    ],
    financial_summary=FinancialStatementSummary(
        periods=["2028", "2029F", "2030F"],
        revenue=[D(10000), D(12000), D(15000)],
        operating_profit=[D(1000), D(1200), D(1500)],
        operating_margin=[D(10.0), D(10.0), D(10.0)],
        net_income=[D(800), D(960), D(1200)],
        eps=[D(4000), D(4800), D(6000)],
        roe=[D(15.0), D(16.0), D(17.5)],
        pe=[D(12.5), D(10.4), D(8.3)],
        pb=[D(1.8), D(1.6), D(1.4)],
        dividend_yield=[D(2.0), D(2.2), D(2.5)],
    ),
)
