from __future__ import annotations

import pytest

from agent.core.env import env_float, env_int, env_optional_float


def test_env_int_defaults_and_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CV_TEST_INT", raising=False)
    assert env_int("CV_TEST_INT", 3) == 3
    monkeypatch.setenv("CV_TEST_INT", "0")
    assert env_int("CV_TEST_INT", 3, minimum=1) == 1
    monkeypatch.setenv("CV_TEST_INT", "abc")
    assert env_int("CV_TEST_INT", 3) == 3


def test_env_float_and_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_TEST_FLOAT", "2.5")
    assert env_float("CV_TEST_FLOAT", 1.0) == 2.5
    monkeypatch.setenv("CV_TEST_FLOAT", "")
    assert env_float("CV_TEST_FLOAT", 1.0) == 1.0
    assert env_optional_float("CV_TEST_FLOAT") is None
    monkeypatch.setenv("CV_TEST_FLOAT", "oops")
    assert env_optional_float("CV_TEST_FLOAT") is None
