"""
SiliconDreams — Citation Data Model & Formatter
================================================
Tracks knowledge sources used in LLM responses and formats
collapsible citation panels for the chat frontend.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from urllib.parse import urlparse


def safe_external_url(value: str) -> str:
    """Allow only absolute HTTP(S) citation links."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return value


@dataclass
class Citation:
    """A single citation pointing to a knowledge source."""

    source: str  # filename, term name, or company name
    source_label: str  # "source" | "term" | "financial"
    source_type: str  # "rag" | "term" | "financial"
    page: int | None = None  # page number (None for terms/financial)
    snippet: str = ""  # bounded evidence excerpt
    score: float = 0.0  # relevance score (0-1 for RAG)
    url: str = ""  # web search URL (empty for non-web citations)
    name_en: str = ""  # company English name/ticker (for financial type)
    data_year: str = ""  # data year (for financial type)
    reference_title: str = ""  # exact filing or release title
    publisher: str = ""
    published_at: str = ""
    trust_tier: int = 3
    date_status: str = ""

    def display_source(self) -> str:
        """Human-readable source identifier."""
        if self.source_type == "term":
            return f"{self.source} ({self.name_en})" if self.name_en else self.source
        elif self.source_type == "financial":
            parts = [self.source]
            if self.name_en:
                parts.append(f" ({self.name_en})")
            if self.data_year:
                period = self.data_year
                if period.startswith("FY") or " Q" in period:
                    parts.append(f" · {period}")
                else:
                    parts.append(f" · FY{period}")
            else:
                parts.append(" 财务数据")
            if self.reference_title:
                parts.append(f" · {self.reference_title}")
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
        page: int | None = None,
        snippet: str = "",
        score: float = 0.0,
        url: str = "",
        name_en: str = "",
        data_year: str = "",
        reference_title: str = "",
        publisher: str = "",
        published_at: str = "",
        trust_tier: int = 3,
        date_status: str = "",
    ) -> None:
        """Add a citation. Duplicates (same source+type+page) are skipped."""
        key = (
            source_type,
            source,
            page or 0,
            data_year if source_type == "financial" else "",
            reference_title if source_type == "financial" else "",
        )
        if key in self._seen:
            return
        self._seen.add(key)

        label_map = {"rag": "source", "term": "term", "financial": "financial", "web": "web"}
        citation = Citation(
            source=source,
            source_label=label_map.get(source_type, "source"),
            source_type=source_type,
            page=page,
            snippet=snippet[:800],
            score=score,
            url=url,
            name_en=name_en,
            data_year=data_year,
            reference_title=reference_title,
            publisher=publisher,
            published_at=published_at,
            trust_tier=trust_tier,
            date_status=date_status,
        )
        self._citations.append(citation)

    def add_term(self, name: str, *, name_en: str = "", snippet: str = "") -> None:
        """Convenience: add a terminology citation."""
        self.add(source=name, source_type="term", name_en=name_en, snippet=snippet)

    def add_rag(self, source: str, page: int, snippet: str, score: float) -> None:
        """Convenience: add a RAG (PDF) citation."""
        self.add(source=source, source_type="rag", page=page, snippet=snippet, score=score)

    def add_financial(
        self,
        company: str,
        name_en: str = "",
        year: str = "",
        reference_title: str = "",
        url: str = "",
        publisher: str = "",
        published_at: str = "",
        trust_tier: int = 1,
        snippet: str = "",
    ) -> None:
        """Convenience: add a financial data citation."""
        self.add(
            source=company,
            source_type="financial",
            name_en=name_en,
            data_year=year,
            reference_title=reference_title,
            url=url,
            publisher=publisher,
            published_at=published_at,
            trust_tier=trust_tier,
            snippet=snippet,
        )

    def add_web(
        self,
        title: str,
        url: str,
        snippet: str = "",
        publisher: str = "",
        published_at: str = "",
        trust_tier: int = 3,
        date_status: str = "",
    ) -> None:
        """Convenience: add a web search citation."""
        self.add(
            source=title,
            source_type="web",
            snippet=snippet,
            url=url,
            publisher=publisher,
            published_at=published_at,
            trust_tier=trust_tier,
            date_status=date_status,
        )

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
                "reference_title": c.reference_title,
                "publisher": c.publisher,
                "published_at": c.published_at,
                "trust_tier": c.trust_tier,
                "date_status": c.date_status,
            }
            for c in self._citations
        ]

    def is_empty(self) -> bool:
        return len(self._citations) == 0

    def merge(self, other: CitationTracker) -> None:
        """Merge another tracker while preserving this tracker's stable order."""
        for citation in other._citations:
            self.add(
                source=citation.source,
                source_type=citation.source_type,
                page=citation.page,
                snippet=citation.snippet,
                score=citation.score,
                url=citation.url,
                name_en=citation.name_en,
                data_year=citation.data_year,
                reference_title=citation.reference_title,
                publisher=citation.publisher,
                published_at=citation.published_at,
                trust_tier=citation.trust_tier,
                date_status=citation.date_status,
            )

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
                escaped_snippet = escape(str(c["snippet"]), quote=True)
                snippet_html = (
                    f'<div class="citation-snippet">&ldquo;{escaped_snippet}&rdquo;</div>'
                )

            escaped_display = escape(str(c.get("display_source", "")), quote=True)
            citation_url = safe_external_url(str(c.get("url", "")))
            if citation_url:
                display = (
                    f'<a href="{escape(citation_url, quote=True)}" target="_blank" '
                    f'rel="noopener noreferrer" '
                    f'class="citation-web-link" title="Open source in new tab">'
                    f'{escaped_display}<span aria-hidden="true"> ↗</span></a>'
                )
            else:
                display = escaped_display

            escaped_icon = escape(str(c.get("icon", "SOURCE")), quote=True)
            metadata = []
            if c.get("publisher"):
                metadata.append(escape(str(c["publisher"]), quote=True))
            if c.get("published_at"):
                metadata.append(escape(str(c["published_at"]), quote=True))
            if c.get("source_type") in {"web", "financial"} and c.get("trust_tier"):
                tier_label = {
                    1: "Tier 1 · Official",
                    2: "Tier 2 · Reputable reporting",
                    3: "Tier 3 · Web source",
                }.get(int(c["trust_tier"]), f"Tier {int(c['trust_tier'])}")
                metadata.append(tier_label)
            if c.get("source_type") == "web":
                if c.get("date_status") == "undated":
                    metadata.append("Date unknown" if lang == "en" else "发布日期未知")
                elif c.get("date_status") == "stale":
                    metadata.append("Background source" if lang == "en" else "较旧背景来源")
            metadata_html = (
                f'<div class="citation-metadata">{" · ".join(metadata)}</div>' if metadata else ""
            )

            items.append(
                f'<div class="citation-item" data-cite-index="{i}">'
                f'<span class="citation-index">[{i}]</span> '
                f'<span class="citation-source">'
                f'<span class="citation-icon">{escaped_icon}</span> '
                f"{display}"
                f"</span>"
                f"{metadata_html}"
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
