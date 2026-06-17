from __future__ import annotations

from pathlib import Path

from agent.skills.audio.sound_design import (
    SfxCue,
    build_sfx_cues,
    build_sfx_ffmpeg_command,
)


def _meta(order, duration, *, hook=None, voice=True):
    return {
        "duration_s": duration,
        "needs_voice": voice,
        "needs_music": True,
        "mood": "calme",
        "strip_source_audio": True,
        "hook_type": hook,
    }


def test_no_cues_for_empty_or_single_segment() -> None:
    assert build_sfx_cues({}) == []
    cues = build_sfx_cues({1: _meta(1, 30)})
    # Un seul segment, pas de hook révélateur → aucun whoosh, aucun accent.
    assert cues == []


def test_whoosh_on_each_transition() -> None:
    meta = {1: _meta(1, 30), 2: _meta(2, 20), 3: _meta(3, 40)}
    cues = build_sfx_cues(meta)
    whooshes = [c for c in cues if c.kind == "whoosh"]
    # Deux transitions (avant seg 2 et seg 3).
    assert len(whooshes) == 2
    times = sorted(c.time_s for c in whooshes)
    assert abs(times[0] - (30 - 0.15)) < 1e-6
    assert abs(times[1] - (50 - 0.15)) < 1e-6


def test_accent_on_reveal_hook() -> None:
    meta = {
        1: _meta(1, 30, hook="question"),
        2: _meta(2, 20, hook="fait_surprenant"),
    }
    cues = build_sfx_cues(meta)
    accents = [c for c in cues if c.kind == "accent"]
    assert len(accents) == 1
    assert abs(accents[0].time_s - (30 + 0.05)) < 1e-6


def test_voiceless_uses_louder_gain() -> None:
    voiced = build_sfx_cues({1: _meta(1, 10), 2: _meta(2, 10)})
    silent = build_sfx_cues({1: _meta(1, 10, voice=False), 2: _meta(2, 10, voice=False)})
    assert silent[0].gain_db > voiced[0].gain_db  # moins négatif = plus fort


def test_cues_capped() -> None:
    meta = {i: _meta(i, 5) for i in range(1, 40)}
    cues = build_sfx_cues(meta, max_cues=10)
    assert len(cues) == 10


def test_ffmpeg_command_structure() -> None:
    cues = [SfxCue(time_s=5.0, kind="whoosh", gain_db=-22.0), SfxCue(time_s=10.0, kind="accent", gain_db=-20.0)]
    cmd = build_sfx_ffmpeg_command(Path("/tmp/in.mp4"), cues, Path("/tmp/out.mp4"))
    assert cmd[0] == "ffmpeg"
    # une entrée vidéo + une entrée lavfi par cue
    assert cmd.count("-i") == 1 + len(cues)
    assert cmd.count("lavfi") == len(cues)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "amix=inputs=3" in fc  # vidéo + 2 SFX
    assert "adelay=5000|5000" in fc
    assert "adelay=10000|10000" in fc
    assert "-c:v" in cmd and "copy" in cmd
