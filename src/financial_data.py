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
from pathlib import Path
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger(__name__)

FOUNDRY_FILE = DATA_DIR / "foundry_financials.json"


class FinancialDataManager:
    """
    公司财务数据管理器（单例）。

    Usage:
        fdm = FinancialDataManager()
        companies = fdm.find_companies("中芯国际和台积电的毛利率对比")
        ctx, refs = fdm.build_context("中芯国际和台积电的毛利率对比")
    """

    _instance: Optional["FinancialDataManager"] = None
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

        with open(FOUNDRY_FILE, "r") as f:
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

        # Exact match first
        for name, key in self._name_index.items():
            if name in query and key not in seen:
                seen.add(key)
                found.append(key)

        return found

    def get_company(self, name: str) -> Optional[dict]:
        """Get financial data for a single company by its key name."""
        return self._companies.get(name)

    # ── Context Builder ───────────────────────────────

    def build_context(
        self, query: str, max_companies: int = 2
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
        parts = [f"## 晶圆代工企业关键财务数据 ({self._meta_year()})\n"]

        for key in selected:
            c = self._companies[key]
            refs.append({"name": key, "name_en": c.get("name_en", ""), "year": c.get("year", "")})

            parts.append(f"### {key} ({c['name_en']}) [{c['ticker']}]")
            parts.append(f"- 币种: {c['currency']}")
            parts.append(
                f"- 营收: {c['revenue']['value']:.1f} "
                f"(YoY {c['revenue']['yoy_growth_pct']:+.1f}%)"
            )
            if c["revenue"].get("note"):
                parts.append(f"  → {c['revenue']['note']}")
            parts.append(f"- 毛利率: {c['gross_margin']['value']:.1f}%")
            if c["gross_margin"].get("trend"):
                parts.append(f"  → {c['gross_margin']['trend']}")
            parts.append(f"- 净利率: {c['net_margin']['value']:.1f}%")
            parts.append(
                f"- 资本支出 (CAPEX): {c['capex']['value']:.1f} "
                f"(CAPEX/营收={c['capex']['intensity_pct']}%)"
            )
            if c["capex"].get("trend"):
                parts.append(f"  → {c['capex']['trend']}")
            parts.append(f"- 研发投入比: {c['rd_expense']['rd_ratio']:.1f}%")
            parts.append(
                f"- 产能利用率: {c['capacity']['utilization_rate']:.1f}%"
            )
            parts.append(
                f"- 制程结构: {', '.join(f'{k}: {v}' for k, v in c['capacity'].get('process_mix', {}).items())}"
            )

            if c.get("key_strengths"):
                parts.append(f"- 核心优势: {'; '.join(c['key_strengths'][:3])}")
            if c.get("key_risks"):
                parts.append(f"- 关键风险: {'; '.join(c['key_risks'][:3])}")

            parts.append("")

        return "\n".join(parts), refs

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
