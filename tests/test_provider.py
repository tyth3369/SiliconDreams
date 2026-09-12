from types import SimpleNamespace

from src.providers.deepseek import DeepSeekProvider


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def _provider(*responses):
    provider = DeepSeekProvider.__new__(DeepSeekProvider)
    completions = FakeCompletions(responses)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider.model = "deepseek-v4-flash"
    provider.reasoner_model = "deepseek-v4-pro"
    provider.max_tokens = 1024
    provider.temperature = 0.3
    provider.max_retries = 2
    provider.retry_delay = 0
    return provider, completions


def test_chat_disables_thinking_for_predictable_visible_output():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))])
    provider, completions = _provider(response)

    assert provider.chat([{"role": "user", "content": "question"}]) == "answer"
    assert completions.calls[0]["model"] == "deepseek-v4-flash"
    assert completions.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert completions.calls[0]["stream"] is False


def test_tool_calls_are_parsed_and_invalid_json_is_safely_rejected():
    tool_calls = [
        SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="web_search", arguments='{"query":"TSMC"}'),
        ),
        SimpleNamespace(
            id="call-2",
            function=SimpleNamespace(name="search_reports", arguments="not-json"),
        ),
    ]
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=20,
            completion_tokens=4,
            total_tokens=24,
            prompt_cache_hit_tokens=12,
            prompt_cache_miss_tokens=8,
        ),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=tool_calls),
                finish_reason="tool_calls",
            )
        ],
    )
    provider, _ = _provider(response)

    result = provider.chat_with_tools([], [{"type": "function"}])
    assert result["tool_calls"][0]["arguments"] == {"query": "TSMC"}
    assert result["tool_calls"][1]["arguments"] == {}
    assert result["finish_reason"] == "tool_calls"
    assert result["usage"]["prompt_cache_hit_tokens"] == 12


def test_stream_yields_only_content_tokens():
    seen_usage = []
    chunks = iter(
        [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="A"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="B"))],
                usage={"prompt_tokens": 8, "completion_tokens": 2},
            ),
        ]
    )
    provider, completions = _provider(chunks)

    assert list(provider.chat_stream([], usage_callback=seen_usage.append)) == ["A", "B"]
    assert completions.calls[0]["stream"] is True
    assert completions.calls[0]["stream_options"] == {"include_usage": True}
    assert seen_usage[0]["completion_tokens"] == 2


def test_retry_recovers_from_transient_error():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
    provider, completions = _provider(RuntimeError("temporary"), response)

    assert provider.chat([]) == "ok"
    assert len(completions.calls) == 2
