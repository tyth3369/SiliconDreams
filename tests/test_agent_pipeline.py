import json

from src.agent_loop import _format_duration, run_agent_loop
from src.citation import CitationTracker


def _events(generator):
    parsed = []
    for event in generator:
        assert event.startswith("data: ")
        parsed.append(json.loads(event.removeprefix("data: ").strip()))
    return parsed


def test_submillisecond_duration_is_not_rendered_as_zero():
    assert _format_duration(0.0004) == "<1ms"


class BoundedClient:
    def __init__(self):
        self.planning_calls = 0

    def chat_with_tools(self, messages, tools, model=None, tool_choice="auto"):
        self.planning_calls += 1
        tool_names = {tool["function"]["name"] for tool in tools}
        if "web_search" in tool_names:
            return {
                "tool_calls": [
                    {"id": "web-1", "name": "web_search", "arguments": {"query": "TSMC Q4"}},
                    {"id": "web-dup", "name": "web_search", "arguments": {"query": "TSMC Q4"}},
                    {
                        "id": "company-1",
                        "name": "get_company_data",
                        "arguments": {
                            "company": "TSMC",
                            "periods": ["2025 Q3", "2025 Q4"],
                        },
                    },
                ]
            }
        return {
            "tool_calls": [
                {
                    "id": "calc-1",
                    "name": "financial_calculator",
                    "arguments": {
                        "operation": "qoq_growth",
                        "operands": {"current": 33.73, "previous": 33.1},
                    },
                }
            ]
        }

    @staticmethod
    def chat_stream(messages, model=None):
        yield "answer"


def test_pipeline_has_one_retrieval_plan_and_one_calculation_plan(monkeypatch):
    executed = []

    def fake_execute(name, arguments, tracker):
        executed.append((name, arguments))
        if name == "web_search":
            tracker.add_web("TSMC Results", "https://example.com/results")
        return "evidence"

    monkeypatch.setattr("src.agent_loop.execute_tool", fake_execute)
    client = BoundedClient()
    events = _events(
        run_agent_loop(
            client,
            [{"role": "user", "content": "台积电Q4环比增长"}],
            CitationTracker(),
        )
    )
    assert client.planning_calls == 2
    names = [name for name, _args in executed]
    assert sorted(names[:2]) == ["get_company_data", "web_search"]
    assert names[2] == "financial_calculator"
    assert any(event.get("token") == "answer" for event in events)
    assert events[-1] == {"done": True}


class NoToolClient:
    def __init__(self):
        self.planning_calls = 0

    def chat_with_tools(self, messages, tools, model=None, tool_choice="auto"):
        self.planning_calls += 1
        return {"tool_calls": None}

    @staticmethod
    def chat_stream(messages, model=None):
        yield "direct answer"


def test_non_numeric_question_never_enters_a_loop():
    client = NoToolClient()
    events = _events(
        run_agent_loop(
            client,
            [{"role": "user", "content": "你好"}],
            CitationTracker(),
        )
    )
    assert client.planning_calls == 1
    assert events[-1] == {"done": True}


def test_invalid_planned_arguments_are_rejected(monkeypatch):
    class InvalidClient(NoToolClient):
        def chat_with_tools(self, messages, tools, model=None, tool_choice="auto"):
            self.planning_calls += 1
            return {"tool_calls": [{"id": "bad", "name": "web_search", "arguments": {}}]}

    monkeypatch.setattr(
        "src.agent_loop.execute_tool",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not execute")),
    )
    events = _events(
        run_agent_loop(
            InvalidClient(),
            [{"role": "user", "content": "hello"}],
            CitationTracker(),
        )
    )
    assert events[-1] == {"done": True}


def test_unavailable_retrieval_paths_are_not_advertised():
    seen_tool_names = set()

    class InspectingClient(NoToolClient):
        def chat_with_tools(self, messages, tools, model=None, tool_choice="auto"):
            self.planning_calls += 1
            seen_tool_names.update(tool["function"]["name"] for tool in tools)
            return {"tool_calls": None}

    list(
        run_agent_loop(
            InspectingClient(),
            [{"role": "user", "content": "hello"}],
            CitationTracker(),
            available_retrieval_tools={"lookup_terms"},
        )
    )
    assert seen_tool_names == {"lookup_terms"}
