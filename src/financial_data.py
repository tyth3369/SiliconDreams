"""
SiliconDreams — Company Financial Data Manager
===============================================
Singleton manager for structured financial data on foundry companies.
Pattern: mirrors TerminologyManager — lazy-loaded JSON, name matching, context builder.

Data source: data/foundry_financials.json
"""

from __future__ import annotations

import json
import logging
import re

from config import DATA_DIR

logger = logging.getLogger(__name__)

FOUNDRY_FILE = DATA_DIR / "foundry_financials.json"

QUARTERLY_METRICS = (
    ("revenue_usd_billion", "营收", "revenue", "billion", "USD"),
    ("gross_margin_pct", "毛利率", "gross_margin", "percent", None),
    ("operating_margin_pct", "营业利润率", "operating_margin", "percent", None),
    (
        "operating_profit_usd_billion",
        "营业利润",
        "operating_profit",
        "billion",
        "USD",
    ),
    (
        "usd_ntd_exchange_rate",
        "平均汇率（1 USD 对 NTD）",
        "usd_ntd_exchange_rate",
        "NTD_per_USD",
        None,
    ),
)


def _format_quarterly_metric(key: str, value: float) -> str:
    if key.endswith("_pct"):
        return f"{value:.1f}%"
    if key.endswith("_usd_billion"):
        return f"{value:.6g} USD billion"
    if key == "usd_ntd_exchange_rate":
        return f"{value:.2f} NTD per USD"
    return str(value)


class FinancialDataManager:
    """
    公司财务数据管理器（单例）。

    Usage:
        fdm = FinancialDataManager()
        companies = fdm.find_companies("中芯国际和台积电的毛利率对比")
        ctx, refs = fdm.build_context("中芯国际和台积电的毛利率对比")
    """

    _instance: FinancialDataManager | None = None
    _companies: dict = {}
    _name_index: dict = {}  # name/english/ticker → company key

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._companies:
            self._load()

    def _load(self):
        """Load financial data from JSON file."""
        if not FOUNDRY_FILE.exists():
            logger.warning(f"财务数据文件不存在: {FOUNDRY_FILE}")
            return

        with open(FOUNDRY_FILE) as f:
            data = json.load(f)

        self._companies = data.get("companies", {})
        self._build_index()
        logger.info(f"财务数据加载完成: {len(self._companies)} 家公司")

    def _build_index(self):
        """Build name lookup index."""
        for name, info in self._companies.items():
            self._name_index[name] = name
            en = info.get("name_en", "")
            if en:
                self._name_index[en.lower()] = name
            ticker = info.get("ticker", "")
            if ticker:
                # Handle multi-ticker format "688981.SH / 0981.HK"
                for t in ticker.replace("/", " ").split():
                    t = t.strip().upper()
                    if t:
                        self._name_index[t] = name

    # ── Query ─────────────────────────────────────────

    def find_companies(self, query: str) -> list[str]:
        """
        Detect company names in a user query.

        Returns:
            List of company keys found (e.g. ["台积电", "中芯国际"])
        """
        found = []
        seen = set()
        normalized_query = query.casefold()

        # Exact match first
        for name, key in self._name_index.items():
            if name.casefold() in normalized_query and key not in seen:
                seen.add(key)
                found.append(key)

        return found

    def get_company(self, name: str) -> dict | None:
        """Get financial data for a single company by its key name."""
        return self._companies.get(name)

    # ── Context Builder ───────────────────────────────

    @staticmethod
    def _normalize_period(value: str) -> str:
        """Normalize common Chinese/English quarter spellings to ``YYYY QN``."""
        cleaned = re.sub(r"\s+", " ", value.strip().upper())
        patterns = (
            r"(20\d{2})\s*(?:年|[-/])?\s*Q([1-4])",
            r"Q([1-4])\s*[-/]?\s*(20\d{2})",
            r"([1-4])Q\s*[-/]?\s*(20\d{2})",
        )
        for index, pattern in enumerate(patterns):
            match = re.fullmatch(pattern, cleaned)
            if match:
                first, second = match.groups()
                year, quarter = (first, second) if index == 0 else (second, first)
                return f"{year} Q{quarter}"

        chinese = re.fullmatch(r"(20\d{2})\s*年?\s*第?([一二三四1-4])\s*季度", cleaned)
        if chinese:
            quarter = {"一": "1", "二": "2", "三": "3", "四": "4"}.get(
                chinese.group(2), chinese.group(2)
            )
            return f"{chinese.group(1)} Q{quarter}"
        if re.fullmatch(r"FY20\d{2}", cleaned):
            return cleaned
        if re.fullmatch(r"20\d{2}", cleaned):
            return f"FY{cleaned}"
        return cleaned

    @classmethod
    def _periods_from_query(cls, query: str, available: set[str]) -> list[str]:
        """Extract explicit quarters, or all quarters for requested years."""
        normalized_query = query.upper()
        years = list(dict.fromkeys(re.findall(r"20\d{2}", normalized_query)))
        wants_all = any(
            marker in normalized_query
            for marker in ("各季度", "所有季度", "逐季", "QUARTERS", "QUARTERLY")
        )
        if wants_all and years:
            return sorted(period for period in available if period[:4] in years)

        candidates: list[str] = []
        for match in re.finditer(r"(20\d{2})\s*(?:年|[-/])?\s*Q([1-4])", normalized_query):
            candidates.append(f"{match.group(1)} Q{match.group(2)}")
        for match in re.finditer(r"Q([1-4])\s*[-/]?\s*(20\d{2})", normalized_query):
            candidates.append(f"{match.group(2)} Q{match.group(1)}")
        for match in re.finditer(r"(20\d{2})\s*年?\s*第?([一二三四1-4])\s*季度", query):
            quarter = {"一": "1", "二": "2", "三": "3", "四": "4"}.get(
                match.group(2), match.group(2)
            )
            candidates.append(f"{match.group(1)} Q{quarter}")

        return list(dict.fromkeys(period for period in candidates if period in available))

    def build_context(
        self,
        query: str,
        max_companies: int = 2,
        periods: list[str] | None = None,
    ) -> tuple[str, list[dict]]:
        """
        Build financial context string and citation refs for detected companies.

        Returns:
            (context_str, refs) where refs is [{"name": "台积电", "name_en": "TSMC"}, ...]
        """
        company_keys = self.find_companies(query)

        if not company_keys:
            return "", []

        selected = company_keys[:max_companies]
        refs = []
        parts = ["## 晶圆代工企业官方结构化财务数据\n"]

        for key in selected:
            c = self._companies[key]
            quarterly = c.get("quarterly", {})
            requested = [self._normalize_period(period) for period in (periods or [])]
            if not requested:
                requested = self._periods_from_query(query, set(quarterly))
            selected_quarters = [period for period in requested if period in quarterly]
            annual_period = f"FY{c['year']}"
            annual_requested = annual_period in requested

            if selected_quarters:
                parts.append(f"### {key} ({c['name_en']}) [{c['ticker']}] — 季度实际值")
                if c.get("evidence_scope"):
                    parts.append(f"- 证据口径: {c['evidence_scope']}")
                for period in selected_quarters:
                    quarter = quarterly[period]
                    metrics = quarter["metrics"]
                    metric_lines = [
                        f"{label}: {_format_quarterly_metric(metric_key, metrics[metric_key])}"
                        for metric_key, label, _fact_metric, _unit, _currency in QUARTERLY_METRICS
                        if metric_key in metrics
                    ]
                    refs.append(
                        {
                            "name": key,
                            "name_en": c.get("name_en", ""),
                            "period": period,
                            "source_title": quarter["source_title"],
                            "source_url": quarter["source_url"],
                            "source_publisher": quarter.get("source_publisher", ""),
                            "source_published_at": quarter.get("source_published_at", ""),
                            "snippet": f"{period}: {'; '.join(metric_lines)}",
                        }
                    )
                    parts.append(f"#### {period}")
                    parts.extend(f"- {line}" for line in metric_lines)
                    parts.extend(
                        [
                            f"- 官方来源: {quarter['source_title']} ({quarter['source_published_at']})",
                            f"  {quarter['source_url']}",
                        ]
                    )
                parts.append(
                    "- 数据口径说明: 表内均为公司披露的季度实际值；增长率或差额须另由 financial_calculator 计算。"
                )
                missing = [period for period in requested if period not in quarterly]
                if missing:
                    parts.append(f"- 缺失期间: {', '.join(missing)}（结构化数据尚未收录）")
                parts.append("")
                continue

            if requested and not annual_requested:
                available = ", ".join(sorted(quarterly)) or "无"
                parts.extend(
                    [
                        f"### {key} ({c['name_en']}) [{c['ticker']}]",
                        f"- 请求期间: {', '.join(requested)}",
                        "- 结果: 结构化季度数据尚未收录；不得用年度数据替代季度数据。",
                        f"- 当前可用季度: {available}",
                        "",
                    ]
                )
                continue

            refs.append(
                {
                    "name": key,
                    "name_en": c.get("name_en", ""),
                    "year": c.get("year", ""),
                    "source_title": c.get("source_title", ""),
                    "source_url": c.get("source_url", ""),
                    "source_publisher": c.get("source_publisher", ""),
                    "source_published_at": c.get("source_published_at", ""),
                    "snippet": (
                        f"FY{c['year']}: revenue {c['revenue']['value']:.4g} "
                        f"{c['currency']} {c.get('unit', '')}; gross margin "
                        f"{c['gross_margin']['value']:.1f}%; net margin "
                        f"{c['net_margin']['value']:.1f}%; CAPEX "
                        f"{c['capex']['value']:.4g} {c['currency']} {c.get('unit', '')}; "
                        f"CAPEX/revenue {c['capex']['intensity_pct']:.1f}%; R&D intensity "
                        f"{c['rd_expense']['rd_ratio']:.1f}%; capacity utilization "
                        f"{c['capacity']['utilization_rate']:.1f}%; process mix "
                        f"{', '.join(f'{name} {value}' for name, value in c['capacity'].get('process_mix', {}).items())}"
                    ),
                }
            )

            parts.append(f"### {key} ({c['name_en']}) [{c['ticker']}]")
            unit = c.get("unit", "")
            parts.append(f"- 计量口径: {c['currency']} {unit}".rstrip())
            parts.append(
                f"- 营收: {c['revenue']['value']:.4g} {c['currency']} {unit} "
                f"(YoY {c['revenue']['yoy_growth_pct']:+.1f}%)"
            )
            if c["revenue"].get("note"):
                parts.append(f"  → {c['revenue']['note']}")
            parts.append(f"- 毛利率: {c['gross_margin']['value']:.1f}%")
            if c["gross_margin"].get("trend"):
                parts.append(f"  → {c['gross_margin']['trend']}")
            parts.append(f"- 净利率: {c['net_margin']['value']:.1f}%")
            parts.append(
                f"- 资本支出 (CAPEX): {c['capex']['value']:.4g} {c['currency']} {unit} "
                f"(CAPEX/营收={c['capex']['intensity_pct']}%)"
            )
            if c["capex"].get("trend"):
                parts.append(f"  → {c['capex']['trend']}")
            parts.append(f"- 研发投入比: {c['rd_expense']['rd_ratio']:.1f}%")
            parts.append(f"- 产能利用率: {c['capacity']['utilization_rate']:.1f}%")
            parts.append(
                f"- 制程结构: {', '.join(f'{k}: {v}' for k, v in c['capacity'].get('process_mix', {}).items())}"
            )

            if c.get("source_title"):
                parts.append(
                    f"- 官方来源: {c['source_title']} ({c.get('source_published_at', '日期未知')})"
                )
                parts.append(f"  {c.get('source_url', '')}")

            parts.append("")

        return "\n".join(parts), refs

    def sync_to_database(self, database=None) -> int:
        """Normalize bundled company summaries into the evidence database."""
        from src.storage import Database

        db = database or Database()
        inserted = 0
        for company, data in self._companies.items():
            source_id = db.upsert_source(
                source_type="official",
                title=data["source_title"],
                url=data["source_url"],
                publisher=data.get("source_publisher"),
                published_at=data.get("source_published_at"),
                trust_tier=1,
                metadata={"company": company, "report_period": f"FY{data['year']}"},
            )
            common = {
                "source_id": source_id,
                "company": data["name_en"],
                "period": f"FY{data['year']}",
                "currency": data["currency"],
            }
            facts = [
                ("revenue", data["revenue"]["value"], data.get("unit", "billion")),
                ("revenue_yoy", data["revenue"]["yoy_growth_pct"], "percent"),
                ("gross_margin", data["gross_margin"]["value"], "percent"),
                ("net_margin", data["net_margin"]["value"], "percent"),
                ("capex", data["capex"]["value"], data.get("unit", "billion")),
                ("capex_intensity", data["capex"]["intensity_pct"], "percent"),
                ("rd_intensity", data["rd_expense"]["rd_ratio"], "percent"),
                ("capacity_utilization", data["capacity"]["utilization_rate"], "percent"),
            ]
            for metric, value, fact_unit in facts:
                db.upsert_fact(metric=metric, value=value, unit=fact_unit, **common)
                inserted += 1

            for period, quarter in data.get("quarterly", {}).items():
                quarter_source_id = db.upsert_source(
                    source_type="official",
                    title=quarter["source_title"],
                    url=quarter["source_url"],
                    publisher=quarter.get("source_publisher"),
                    published_at=quarter.get("source_published_at"),
                    trust_tier=1,
                    metadata={"company": company, "report_period": period},
                )
                metrics = quarter["metrics"]
                for metric_key, _label, metric, fact_unit, currency in QUARTERLY_METRICS:
                    if metric_key not in metrics:
                        continue
                    db.upsert_fact(
                        source_id=quarter_source_id,
                        company=data["name_en"],
                        metric=metric,
                        period=period,
                        value=metrics[metric_key],
                        unit=fact_unit,
                        currency=currency,
                        metadata={"period_type": "quarterly", "actual": True},
                    )
                    inserted += 1
        return inserted

    def _meta_year(self) -> str:
        """Return the data year from the first company's metadata."""
        for c in self._companies.values():
            return str(c.get("year", "2025"))
        return "2025"

    def stats(self) -> dict:
        return {"companies": len(self._companies), "aliases": len(self._name_index)}


# ── Convenience ──────────────────────────────────────────


def get_financial_data() -> FinancialDataManager:
    return FinancialDataManager()
