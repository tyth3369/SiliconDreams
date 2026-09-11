import pymupdf

from src.exporter import build_markdown_export, build_pdf_export, export_filename


def sample_record():
    conversation = {"title": "台积电季度研究"}
    messages = [
        {"role": "user", "content": "对比两个季度。", "citations": []},
        {
            "role": "assistant",
            "content": (
                "## 核心数据\n\n"
                "| 指标 | Q3 | Q4 |\n"
                "| --- | ---: | ---: |\n"
                "| Revenue | 33.1 | 33.7 |\n\n"
                "Revenue increased modestly.[1]"
            ),
            "citations": [
                {
                    "icon": "WEB",
                    "display_source": "TSMC Quarterly Results",
                    "url": "https://investor.tsmc.com/english/quarterly-results/2025/q4",
                    "publisher": "TSMC",
                    "published_at": "2026-01-15",
                    "snippet": "Revenue was US$33.73 billion.",
                    "trust_tier": 1,
                    "source_type": "web",
                }
            ],
        },
    ]
    return conversation, messages


def test_markdown_export_preserves_content_and_provenance():
    conversation, messages = sample_record()
    output = build_markdown_export(conversation, messages)
    assert output.startswith("# 台积电季度研究")
    assert "| Revenue | 33.1 | 33.7 |" in output
    assert "[TSMC Quarterly Results](https://investor.tsmc.com" in output
    assert "Revenue was US$33.73 billion." in output


def test_pdf_export_is_readable_and_contains_table_content():
    conversation, messages = sample_record()
    output = build_pdf_export(conversation, messages)
    assert output.startswith(b"%PDF")
    assert len(output) > 2_000
    document = pymupdf.open(stream=output, filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    assert "Revenue" in text
    assert "33.7" in text
    assert "TSMC Quarterly Results" in text


def test_export_filename_is_safe_and_bounded():
    filename = export_filename({"title": "TSMC / Arizona: Q4?"}, "pdf")
    assert filename == "TSMC-Arizona-Q4.pdf"
    assert len(filename) <= 68
