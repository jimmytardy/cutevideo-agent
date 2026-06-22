"""Tests SSML builder and voice optional logic."""

from agent.agents.narrator_agent import segment_needs_voice
from agent.skills.audio.ssml_builder import build_azure_ssml, is_dragon_hd_voice


def test_segment_needs_voice_false_when_explicit() -> None:
    assert segment_needs_voice({"needs_voice": False, "narration_text": "hello"}) is False


def test_segment_needs_voice_false_when_empty_text() -> None:
    assert segment_needs_voice({"needs_voice": True, "narration_text": ""}) is False


def test_segment_needs_voice_true_by_default_with_text() -> None:
    assert segment_needs_voice({"narration_text": "Bonjour"}) is True


def test_build_azure_ssml_maps_editorial_tone_channel_wide() -> None:
    ssml = build_azure_ssml(
        "Test narration",
        "fr-FR-HenriNeural",
        editorial_tone="humoristique",
    )
    assert "fr-FR-HenriNeural" in ssml
    assert "cheerful" in ssml
    assert "Test narration" in ssml


def test_build_azure_ssml_respects_per_segment_delivery_style() -> None:
    ssml = build_azure_ssml(
        "Test narration",
        "fr-FR-HenriNeural",
        delivery_style={
            "azure_style": "cheerful",
            "pace": "fast",
            "pitch": "+5Hz",
            "emphasis_words": [],
        },
        default_style="narration-professional",
        default_rate="+0%",
        default_pitch="+0Hz",
    )
    assert "cheerful" in ssml
    assert "+12%" in ssml
    assert "+5Hz" in ssml


def test_build_azure_ssml_mood_overrides_defaults() -> None:
    ssml = build_azure_ssml(
        "Segment dramatique",
        "fr-FR-HenriNeural",
        mood="dramatique",
    )
    assert "sad" in ssml


def test_build_azure_ssml_inserts_pauses() -> None:
    ssml = build_azure_ssml(
        "Première phrase. Deuxième phrase?",
        "fr-FR-HenriNeural",
        insert_pauses=True,
    )
    assert "<break time='300ms'/>" in ssml


def test_build_azure_ssml_channel_tts_settings_override_editorial_tone() -> None:
    ssml = build_azure_ssml(
        "Test narration",
        "fr-FR-HenriNeural",
        editorial_tone="humoristique",
        default_style="newscast-formal",
    )
    assert "newscast-formal" in ssml
    assert "cheerful" not in ssml


def test_is_dragon_hd_voice() -> None:
    assert is_dragon_hd_voice("fr-FR-Vivienne:DragonHDLatestNeural") is True
    assert is_dragon_hd_voice("fr-FR-HenriNeural") is False


def test_build_azure_ssml_dragon_hd_without_express_as() -> None:
    ssml = build_azure_ssml(
        "Test narration documentaire.",
        "fr-FR-Vivienne:DragonHDLatestNeural",
        mood="dramatique",
        default_style="narration-relaxed",
    )
    assert "fr-FR-Vivienne:DragonHDLatestNeural" in ssml
    assert "mstts:express-as" not in ssml
    assert "<prosody" in ssml
    assert "Test narration documentaire." in ssml


def test_build_azure_ssml_dragon_hd_inserts_pauses() -> None:
    ssml = build_azure_ssml(
        "Première phrase. Deuxième phrase?",
        "fr-FR-Vivienne:DragonHDLatestNeural",
        insert_pauses=True,
    )
    assert "<break time='300ms'/>" in ssml
    assert "mstts:express-as" not in ssml


def test_build_azure_ssml_comma_pauses_opt_in() -> None:
    base = build_azure_ssml(
        "Un, deux, trois.",
        "fr-FR-HenriNeural",
        insert_pauses=True,
        comma_pauses=False,
    )
    assert "150ms" not in base

    with_commas = build_azure_ssml(
        "Un, deux, trois.",
        "fr-FR-HenriNeural",
        insert_pauses=True,
        comma_pauses=True,
    )
    assert "<break time='150ms'/>" in with_commas


def test_build_azure_ssml_clamps_excessive_rate() -> None:
    ssml = build_azure_ssml(
        "Test",
        "fr-FR-HenriNeural",
        delivery_style={"azure_style": "excited"},
        default_rate="+40%",
    )
    assert "+40%" not in ssml
    assert 'rate="+15%"' in ssml


def test_build_azure_ssml_clamps_excessive_pitch() -> None:
    ssml = build_azure_ssml(
        "Test",
        "fr-FR-HenriNeural",
        delivery_style={"pitch": "+20Hz"},
    )
    assert "+20Hz" not in ssml
    assert 'pitch="+8Hz"' in ssml


def test_build_azure_ssml_aliases_documentary_style() -> None:
    # "documentary" n'est pas un style Azure valide ; doit mapper sur la narration
    # documentaire plutôt que retomber silencieusement sur le défaut.
    ssml = build_azure_ssml(
        "Test",
        "fr-FR-HenriNeural",
        delivery_style={"azure_style": "documentary"},
    )
    assert "documentary-narration" in ssml


def test_build_azure_ssml_accepts_underscore_style() -> None:
    ssml = build_azure_ssml(
        "Test",
        "fr-FR-HenriNeural",
        delivery_style={"azure_style": "newscast_formal"},
    )
    assert "newscast-formal" in ssml


def test_build_azure_ssml_normalizes_medium_pace() -> None:
    # "medium" / "medium_varied" étaient ignorés (rate jamais ajusté) → normal.
    for pace in ("medium", "medium_varied"):
        ssml = build_azure_ssml(
            "Test",
            "fr-FR-HenriNeural",
            delivery_style={"pace": pace},
        )
        assert 'rate="+0%"' in ssml
