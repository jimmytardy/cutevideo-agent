"""Moteur ElevenLabs et voix de secours par chaîne (HTTP simulé, aucun appel réel)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf

from agent.core import llm_retry
from agent.core.channel_config import TtsFormatProfile, _resolve_tts_fallback
from agent.core.subscription import SubscriptionLimits, apply_subscription_caps
from agent.skills.audio import elevenlabs_tts as el
from studio import tools


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Réponses successives de l'API ; renvoie les requêtes reçues. Pas d'attente ni de vrai ffmpeg."""
    requests: list[httpx.Request] = []

    def install(*statuses: tuple[int, dict | None]) -> list[httpx.Request]:
        replies = list(statuses)

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            status, body = replies.pop(0)
            return httpx.Response(status, json=body) if body is not None else httpx.Response(status, content=b"mp3")

        monkeypatch.setattr(el, "_transport", httpx.MockTransport(handler))
        return requests

    async def fake_normalize(src, dst, *, mastering=None):
        Path(dst).write_bytes(b"wav")
        return dst

    async def fake_probe(_path) -> float:
        return 1.5

    monkeypatch.setattr("agent.skills.audio.tts.normalize_wav", fake_normalize)
    monkeypatch.setattr(el, "probe_duration", fake_probe)
    monkeypatch.setattr(llm_retry, "TRANSIENT_BACKOFF_BASE_S", 0)
    return install


def _synth(tmp_path: Path, **overrides) -> float:
    kwargs = {"voice": "voix/1", "api_key": "el-secret", "rate": "+10%"} | overrides
    return asyncio.run(el.synthesize_elevenlabs_tts("Bonjour.", tmp_path / "o.wav", **kwargs))


def test_request_carries_key_voice_speed_and_context(api, tmp_path: Path) -> None:
    requests = api((200, None))
    assert _synth(tmp_path, previous_text="Avant.", next_text="Après.") == 1.5
    request = requests[0]
    assert request.headers["xi-api-key"] == "el-secret"
    assert str(request.url).split("?")[0].endswith("/voix%2F1")
    assert request.url.params["output_format"] == "mp3_44100_128"
    body = json.loads(request.content)
    assert body == {
        "text": "Bonjour.", "model_id": "eleven_multilingual_v2", "voice_settings": {"speed": 1.1},
        "previous_text": "Avant.", "next_text": "Après.",
    }
    assert not (tmp_path / "o.mp3").exists()


@pytest.mark.parametrize(("rate", "speed"), [("+0%", 1.0), ("-10%", 0.9), ("+90%", 1.2), ("-90%", 0.7), ("?", 1.0)])
def test_rate_to_speed_stays_in_api_range(rate: str, speed: float) -> None:
    assert el.rate_to_speed(rate) == speed


def test_rate_limit_is_retried(api, tmp_path: Path) -> None:
    requests = api((429, {"detail": {"code": "rate_limit_exceeded"}}), (200, None))
    assert _synth(tmp_path) == 1.5
    assert len(requests) == 2


@pytest.mark.parametrize("status", [401, 402, 403, 404])
def test_definitive_refusal_is_not_retried_and_hides_the_key(api, tmp_path: Path, status: int) -> None:
    # « 500 » dans le texte libre ne doit pas faire passer le refus pour une erreur temporaire.
    requests = api((status, {"detail": {"code": "refus", "message": "il reste 500 crédits"}}))
    with pytest.raises(el.ElevenLabsError) as exc:
        _synth(tmp_path)
    assert len(requests) == 1
    assert str(status) in str(exc.value) and "el-secret" not in str(exc.value)


@pytest.mark.parametrize("overrides", [{"api_key": None}, {"api_key": " "}, {"voice": ""}])
def test_missing_key_or_voice_raises_without_calling(api, tmp_path: Path, overrides: dict) -> None:
    requests = api()
    with pytest.raises(RuntimeError):
        _synth(tmp_path, **overrides)
    assert requests == []


# ── chaîne de repli de `studio.tools tts` ─────────────────────────────────


def _args(**overrides) -> argparse.Namespace:
    base = dict(text_file="narration.txt", out="voice.wav", engine=None, voice=None, style=None,
                rate="+0%", pitch="+0Hz", mood="calme", max_pause=0)
    return argparse.Namespace(**(base | overrides))


def _run(tmp_path: Path, monkeypatch, text: str, refused: set[str], **overrides):
    """Brief ElevenLabs + secours Gemini Charon ; renvoie (sortie de l'outil, appels (moteur, voix, texte, kw))."""
    (tmp_path / "brief.json").write_text(json.dumps({
        "tts_engine": "elevenlabs", "voice": "el-voice",
        "tts_fallback_engine": "gemini", "tts_fallback_voice": "Charon",
    }), encoding="utf-8")
    (tmp_path / "narration.txt").write_text(text, encoding="utf-8")
    calls: list[tuple[str, str, str, dict]] = []

    async def fake_generate_tts(seg, output_path, *, voice, engine, **kw):
        calls.append((engine, voice, seg, kw))
        if engine in refused:
            raise el.ElevenLabsError(402, "insufficient_credits")
        sf.write(str(output_path), np.full(2400, 0.1, dtype=np.float32), 24000, subtype="PCM_16")
        return 0.1, engine

    monkeypatch.setattr("agent.skills.audio.tts.generate_tts", fake_generate_tts)
    monkeypatch.setenv("STUDIO_GEMINI_API_KEY", "g")  # sinon resolve_engine écarte Gemini
    return asyncio.run(tools.cmd_tts(_args(**overrides), tmp_path)), calls


def test_refused_engine_uses_channel_fallback_for_whole_narration(tmp_path: Path, monkeypatch) -> None:
    out, calls = _run(tmp_path, monkeypatch, "Un.\nDeux.", {"elevenlabs"})
    assert out["engine"] == "gemini" and out["voice"] == "Charon"
    assert "402" in out["fallback_errors"]["elevenlabs"]
    assert [c[:3] for c in calls] == [("elevenlabs", "el-voice", "Un."), ("gemini", "Charon", "Un."),
                                      ("gemini", "Charon", "Deux.")]
    status = json.loads((tmp_path / "tts_status.json").read_text(encoding="utf-8"))
    assert status["engine"] == "gemini" and "elevenlabs" in status["fallback_errors"]


def test_no_key_goes_to_fallback_not_edge(tmp_path: Path, monkeypatch) -> None:
    # Vrai `generate_tts` : sans clé, ElevenLabs ne doit pas être remplacé en silence par edge (`resolve_engine`).
    (tmp_path / "brief.json").write_text(json.dumps({
        "tts_engine": "elevenlabs", "voice": "v", "tts_fallback_engine": "gemini", "tts_fallback_voice": "Charon",
    }), encoding="utf-8")
    (tmp_path / "narration.txt").write_text("Un.", encoding="utf-8")
    monkeypatch.delenv("STUDIO_ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "cle-de-plateforme-ignoree")
    monkeypatch.setenv("STUDIO_GEMINI_API_KEY", "g")
    voices: list[str] = []

    async def fake_gemini(_text, output_path, *, voice, **_kw):
        voices.append(voice)
        sf.write(str(output_path), np.full(2400, 0.1, dtype=np.float32), 24000, subtype="PCM_16")
        return 0.1

    async def no_edge(*_a, **_kw):
        raise AssertionError("edge-tts ne doit pas remplacer la voix de secours")

    monkeypatch.setattr("agent.skills.audio.gemini_tts.synthesize_gemini_tts", fake_gemini)
    monkeypatch.setattr("agent.skills.audio.tts._generate_edge_tts", no_edge)
    out = asyncio.run(tools.cmd_tts(_args(), tmp_path))
    assert voices == ["Charon"] and out["engine"] == "gemini"
    assert "Clé ElevenLabs" in out["fallback_errors"]["elevenlabs"]


def test_fallback_engine_is_tried_before_the_default_chain(tmp_path: Path) -> None:
    (tmp_path / "brief.json").write_text(json.dumps({
        "tts_engine": "elevenlabs", "voice": "v", "tts_fallback_engine": "azure", "tts_fallback_voice": "fr-FR-X",
    }), encoding="utf-8")
    chain, voices = tools._tts_engine_chain(tmp_path, None)
    assert chain == ["elevenlabs", "azure", "gemini", "edge"]
    assert voices["azure"] == "fr-FR-X"


def test_refusal_during_a_retouch_rereads_everything_with_fallback(tmp_path: Path, monkeypatch) -> None:
    _run(tmp_path, monkeypatch, "Un.\nDeux.", set())
    out, calls = _run(tmp_path, monkeypatch, "Un.\nDeux, retouchée.", {"elevenlabs"})
    assert out["engine"] == "gemini"
    assert [c[2] for c in calls if c[0] == "gemini"] == ["Un.", "Deux, retouchée."]


def test_success_after_a_refusal_clears_the_alert(tmp_path: Path, monkeypatch) -> None:
    _run(tmp_path, monkeypatch, "Un.", {"elevenlabs"})
    _run(tmp_path, monkeypatch, "Un.", set())
    assert json.loads((tmp_path / "tts_status.json").read_text(encoding="utf-8"))["fallback_errors"] == {}


def test_ignored_settings_do_not_rebill_a_line(tmp_path: Path, monkeypatch) -> None:
    _run(tmp_path, monkeypatch, "Un.\nDeux.", set())
    out, calls = _run(tmp_path, monkeypatch, "[pitch=+8Hz mood=tension style=sad] Un.\nDeux.", set(), mood="dramatique")
    assert calls == [] and out["lines_reused"] == 2
    _out, calls = _run(tmp_path, monkeypatch, "[rate=+8%] Un.\nDeux.", set())
    assert [c[2] for c in calls] == ["Un."]  # le débit, lui, change l'audio


def test_neighbour_context_is_sent_but_not_in_the_cache_key(tmp_path: Path, monkeypatch) -> None:
    _out, calls = _run(tmp_path, monkeypatch, "Un.\nDeux.\nTrois.", set())
    assert calls[1][3]["previous_text"] == "Un." and calls[1][3]["next_text"] == "Trois."
    _out, calls = _run(tmp_path, monkeypatch, "Un.\nDeux.\nTrois, retouchée.", set())
    assert [c[2] for c in calls] == ["Trois, retouchée."]


# ── config de la chaîne et forfait ────────────────────────────────────────


PRIMARY = TtsFormatProfile(engine="elevenlabs", voice="v")


@pytest.mark.parametrize(
    ("fallback", "expected"),
    [
        ({"engine": "gemini", "voice": "Charon"}, ("gemini", "Charon")),
        ({"engine": "edge", "voice": "fr-FR-DeniseNeural"}, ("edge-tts", "fr-FR-DeniseNeural")),
        ({"engine": "elevenlabs", "voice": "autre"}, None),  # même moteur : même refus
        ({"engine": "nimporte", "voice": "x"}, None),
        ({"engine": "gemini"}, None),
        ("Charon", None),
    ],
)
def test_resolve_fallback(fallback, expected) -> None:
    profile = _resolve_tts_fallback({"short": {"fallback": fallback}}, PRIMARY)
    assert (profile.engine, profile.voice) == expected if expected else profile is None


def test_plan_removes_a_fallback_it_does_not_allow() -> None:
    limits = SubscriptionLimits(tts_allowed_engines=["edge", "elevenlabs"])
    cfg = {"tts": {"engine": "edge", "short": {"engine": "elevenlabs", "voice": "v",
                                               "fallback": {"engine": "gemini", "voice": "Charon"}}}}
    assert apply_subscription_caps(cfg, limits)["tts"]["short"] == {"engine": "elevenlabs", "voice": "v"}


def test_elevenlabs_is_allowed_by_default_since_the_user_pays() -> None:
    limits = SubscriptionLimits()
    assert limits.tts_allowed_engines[0] == "edge" and "elevenlabs" in limits.tts_allowed_engines


# ── retours de relecture ──────────────────────────────────────────────────


def test_read_timeout_is_not_retried_since_it_may_be_billed(monkeypatch, api, tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("lent", request=request)

    api()
    monkeypatch.setattr(el, "_transport", httpx.MockTransport(handler))
    with pytest.raises(RuntimeError):
        _synth(tmp_path)
    assert calls == [1]


def test_connection_error_is_retried(monkeypatch, api, tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("refus", request=request)
        return httpx.Response(200, content=b"mp3")

    api()
    monkeypatch.setattr(el, "_transport", httpx.MockTransport(handler))
    assert _synth(tmp_path) == 1.5 and len(calls) == 2


def test_keyless_azure_goes_to_channel_fallback_not_edge(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "brief.json").write_text(json.dumps({
        "tts_engine": "azure", "voice": "fr-FR-DeniseNeural",
        "tts_fallback_engine": "elevenlabs", "tts_fallback_voice": "el-voice",
    }), encoding="utf-8")
    (tmp_path / "narration.txt").write_text("Un.", encoding="utf-8")
    monkeypatch.delenv("STUDIO_AZURE_SPEECH_KEY", raising=False)
    seen: list[tuple[str, str]] = []

    async def fake_generate_tts(_seg, output_path, *, voice, engine, **_kw):
        seen.append((engine, voice))
        sf.write(str(output_path), np.full(2400, 0.1, dtype=np.float32), 24000, subtype="PCM_16")
        return 0.1, engine

    monkeypatch.setattr("agent.skills.audio.tts.generate_tts", fake_generate_tts)
    out = asyncio.run(tools.cmd_tts(_args(), tmp_path))
    assert seen == [("elevenlabs", "el-voice")] and "azure" in out["fallback_errors"]


def test_explicit_engine_keeps_the_configured_fallback_voice(tmp_path: Path) -> None:
    (tmp_path / "brief.json").write_text(json.dumps({
        "tts_engine": "azure", "voice": "a", "tts_fallback_engine": "elevenlabs", "tts_fallback_voice": "el-voice",
    }), encoding="utf-8")
    assert tools._tts_engine_chain(tmp_path, "elevenlabs")[1]["elevenlabs"] == "el-voice"


def test_identical_clamped_speed_is_not_rebilled(tmp_path: Path, monkeypatch) -> None:
    _run(tmp_path, monkeypatch, "Un.", set(), rate="+25%")
    _out, calls = _run(tmp_path, monkeypatch, "Un.", set(), rate="+30%")
    assert calls == []


def test_trial_to_another_file_keeps_the_status_of_the_real_voice(tmp_path: Path, monkeypatch) -> None:
    _run(tmp_path, monkeypatch, "Un.", {"elevenlabs"})
    _run(tmp_path, monkeypatch, "Un.", set(), out="essai.wav")
    assert json.loads((tmp_path / "tts_status.json").read_text(encoding="utf-8"))["engine"] == "gemini"


def test_status_file_overrides_agent_voice_json(tmp_path: Path) -> None:
    from studio.artifacts import list_artifacts

    (tmp_path / "voice.wav").write_bytes(b"x")
    (tmp_path / "voice.json").write_text(json.dumps({"engine": "elevenlabs", "voice": "v"}), encoding="utf-8")
    (tmp_path / "tts_status.json").write_text(json.dumps({
        "engine": "gemini", "voice": "Charon", "fallback_errors": {"elevenlabs": "402"},
    }), encoding="utf-8")
    voice = list_artifacts(tmp_path)["voice"]
    assert voice["engine"] == "gemini" and voice["fallback_errors"] == {"elevenlabs": "402"}


def test_elevenlabs_without_voice_keeps_it_empty_so_the_fallback_runs() -> None:
    from agent.core.channel_config import _parse_tts_format_profile

    profile = _parse_tts_format_profile({"engine": "elevenlabs"}, fallback_engine="azure", fallback_voice="fr-FR-X")
    assert profile.voice == ""
