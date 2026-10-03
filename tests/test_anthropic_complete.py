"""Appel Anthropic : marge de réflexion, repli serveur et continuation sans prefill."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent.core.llm_resolver import (
    ANTHROPIC_THINKING_HEADROOM_TOKENS,
    CONTINUATION_PROMPT,
    SERVER_FALLBACK_BETA,
    _anthropic_complete,
)


def _response(text: str, stop_reason: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        stop_details=None,
    )


class _FakeStream:
    def __init__(self, response: SimpleNamespace) -> None:
        self._response = response

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get_final_message(self) -> SimpleNamespace:
        return self._response


class _FakeClient:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs: Any) -> _FakeStream:
        self.calls.append(kwargs)
        return _FakeStream(self._responses.pop(0))


def _kwargs(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
    }


@pytest.mark.asyncio
async def test_thinking_model_gets_headroom_and_server_fallback() -> None:
    client = _FakeClient([_response("ok", "end_turn")])
    text = await _anthropic_complete(client, _kwargs("claude-opus-5-5"), "test_agent", "claude-opus-5-5")

    assert text == "ok"
    call = client.calls[0]
    assert call["max_tokens"] == 1024 + ANTHROPIC_THINKING_HEADROOM_TOKENS
    assert call["fallbacks"] == "default"
    assert call["betas"] == [SERVER_FALLBACK_BETA]


@pytest.mark.asyncio
async def test_haiku_keeps_budget_and_no_fallback() -> None:
    client = _FakeClient([_response("ok", "end_turn")])
    await _anthropic_complete(client, _kwargs("claude-haiku-4-5-20251001"), "test_agent", "claude-haiku-4-5-20251001")

    call = client.calls[0]
    assert call["max_tokens"] == 1024
    assert "fallbacks" not in call
    assert "betas" not in call


@pytest.mark.asyncio
async def test_continuation_ends_with_user_turn_not_prefill() -> None:
    client = _FakeClient([_response("début ", "max_tokens"), _response("fin", "end_turn")])
    text = await _anthropic_complete(client, _kwargs("claude-sonnet-5-5"), "test_agent", "claude-sonnet-5-5")

    assert text == "début fin"
    messages = client.calls[1]["messages"]
    assert messages[-2] == {"role": "assistant", "content": "début "}
    assert messages[-1] == {"role": "user", "content": CONTINUATION_PROMPT}
