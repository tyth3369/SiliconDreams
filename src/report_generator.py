"""
SiliconDreams — Structured Report Generator
=============================================
Three preset report templates: Peer Comparison / Tech Trends / Financial Deep Dive
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# Report Prompt Templates
# ═══════════════════════════════════════════════════

COMPARE_REPORT_PROMPT = """You are a senior semiconductor industry analyst. Based on the retrieved data below, generate a **Peer Comparison Analysis Report**.

## Data Sources
{context}

## Report Requirements
1. **Executive Summary** (2-3 sentences): Key findings
2. **Company Overview**: Market positioning and technology characteristics of each company
3. **Financial Metrics Comparison**: Use Markdown tables to display gross margin, net margin, ROE, R&D intensity, debt-to-asset ratio
   - [CRITICAL] All ratios MUST be computed using the financial_calculator tool
4. **Competitive Advantage Analysis**: Core strengths and risk factors for each company
5. **Investment Perspective**: Comprehensive analysis (for reference only, not investment advice)

## Format Requirements
- Use Markdown format
- Tag each data point with [source pN]
- Use Markdown tables for comparisons
"""

TECH_TREND_PROMPT = """You are a senior semiconductor technology analyst. Based on the information below, generate a **Technology Trend Analysis Report**.

## Terminology & Technology Background
{terminology_context}

## Financial Data
{financial_context}

## Report Requirements
1. **Technology Overview**: Definition, development history, current stage
2. **Supply Chain Analysis**: Benefit sequence for upstream equipment/materials, midstream manufacturing, downstream applications
3. **Financial Impact Quantification**: Impact of this technology on relevant companies' gross margin, R&D spending, CAPEX
   - [CRITICAL] Must use the financial_calculator tool
4. **Competitive Landscape**: Technology roadmap and progress of key players
5. **Outlook**: Key milestones and risk factors over the next 2-3 years

## Format Requirements
- Use Markdown format
- Include English full names when technical terms first appear
"""

FINANCE_DEEP_DIVE_PROMPT = """You are a senior semiconductor financial analyst. Based on the retrieved data below, generate a **Financial Deep Dive Report**.

## Data Sources
{context}

## Report Requirements
1. **Revenue Analysis**:
   - Revenue breakdown (by segment / region / customer)
   - YoY / QoQ growth rates ([CRITICAL] use financial_calculator)
2. **Profitability Analysis**:
   - Gross margin trends and drivers (process node, utilization rate, product mix)
   - Net margin analysis
   - ROE DuPont decomposition
3. **Operational Efficiency**:
   - Inventory turnover
   - Revenue per employee
   - R&D intensity
4. **Solvency & Cash Flow**:
   - Debt-to-asset ratio
   - Current ratio
   - Free cash flow trends
5. **Valuation Reference**: P/E or EV/EBITDA (data only, not investment advice)

## [CRITICAL] Rules
- All ratio and growth rate calculations MUST use the financial_calculator tool
- NEVER compute manually via LLM
- Include formulas with each calculation

## Format Requirements
- Markdown format
- Use tables for key metrics
- Tag each data point with [source pN]
"""


# ═══════════════════════════════════════════════════
# Report Generator
# ═══════════════════════════════════════════════════

class ReportGenerator:
    """Report generator with preset templates."""

    def __init__(self):
        self._templates = {
            "compare": COMPARE_REPORT_PROMPT,
            "tech_trend": TECH_TREND_PROMPT,
            "finance": FINANCE_DEEP_DIVE_PROMPT,
        }

    def generate(
        self,
        report_type: str,
        context: str = "",
        terminology_context: str = "",
        financial_context: str = "",
    ) -> str:
        """
        Generate a report prompt for LLM consumption.

        Args:
            report_type: "compare" | "tech_trend" | "finance"
            context: RAG retrieval context
            terminology_context: Terminology knowledge base context
            financial_context: Financial data context

        Returns:
            Complete report generation prompt
        """
        template = self._templates.get(report_type)
        if template is None:
            return f"Unknown report type: {report_type}"

        return template.format(
            context=context or "No relevant data available",
            terminology_context=terminology_context or "No terminology information available",
            financial_context=financial_context or context or "No financial data available",
        )

    @staticmethod
    def build_context_from_retrieval(
        text_results: list[dict],
        table_results: list[dict],
    ) -> str:
        """
        Assemble retrieval results into formatted context.

        Args:
            text_results: Text retrieval results
            table_results: Table retrieval results

        Returns:
            Formatted context string
        """
        parts = []

        if table_results:
            parts.append("## Financial Table Data\n")
            for i, r in enumerate(table_results[:5]):
                src = r["metadata"].get("source", "")
                page = r["metadata"].get("page", "?")
                parts.append(f"### Table {i+1}: {src} (p{page})\n")
                parts.append(r["text"][:2000])
                parts.append("")

        if text_results:
            parts.append("## Text Excerpts\n")
            for i, r in enumerate(text_results[:5]):
                src = r["metadata"].get("source", "")
                page = r["metadata"].get("page", "?")
                parts.append(f"### Excerpt {i+1}: {src} (p{page})\n")
                parts.append(r["text"][:2000])
                parts.append("")

        return "\n".join(parts) if parts else "No retrieval data available"


# ── Convenience ──────────────────────────────────────

def get_report_generator() -> ReportGenerator:
    return ReportGenerator()
