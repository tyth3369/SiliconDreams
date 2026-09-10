"""
SiliconDreams — Citation Data Model & Formatter
================================================
Tracks knowledge sources used in LLM responses and formats
collapsible citation panels for the chat frontend.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Citation:
    """A single citation pointing to a knowledge source."""

    source: str  # filename, term name, or company name
    source_label: str  # "source" | "term" | "financial"
    source_type: str  # "rag" | "term" | "financial"
    page: Optional[int] = None  # page number (None for terms/financial)
    snippet: str = ""  # truncated excerpt (first 200 chars)
    score: float = 0.0  # relevance score (0-1 for RAG)
    url: str = ""  # web search URL (empty for non-web citations)
    name_en: str = ""  # company English name/ticker (for financial type)
    data_year: str = ""  # data year (for financial type)

    def display_source(self) -> str:
        """Human-readable source identifier."""
        if self.source_type == "term":
            return self.source
        elif self.source_type == "financial":
            parts = [self.source]
            if self.name_en:
                parts.append(f" ({self.name_en})")
            if self.data_year:
                parts.append(f" · FY{self.data_year} 年度财务摘要")
            else:
                parts.append(" 财务数据")
            return "".join(parts)
        elif self.source_type == "web":
            return self.source  # title is already descriptive
        elif self.page:
            return f"{self.source} · p{self.page}"
        return self.source

    def icon(self) -> str:
        """Emoji-free icon label."""
        if self.source_type == "term":
            return "KNOWLEDGE"
        elif self.source_type == "financial":
            return "FINANCIAL"
        elif self.source_type == "web":
            return "WEB"
        return "DOCUMENT"


class CitationTracker:
    """
    Collects, deduplicates, and formats citations during RAG pipeline.
    """

    def __init__(self):
        self._citations: list[Citation] = []
        self._seen: set[tuple] = set()  # (source_type, source, page) for dedup

    def add(
        self,
        source: str,
        source_type: str = "rag",
        page: Optional[int] = None,
        snippet: str = "",
        score: float = 0.0,
        url: str = "",
        name_en: str = "",
        data_year: str = "",
    ) -> None:
        """Add a citation. Duplicates (same source+type+page) are skipped."""
        key = (source_type, source, page or 0)
        if key in self._seen:
            return
        self._seen.add(key)

        label_map = {"rag": "source", "term": "term", "financial": "financial", "web": "web"}
        citation = Citation(
            source=source,
            source_label=label_map.get(source_type, "source"),
            source_type=source_type,
            page=page,
            snippet=snippet[:200],
            score=score,
            url=url,
            name_en=name_en,
            data_year=data_year,
        )
        self._citations.append(citation)

    def add_term(self, name: str) -> None:
        """Convenience: add a terminology citation."""
        self.add(source=name, source_type="term")

    def add_rag(self, source: str, page: int, snippet: str, score: float) -> None:
        """Convenience: add a RAG (PDF) citation."""
        self.add(source=source, source_type="rag", page=page, snippet=snippet, score=score)

    def add_financial(self, company: str, name_en: str = "", year: str = "") -> None:
        """Convenience: add a financial data citation."""
        self.add(source=company, source_type="financial", name_en=name_en, data_year=year)

    def add_web(self, title: str, url: str, snippet: str = "") -> None:
        """Convenience: add a web search citation."""
        self.add(source=title, source_type="web", snippet=snippet, url=url)

    def to_list(self) -> list[dict]:
        """Export citations as serializable dicts for SSE transmission."""
        return [
            {
                "source": c.source,
                "source_type": c.source_type,
                "display_source": c.display_source(),
                "icon": c.icon(),
                "page": c.page,
                "snippet": c.snippet,
                "score": c.score,
                "url": c.url,
                "name_en": c.name_en,
                "data_year": c.data_year,
            }
            for c in self._citations
        ]

    def is_empty(self) -> bool:
        return len(self._citations) == 0

    @staticmethod
    def format_panel(citations: list[dict], lang: str = "zh") -> str:
        """
        Build the HTML for a collapsible citation panel.

        Args:
            citations: citation dicts from to_list()
            lang: "zh" or "en"

        Returns:
            HTML string for the <details> panel
        """
        if not citations:
            return ""

        if lang == "zh":
            heading = f"引用溯源（{len(citations)}个来源）"
            hint = "点击展开查看原始文本片段"
        else:
            heading = f"Sources ({len(citations)})"
            hint = "Click to expand and view original text excerpts"

        items = []
        for i, c in enumerate(citations, 1):
            snippet_html = ""
            if c.get("snippet"):
                escaped = c["snippet"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                snippet_html = f'<div class="citation-snippet">"{escaped}"</div>'

            # Web citations get a clickable link icon
            if c.get("source_type") == "web" and c.get("url"):
                display = (
                    f'<a href="{c["url"]}" target="_blank" rel="noopener" '
                    f'class="citation-web-link" title="Open source in new tab">'
                    f'{c["display_source"]} ↗</a>'
                )
            else:
                display = c["display_source"]

            items.append(
                f'<div class="citation-item" id="cite-{i}">'
                f'<span class="citation-index">[{i}]</span> '
                f'<span class="citation-source">'
                f'<span class="citation-icon">{c["icon"]}</span> '
                f"{display}"
                f"</span>"
                f"{snippet_html}"
                f"</div>"
            )

        return (
            f'<details class="citation-panel">'
            f'<summary><span class="citation-heading">{heading}</span>'
            f'<span class="citation-hint">{hint}</span></summary>'
            f'<div class="citation-list">{"".join(items)}</div>'
            f"</details>"
        )
