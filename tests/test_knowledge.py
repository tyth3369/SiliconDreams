from src.financial_data import FinancialDataManager
from src.storage import Database
from src.terminology import TerminologyManager


def test_terminology_loads_expected_baseline():
    manager = TerminologyManager()
    assert manager.stats()["total_terms"] >= 100


def test_terminology_finds_chinese_term():
    results = TerminologyManager().find_terms("先进制程是什么")
    assert any(term["name"] == "先进制程" for term in results)


def test_terminology_context_returns_refs():
    context, refs = TerminologyManager().build_context("解释 GAA", return_refs=True)
    assert context
    assert refs


def test_financial_data_finds_chinese_company():
    assert "台积电" in FinancialDataManager().find_companies("分析台积电的资本开支")


def test_financial_data_finds_english_company():
    assert "台积电" in FinancialDataManager().find_companies("TSMC gross margin")


def test_financial_context_has_year_and_reference():
    context, refs = FinancialDataManager().build_context("台积电财务数据")
    assert "2025" in context
    assert refs[0]["name"] == "台积电"


def test_unknown_company_returns_empty_context():
    assert FinancialDataManager().build_context("不存在的公司") == ("", [])


def test_financial_reference_points_to_official_source():
    _, refs = FinancialDataManager().build_context("台积电财务数据")
    assert refs[0]["source_url"].startswith("https://investor.tsmc.com/")
    assert "Management Report" in refs[0]["source_title"]


def test_financial_context_excludes_unsourced_analyst_narrative():
    context, _ = FinancialDataManager().build_context("台积电财务数据")
    assert "核心优势" not in context
    assert "关键风险" not in context


def test_financial_summaries_sync_to_fact_store(tmp_path):
    database = Database(tmp_path / "facts.db")
    count = FinancialDataManager().sync_to_database(database)
    assert count == 56
    facts = database.find_facts("TSMC", period="FY2025")
    assert len(facts) == 8
    assert all(fact["trust_tier"] == 1 for fact in facts)


def test_tsmc_quarterly_context_uses_requested_official_periods():
    context, refs = FinancialDataManager().build_context(
        "台积电季度数据", periods=["2025 Q3", "2025年第四季度"]
    )
    assert "33.10 USD billion" in context
    assert "33.73 USD billion" in context
    assert "增长率或差额须另由 financial_calculator 计算" in context
    assert [ref["period"] for ref in refs] == ["2025 Q3", "2025 Q4"]
    assert all(ref["source_url"].startswith("https://investor.tsmc.com/") for ref in refs)


def test_tsmc_all_quarters_can_be_selected_from_query():
    context, refs = FinancialDataManager().build_context("对比台积电2024年和2025年各季度")
    assert len(refs) == 8
    assert "2024 Q1" in context
    assert "2025 Q4" in context


def test_tsmc_latest_bundled_quarter_is_2026_q2():
    context, refs = FinancialDataManager().build_context("TSMC latest quarter", periods=["2026 Q2"])
    assert "40.20 USD billion" in context
    assert refs[0]["source_title"] == "TSMC 2Q26 Quarterly Results"


def test_quarterly_facts_sync_with_official_source(tmp_path):
    database = Database(tmp_path / "quarterly-facts.db")
    FinancialDataManager().sync_to_database(database)
    facts = database.find_facts("TSMC", period="2025 Q4")
    assert len(facts) == 4
    assert {fact["metric"] for fact in facts} == {
        "revenue",
        "gross_margin",
        "operating_margin",
        "usd_ntd_exchange_rate",
    }
    assert all(fact["trust_tier"] == 1 for fact in facts)
    assert all("TSMC 4Q25" in fact["source_title"] for fact in facts)


def test_missing_quarter_never_falls_back_to_annual_data():
    context, refs = FinancialDataManager().build_context("中芯国际季度数据", periods=["2025 Q4"])
    assert "不得用年度数据替代季度数据" in context
    assert "营收: 9.327" not in context
    assert refs == []
