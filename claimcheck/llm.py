"""OpenAI-compatible chat client, and a replay client for tests.

The replay client is the supported way to run without a network or an API key.
Tests use it. A live call is optional and is not required for the suite.
"""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from claimcheck.errors import ConfigError, LLMError

DEFAULT_BASE_URL = "https://api.openai.com/v1"
ChatTransport = Callable[[str, dict[str, str], dict[str, object], float], dict[str, object]]


@dataclass(frozen=True)
class LLMConfig:
    """Where to send a chat completion. The base URL is the API root, ending in /v1."""

    base_url: str
    model: str
    api_key: str | None
    timeout: float = 60.0


class ReplayClient:
    """Returns recorded model responses in order. No network."""

    def __init__(self, responses: Sequence[str]) -> None:
        if not responses:
            raise ValueError("ReplayClient needs at least one recorded response")
        self._responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        if not self._responses:
            raise LLMError("Replay client ran out of recorded responses")
        return self._responses.pop(0)


class OpenAICompatibleClient:
    """POST {base_url}/chat/completions and return the assistant message content."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        transport: ChatTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or urllib_transport

    def complete(self, *, system: str, user: str) -> str:
        url = self._config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        payload: dict[str, object] = {
            "model": self._config.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            body = self._transport(url, headers, payload, self._config.timeout)
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        return _message_content(body)


def load_config_from_env() -> LLMConfig:
    """Read CLAIMCHECK_* settings, falling back to OPENAI_* for the same fields.

    CLAIMCHECK_MODEL (or OPENAI_MODEL) is required. There is no hidden default
    model. CLAIMCHECK_API_KEY may be empty for a local server that does not
    check a key. CLAIMCHECK_BASE_URL defaults to the OpenAI API root.
    """
    base_url = (
        os.environ.get("CLAIMCHECK_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or DEFAULT_BASE_URL
    ).strip()
    model = (os.environ.get("CLAIMCHECK_MODEL") or os.environ.get("OPENAI_MODEL") or "").strip()
    if not model:
        raise ConfigError(
            "Set CLAIMCHECK_MODEL (or OPENAI_MODEL) to the model name. "
            "ClaimCheck does not pick a default model. "
            "To run without an API, pass --replay with a recorded response."
        )
    if "CLAIMCHECK_API_KEY" in os.environ:
        api_key: str | None = os.environ.get("CLAIMCHECK_API_KEY", "")
    elif "OPENAI_API_KEY" in os.environ:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    else:
        api_key = None
    if api_key is not None and api_key.strip() == "":
        api_key = None
    timeout_raw = os.environ.get("CLAIMCHECK_TIMEOUT", "60").strip()
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise ConfigError(f"CLAIMCHECK_TIMEOUT must be a number, got {timeout_raw!r}") from exc
    if timeout <= 0:
        raise ConfigError("CLAIMCHECK_TIMEOUT must be greater than 0")
    if not base_url:
        raise ConfigError("CLAIMCHECK_BASE_URL is empty")
    return LLMConfig(base_url=base_url, model=model, api_key=api_key, timeout=timeout)


def load_replay(path: Path) -> ReplayClient:
    """Load recorded responses from a file.

    A JSON list of strings, or an object with a "responses" list of strings,
    is a sequence of attempts. Any other file contents, including a JSON
    object that is itself the model output, is one response.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LLMError(f"Could not read replay file {path}: {exc}") from exc
    return ReplayClient(interpret_replay(raw))


def interpret_replay(raw: str) -> list[str]:
    stripped = raw.strip()
    if not stripped:
        raise LLMError("Replay file is empty")
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return [raw]
    if isinstance(data, str):
        return [data]
    if isinstance(data, list) and all(isinstance(item, str) for item in data):
        if not data:
            raise LLMError("Replay file has an empty response list")
        return list(data)
    if isinstance(data, dict) and "responses" in data:
        responses = data["responses"]
        if (
            not isinstance(responses, list)
            or not responses
            or not all(isinstance(item, str) for item in responses)
        ):
            raise LLMError("Replay file field 'responses' must be a non-empty list of strings")
        return list(responses)
    return [raw]


def urllib_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout: float,
) -> dict[str, object]:
    """POST JSON with the standard library. Used only when a live model is requested."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise LLMError(f"LLM request returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"LLM request failed: {exc.reason}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError("LLM response was not JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMError("LLM response JSON was not an object")
    return parsed


def _message_content(body: dict[str, object]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMError("LLM response did not include choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMError("LLM response choices[0] was not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMError("LLM response did not include a message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMError("LLM response message content was empty")
    return content
