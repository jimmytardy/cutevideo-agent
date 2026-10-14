"""Briques ajoutées pendant l'optimisation des Shorts : sous-titres, pauses de voix, mixage, analyse, kit."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from agent.skills.audio.whisper_utils import WordSegment
from studio import analyze, audiomix, subtitles, voicefx
from studio.animate import TEMPLATES, TEMPLATES_DIR, WORKSPACE_LIB


def _words(text: str, step: float = 0.3, gap_after: dict[int, float] | None = None) -> list[WordSegment]:
    out, t = [], 0.0
    for i, w in enumerate(text.split()):
        out.append(WordSegment(word=w, start=round(t, 3), end=round(t + step - 0.05, 3)))
        t += step + (gap_after or {}).get(i, 0.0)
    return out


def test_subtitles_highlight_only_the_spoken_word() -> None:
    words = _words("La Lune s'éloigne de 3,8 centimètres chaque année.")
    ass = subtitles.build_ass(words, subtitles.SubtitleStyle(keywords=["Lune"]))
    events = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(events) == len(words)  # un événement par mot actif
    active = subtitles._ass_color("#FFD60A")
    for ev, w in zip(events, words):
        assert ev.count(active) == 1
        assert f"{active}\\fscx112\\fscy112}}{w.word}" in ev
    # Mot-clé et nombre en couleur d'accent quand ils ne sont pas actifs.
    keyword = subtitles._ass_color("#4ADE80")
    assert any(f"{keyword}}}Lune" in ev for ev in events)
    assert any(f"{keyword}}}3,8" in ev for ev in events)
    assert all("\\pos(540,1290)" in ev for ev in events)


def test_subtitle_lines_break_on_pauses_and_length() -> None:
    words = _words("Mais attendez le plus fou arrive maintenant", gap_after={1: 0.6})
    lines = subtitles.group_lines(words)
    assert [w.word for w in lines[0]] == ["Mais", "attendez"]
    assert all(len(line) <= subtitles.MAX_WORDS for line in lines)


def test_tighten_pauses_shortens_only_long_silences(tmp_path: Path) -> None:
    sr = 48000
    tone = 0.3 * np.sin(2 * np.pi * 220 * np.arange(int(sr * 0.5)) / sr)
    silence_long, silence_short = np.zeros(int(sr * 0.9)), np.zeros(int(sr * 0.2))
    audio = np.concatenate([tone, silence_long, tone, silence_short, tone])
    path = tmp_path / "voice.wav"
    sf.write(path, audio, sr, subtype="PCM_16")
    res = voicefx.tighten_pauses(path, max_pause_s=0.4)
    assert res["removed_s"] == pytest.approx(0.5, abs=0.05)
    assert sf.info(str(path)).duration == pytest.approx(len(audio) / sr - 0.5, abs=0.05)


@pytest.mark.parametrize("kind", audiomix.SFX_KINDS)
def test_synthetic_sfx_are_short_and_normalized(kind: str) -> None:
    sig = audiomix.synth_sfx(kind)
    assert 0.02 < len(sig) / audiomix.SR < 1.5
    assert np.abs(sig).max() == pytest.approx(1.0, abs=1e-3)


def test_sfx_track_places_events(tmp_path: Path) -> None:
    out = audiomix.build_sfx_track([(1.0, "pop"), (2.0, "riser")], 3.0, -3.0, tmp_path / "sfx.wav")
    data, sr = sf.read(str(out))
    assert len(data) == 3 * sr
    assert np.abs(data[: int(0.9 * sr)]).max() < 0.02          # rien avant le riser
    assert np.abs(data[int(1.0 * sr): int(1.1 * sr)]).max() > 0.02  # le pop


def test_analysis_flags_catch_slow_flat_voice() -> None:
    m = {
        "duration_s": 30.0, "loudness_lufs": -20.0,
        "visual": {"first_cut_s": 4.0, "longest_shot_s": 9.0, "longest_shot_at": 3.0, "static_spans": []},
        "speech": {"words": 60, "first_word_s": 0.0, "words_per_s": 2.1, "longest_pause_s": 1.2},
        "audio": {"speech_to_bed_db": 6.0, "pitch": {"std_semitones": 1.2}, "silences": []},
    }
    flags = " | ".join(analyze._flags(m))
    for needle in ("hook", "rythme", "débit lent", "pause", "loudness", "musique trop forte", "intonation plate"):
        assert needle in flags


def test_templates_exist_and_use_the_kit() -> None:
    for name in TEMPLATES:
        html = (TEMPLATES_DIR / f"{name}.html").read_text(encoding="utf-8")
        assert "/*PARAMS*/{}" in html
        for src in re.findall(r'src="(lib/[^"]+)"', html):
            assert (WORKSPACE_LIB.parent / src).exists(), src


def test_kit_icons_cited_in_workspace_exist() -> None:
    claude_md = (WORKSPACE_LIB.parent.parent / "CLAUDE.md").read_text(encoding="utf-8")
    block = claude_md.split("**Icônes**")[1].split("Polices")[0]
    names = re.findall(r"\b([a-z_]+)(?=,|…)", block.split(":", 1)[1])
    assert len(names) > 30
    for name in names:
        assert (WORKSPACE_LIB / "icons" / f"{name}.svg").exists(), name


def test_emphasis_tags_are_parsed_per_line() -> None:
    text = "Le plus fou ?\n[rate=-4% pitch=+12Hz] Nous !\n\n[bidon] La Terre freine."
    lines = voicefx.parse_emphasis(text)
    assert lines == [("Le plus fou ?", {}), ("Nous !", {"rate": "-4%", "pitch": "+12Hz"}), ("La Terre freine.", {})]
    assert voicefx.has_emphasis(text)
    assert not voicefx.has_emphasis("Phrase simple.\nAutre phrase.")


def test_concat_wavs_inserts_short_gaps(tmp_path: Path) -> None:
    sr = 48000
    parts = []
    for i in range(3):
        p = tmp_path / f"p{i}.wav"
        sf.write(p, 0.2 * np.ones(sr // 2), sr, subtype="PCM_16")
        parts.append(p)
    dur = voicefx.concat_wavs(parts, tmp_path / "out.wav", gap_s=0.1)
    assert dur == pytest.approx(1.5 + 0.2, abs=0.01)


def test_punctuation_tokens_are_not_shown_alone() -> None:
    words = [WordSegment("Sauf", 0.0, 0.3), WordSegment("que", 0.3, 0.5), WordSegment(":", 0.5, 0.55),
             WordSegment("23", 0.6, 0.9)]
    lines = subtitles.group_lines(words)
    flat = [w.word for line in lines for w in line]
    assert ":" not in flat and "que:" in flat


def test_french_typography_and_keywords_with_punctuation() -> None:
    words = [WordSegment("Pourquoi", 0.0, 0.3), WordSegment("Lune?", 0.3, 0.6)]
    ass = subtitles.build_ass(words, subtitles.SubtitleStyle(keywords=["Lune"]))
    first = [line for line in ass.splitlines() if line.startswith("Dialogue:")][0]
    assert "Lune\\h?" in first
    assert subtitles._ass_color("#4ADE80") in first  # mot-clé reconnu malgré la ponctuation


def test_pauses_are_measured_acoustically() -> None:
    times = np.arange(0, 3, 0.02)
    db = np.full(len(times), -15.0)
    db[(times >= 1.0) & (times < 1.3)] = -60.0  # vrai silence de 0,3 s dans un écart Whisper de 0,9 s
    speech = {"pauses": [{"at": 0.9, "s": 0.9, "after": "x"}], "longest_pause_s": 0.9}
    analyze._refine_pauses(speech, {"db": db, "times": times}, -15.0)
    assert speech["longest_pause_s"] == pytest.approx(0.3, abs=0.03)
    assert speech["pauses"][0]["whisper_s"] == 0.9


def test_line_emphasis_is_relative_to_global_settings() -> None:
    assert voicefx.combine_offset("+30%", "-6%") == "+24%"
    assert voicefx.combine_offset("+0Hz", "+12Hz") == "+12Hz"
    assert voicefx.combine_offset("+6%", None) == "+6%"
    assert voicefx.combine_offset("+6%", "bidon") == "+6%"


def test_cues_are_relative_to_the_clip(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    (tmp_path / "words.json").write_text(json.dumps([
        {"word": "Avant", "start": 1.0, "end": 1.3}, {"word": "Cinquante", "start": 27.8, "end": 28.2},
        {"word": "pour", "start": 28.3, "end": 28.5}, {"word": "Après", "start": 31.0, "end": 31.4},
    ]), encoding="utf-8")
    out = subprocess.run([sys.executable, "-m", "studio.tools", "cues", "--start", "27.74", "--end", "30.5"],
                         capture_output=True, text=True, env={**__import__("os").environ, "STUDIO_RUN_DIR": str(tmp_path)},
                         cwd=Path(__file__).resolve().parent.parent)
    cues = json.loads(out.stdout)["cues"]
    assert [c["word"] for c in cues] == ["Cinquante", "pour"]
    assert cues[0]["at"] == pytest.approx(0.06, abs=0.001)
