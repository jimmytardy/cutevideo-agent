"""Repli Vertex AI de Gemini (voix et revue `analyze`) : clé Gemini → Vertex → repli existant."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors

GCP_JSON = json.dumps({"type": "service_account", "project_id": "proj-user"})
PCM = b"\x00\x00" * 4800  # 0,2 s de silence à 24 kHz


def _quota_error() -> errors.ClientError:
    return errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})


@pytest.fixture
def fake_genai(monkeypatch: pytest.MonkeyPatch) -> dict:
    """`genai.Client` simulé : enregistre chaque client ; `fail_key` fait échouer les appels avec clé."""
    state: dict = {"clients": [], "fail_key": None, "text": '{"total": 80}'}

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            state["clients"].append(kwargs)
            self.models = SimpleNamespace(generate_content=self._generate)

        def _generate(self, **_kw):
            if "api_key" in self.kwargs and state["fail_key"] is not None:
                raise state["fail_key"]
            part = SimpleNamespace(inline_data=SimpleNamespace(data=PCM))
            return SimpleNamespace(
                text=state["text"], candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))]
            )

    monkeypatch.setattr("google.genai.Client", FakeClient)
    monkeypatch.setattr("agent.core.vertex.vertex_credentials", lambda _json: "creds")
    return state


def _no_vertex_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent.core.config.load_agent_config", lambda: {"tts": {"gemini": {}}})


def test_tts_without_gemini_key_uses_vertex(fake_genai: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from agent.skills.audio.tts import generate_tts

    _no_vertex_overrides(monkeypatch)
    duration, engine = asyncio.run(generate_tts(
        "Bonjour.", tmp_path / "v.wav", voice="Leda", engine="gemini",
        gcp_credentials_json=GCP_JSON, gcp_location="us-central1",
    ))
    assert engine == "gemini-vertex" and duration > 0
    assert fake_genai["clients"] == [
        {"vertexai": True, "project": "proj-user", "location": "us-central1", "credentials": "creds"}
    ]


def test_tts_vertex_model_and_region_from_config(fake_genai: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.skills.audio.gemini_tts import DEFAULT_VERTEX_TTS_MODEL, vertex_tts_target

    _no_vertex_overrides(monkeypatch)
    assert vertex_tts_target(None) is None
    target = vertex_tts_target(GCP_JSON, "europe-west1")
    assert (target.location, target.model) == ("europe-west1", DEFAULT_VERTEX_TTS_MODEL)
    monkeypatch.setattr(
        "agent.core.config.load_agent_config",
        lambda: {"tts": {"gemini": {"vertex_location": "global", "vertex_model": "m-tts"}}},
    )
    target = vertex_tts_target(GCP_JSON, "europe-west1")
    assert (target.location, target.model) == ("global", "m-tts")


def test_tts_tool_retries_via_vertex_when_key_is_refused(
    fake_genai: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from studio import tools

    _no_vertex_overrides(monkeypatch)
    fake_genai["fail_key"] = _quota_error()
    monkeypatch.setenv("STUDIO_GEMINI_API_KEY", "AIza-user")
    monkeypatch.setenv("STUDIO_GCP_CREDENTIALS_JSON", GCP_JSON)
    monkeypatch.setenv("STUDIO_GCP_LOCATION", "us-central1")
    (tmp_path / "brief.json").write_text(json.dumps({"tts_engine": "gemini", "voice": "Leda"}), encoding="utf-8")
    (tmp_path / "narration.txt").write_text("Bonjour.", encoding="utf-8")
    args = argparse.Namespace(
        text_file="narration.txt", out="voice.wav", engine=None, voice=None, style=None,
        rate=None, pitch=None, mood=None, max_pause=0,
    )
    result = asyncio.run(tools.cmd_tts(args, tmp_path))
    assert result["engine"] == "gemini-vertex"
    assert [("api_key" in c, c.get("vertexai")) for c in fake_genai["clients"]] == [(True, None), (False, True)]


def test_tts_key_error_without_gcp_is_raised(fake_genai: dict, tmp_path: Path) -> None:
    from agent.skills.audio.tts import generate_tts

    fake_genai["fail_key"] = _quota_error()
    with pytest.raises(errors.ClientError):
        asyncio.run(generate_tts("Bonjour.", tmp_path / "v.wav", engine="gemini", gemini_api_key="AIza-user"))


def test_tts_engine_without_key_nor_gcp_falls_back_to_azure_then_edge() -> None:
    from agent.skills.audio.tts import resolve_engine

    assert resolve_engine("gemini") == "edge-tts"
    assert resolve_engine("gemini", azure_speech_key="az") == "azure"
    assert resolve_engine("gemini", gcp_credentials_json=GCP_JSON) == "gemini"


def _video(tmp_path: Path) -> Path:
    video = tmp_path / "v1.mp4"
    video.write_bytes(b"\x00" * 64)
    return video


def test_review_without_key_uses_vertex(fake_genai: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from studio.analyze import _gemini_section

    monkeypatch.delenv("STUDIO_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("STUDIO_GCP_CREDENTIALS_JSON", GCP_JSON)
    monkeypatch.setenv("STUDIO_GCP_LOCATION", "europe-west1")
    section = asyncio.run(_gemini_section("auto", _video(tmp_path), ""))
    assert section == {"gemini": {"total": 80}, "source": "gemini-vertex"}
    assert fake_genai["clients"][0]["location"] == "europe-west1"


def test_review_retries_via_vertex_when_key_is_refused(
    fake_genai: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from studio.analyze import _gemini_section

    fake_genai["fail_key"] = _quota_error()
    monkeypatch.setenv("STUDIO_GEMINI_API_KEY", "AIza-user")
    monkeypatch.setenv("STUDIO_GCP_CREDENTIALS_JSON", GCP_JSON)
    section = asyncio.run(_gemini_section("auto", _video(tmp_path), ""))
    assert section["source"] == "gemini-vertex" and "gemini_error" not in section


def test_review_with_working_key_stays_on_gemini(
    fake_genai: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from studio.analyze import _gemini_section

    monkeypatch.setenv("STUDIO_GEMINI_API_KEY", "AIza-user")
    monkeypatch.setenv("STUDIO_GCP_CREDENTIALS_JSON", GCP_JSON)
    section = asyncio.run(_gemini_section("auto", _video(tmp_path), ""))
    assert section["source"] == "gemini" and len(fake_genai["clients"]) == 1


def test_review_without_key_nor_gcp_falls_back_to_claude(
    fake_genai: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from studio.analyze import _gemini_section

    monkeypatch.delenv("STUDIO_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("STUDIO_GCP_CREDENTIALS_JSON", raising=False)
    section = asyncio.run(_gemini_section("auto", _video(tmp_path), ""))
    assert section["source"] == "claude" and "ni compte Google Cloud" in section["gemini_error"]
    assert fake_genai["clients"] == []
