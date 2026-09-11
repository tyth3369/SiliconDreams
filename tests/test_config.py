from config import SearchConfig


def test_tavily_placeholder_is_not_treated_as_configured(monkeypatch):
    monkeypatch.setattr(SearchConfig, "api_key", "tvly-your-tavily-api-key-here")
    assert SearchConfig.is_configured() is False


def test_real_tavily_key_is_treated_as_configured(monkeypatch):
    monkeypatch.setattr(SearchConfig, "api_key", "tvly-test-value")
    assert SearchConfig.is_configured() is True
