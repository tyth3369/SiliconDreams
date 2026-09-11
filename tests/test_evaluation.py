from src.evaluation import evaluate_retrieval, load_cases


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
    cases = load_cases("tests/fixtures/retrieval_golden.json")
    report = evaluate_retrieval(FixtureRetriever(), cases, top_k=5)
    assert report["recall_at_k"] == 1.0
    assert report["mrr"] == 0.75
    assert report["cases"] == 2


def test_empty_evaluation_set_is_explicit():
    report = evaluate_retrieval(FixtureRetriever(), [])
    assert report == {"cases": 0, "recall_at_k": 0.0, "mrr": 0.0, "details": []}
