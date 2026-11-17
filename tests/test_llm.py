"""Replay files and the OpenAI-compatible client. No sockets."""

import pytest
from claimcheck.errors import ConfigError, LLMError
from claimcheck.llm import (
    LLMConfig,
    OpenAICompatibleClient,
    interpret_replay,
    load_config_from_env,
)


def test_config_requires_a_model_and_does_not_invent_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAIMCHECK_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(ConfigError, match="CLAIMCHECK_MODEL"):
        load_config_from_env()


def test_config_reads_claimcheck_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAIMCHECK_BASE_URL", "http://127.0.0.1:11434/v1/")
    monkeypatch.setenv("CLAIMCHECK_MODEL", "llama3.2")
    monkeypatch.setenv("CLAIMCHECK_API_KEY", "")
    config = load_config_from_env()
    assert config.base_url == "http://127.0.0.1:11434/v1/"
    assert config.model == "llama3.2"
    assert config.api_key is None


def test_openai_env_names_are_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAIMCHECK_MODEL", raising=False)
    monkeypatch.delenv("CLAIMCHECK_API_KEY", raising=False)
    monkeypatch.delenv("CLAIMCHECK_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    config = load_config_from_env()
    assert config.model == "gpt-test"
    assert config.api_key == "sk-test"


def test_client_posts_chat_completions_and_returns_content() -> None:
    seen: dict = {}

    def transport(url, headers, payload, timeout):
        seen["url"] = url
        seen["headers"] = headers
        seen["payload"] = payload
        seen["timeout"] = timeout
        return {"choices": [{"message": {"content": '{"claims": []}'}}]}

    client = OpenAICompatibleClient(
        LLMConfig(base_url="http://127.0.0.1:11434/v1", model="llama3.2", api_key="local"),
        transport=transport,
    )
    assert client.complete(system="sys", user="user") == '{"claims": []}'
    assert seen["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer local"
    assert seen["payload"]["messages"][0] == {"role": "system", "content": "sys"}
    assert seen["payload"]["temperature"] == 0


def test_empty_api_key_omits_the_authorization_header() -> None:
    seen: dict = {}

    def transport(url, headers, payload, timeout):
        seen["headers"] = headers
        return {"choices": [{"message": {"content": "ok"}}]}

    client = OpenAICompatibleClient(
        LLMConfig(base_url="http://127.0.0.1:9/v1", model="m", api_key=None),
        transport=transport,
    )
    client.complete(system="s", user="u")
    assert "Authorization" not in seen["headers"]


def test_missing_choices_is_an_llm_error() -> None:
    client = OpenAICompatibleClient(
        LLMConfig(base_url="http://127.0.0.1:9/v1", model="m", api_key=None),
        transport=lambda *args: {"choices": []},
    )
    with pytest.raises(LLMError, match="choices"):
        client.complete(system="s", user="u")


def test_replay_file_shapes() -> None:
    assert interpret_replay('{"claims": []}') == ['{"claims": []}']
    assert interpret_replay('["first", "second"]') == ["first", "second"]
    assert interpret_replay('{"responses": ["only"]}') == ["only"]
    assert interpret_replay("not json at all") == ["not json at all"]
    with pytest.raises(LLMError):
        interpret_replay("   ")
