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
    assert count == 16
    facts = database.find_facts("TSMC", period="FY2025")
    assert len(facts) == 8
    assert all(fact["trust_tier"] == 1 for fact in facts)
