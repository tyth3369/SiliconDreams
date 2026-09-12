import json
from pathlib import Path

from src.evaluation import citation_integrity, evaluate_citations, evaluate_retrieval, load_cases


class FixtureRetriever:
    RESULTS = {
        "台积电毛利率": [
            {"id": "noise", "text": "unrelated", "metadata": {"source": "other.pdf", "page": 1}},
            {
                "id": "tsmc",
                "text": "TSMC gross margin was reported here",
                "metadata": {"source": "TSMC-2025.pdf", "page": 12},
            },
        ],
        "中芯国际资本开支": [
            {
                "id": "smic",
                "text": "SMIC capital expenditure guidance",
                "metadata": {"source": "SMIC-2025.pdf", "page": 8},
            }
        ],
    }

    def retrieve(self, query, top_k=5, rerank=True):
        return self.RESULTS.get(query, [])[:top_k]


def test_retrieval_metrics_against_golden_fixture():
    cases = [
        {
            "query": "台积电毛利率",
            "expected": [{"source": "TSMC-2025.pdf", "page": 12, "contains": "gross margin"}],
        },
        {
            "query": "中芯国际资本开支",
            "expected": [{"source": "SMIC-2025.pdf", "page": 8, "contains": "capital expenditure"}],
        },
    ]
    report = evaluate_retrieval(FixtureRetriever(), cases, top_k=5)
    assert report["recall_at_k"] == 1.0
    assert report["mrr"] == 0.75
    assert report["cases"] == 2


def test_empty_evaluation_set_is_explicit():
    report = evaluate_retrieval(FixtureRetriever(), [])
    assert report == {"cases": 0, "recall_at_k": 0.0, "mrr": 0.0, "details": []}


def test_content_matching_normalizes_pdf_line_breaks():
    class LineBreakRetriever:
        @staticmethod
        def retrieve(_query, top_k=5, rerank=True):
            return [
                {
                    "text": "monthly capacity reached\n1,058,750 wafers",
                    "metadata": {"source": "report.pdf", "page": 71},
                }
            ]

    cases = [
        {
            "query": "capacity",
            "expected": [
                {
                    "source": "report.pdf",
                    "page": 71,
                    "contains": "monthly capacity reached 1,058,750",
                }
            ],
        }
    ]
    assert evaluate_retrieval(LineBreakRetriever(), cases)["recall_at_k"] == 1.0


def test_official_golden_set_is_bilingual_and_reviewed():
    fixture = Path(__file__).parent / "fixtures" / "retrieval_golden.json"
    cases = load_cases(fixture)

    assert len(cases) == 12
    assert [case["language"] for case in cases].count("zh") == 6
    assert [case["language"] for case in cases].count("en") == 6
    assert all(case["expected"] for case in cases)


def test_citation_integrity_rejects_out_of_range_markers():
    report = citation_integrity("Supported[1], broken[3].", [{"source": "one"}])
    assert report["marker_validity"] == 0.5
    assert report["invalid_markers"] == [3]


def test_citation_evaluation_measures_precision_and_claim_coverage():
    report = evaluate_citations(
        [
            {
                "id": "mixed",
                "answer": "Supported fact[1]. Unsupported mapping[2]. Uncited claim.",
                "citations": [{"source": "one"}, {"source": "two"}],
                "claims": [
                    {"text": "Supported fact[1]", "supported_by": [1]},
                    {"text": "Unsupported mapping[2]", "supported_by": [1]},
                    {"text": "Uncited claim", "supported_by": [2]},
                ],
            }
        ]
    )
    assert report["citation_precision"] == 0.5
    assert report["claim_coverage"] == 1 / 3
    assert report["marker_validity"] == 1.0


def test_reviewed_citation_golden_set_passes_release_thresholds():
    fixture = Path(__file__).parent / "fixtures" / "citation_golden.json"
    manifest = json.loads(fixture.read_text(encoding="utf-8"))
    report = evaluate_citations(manifest["cases"])
    assert len(manifest["cases"]) == 6
    assert {case["language"] for case in manifest["cases"]} == {"zh", "en"}
    assert report["citation_precision"] >= manifest["thresholds"]["citation_precision"]
    assert report["claim_coverage"] >= manifest["thresholds"]["claim_coverage"]
    assert report["marker_validity"] >= manifest["thresholds"]["marker_validity"]
