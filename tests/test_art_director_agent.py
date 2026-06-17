from __future__ import annotations

from agent.agents.art_director_agent import fallback_style_block
from agent.skills.media_sources.ai.prompt_builder import build_visual_prompt


def test_fallback_style_block_by_category() -> None:
    assert "scientific" in fallback_style_block("science").lower()
    assert "noir" in fallback_style_block("true_crime").lower()
    # catégorie inconnue → style par défaut cohérent
    assert "cohesive" in fallback_style_block("inconnu").lower()


def test_style_block_injected_into_visual_prompt() -> None:
    style = "cohesive noir look, desaturated cold palette, low-key lighting"
    prompt = build_visual_prompt(
        "documentary_photo",
        "a detective examining a case file",
        theme_category="true_crime",
        style_block=style,
    )
    assert style in prompt
    # le sujet mène le prompt (bonne pratique FLUX)
    assert prompt.lower().startswith("a detective examining a case file")


def test_style_block_absent_when_empty() -> None:
    prompt = build_visual_prompt("documentary_photo", "a red fox", theme_category="nature")
    assert "cohesive" not in prompt.lower()
