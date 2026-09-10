from src.citation import CitationTracker


def test_citation_tracker_deduplicates_same_source():
    tracker = CitationTracker()
    tracker.add_term("先进制程")
    tracker.add_term("先进制程")
    assert len(tracker.to_list()) == 1


def test_web_citation_preserves_url():
    tracker = CitationTracker()
    tracker.add_web("TSMC release", "https://example.com/release", "source excerpt")
    citation = tracker.to_list()[0]
    assert citation["url"] == "https://example.com/release"
    assert citation["source_type"] == "web"


def test_financial_citation_is_descriptive():
    tracker = CitationTracker()
    tracker.add_financial(
        "台积电",
        name_en="TSMC",
        year="2025",
        reference_title="TSMC 4Q25 Quarterly Management Report",
        url="https://example.com/tsmc-q4.pdf",
    )
    display = tracker.to_list()[0]["display_source"]
    assert "FY2025" in display
    assert "Quarterly Management Report" in display


def test_rag_citation_includes_page():
    tracker = CitationTracker()
    tracker.add_rag("annual-report.pdf", page=42, snippet="margin", score=0.9)
    assert tracker.to_list()[0]["display_source"] == "annual-report.pdf · p42"


def test_empty_tracker_reports_empty():
    assert CitationTracker().is_empty()


def test_panel_escapes_snippet_html():
    tracker = CitationTracker()
    tracker.add_web("safe title", "https://example.com", '<script>alert("x")</script>')
    panel = CitationTracker.format_panel(tracker.to_list())
    assert "<script>" not in panel
    assert "&lt;script&gt;" in panel


def test_panel_rejects_javascript_url():
    tracker = CitationTracker()
    tracker.add_web("unsafe", "javascript:alert(1)", "text")
    panel = CitationTracker.format_panel(tracker.to_list())
    assert "javascript:" not in panel
    assert "<a href=" not in panel


def test_panel_escapes_source_title():
    tracker = CitationTracker()
    tracker.add_web("<img src=x onerror=alert(1)>", "https://example.com", "text")
    panel = CitationTracker.format_panel(tracker.to_list())
    assert "<img" not in panel
    assert "&lt;img" in panel
