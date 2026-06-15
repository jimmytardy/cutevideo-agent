from __future__ import annotations

from agent.skills.media_sources.ai.prompt_builder import (
    VISUAL_TYPE_REGISTRY,
    build_visual_prompt,
    build_documentary_prompt,
    description_for_type,
)


def test_all_registry_types_produce_prompts() -> None:
    for vtype in VISUAL_TYPE_REGISTRY:
        prompt = build_visual_prompt(vtype, "test subject", style_hint="hand drawn")
        assert "test subject" in prompt
        assert len(prompt) > 20


def test_all_types_have_description_fr() -> None:
    for vtype in VISUAL_TYPE_REGISTRY:
        assert description_for_type(vtype).strip(), f"{vtype} missing description"


def test_documentary_prompt_backward_compat() -> None:
    prompt = build_documentary_prompt("bird on branch", theme_category="nature")
    assert "bird on branch" in prompt
    assert "No text" in prompt or "no text" in prompt.lower()


def test_custom_uses_style_hint() -> None:
    prompt = build_visual_prompt(
        "custom",
        "political satire scene",
        style_hint="1970s newspaper cartoon style",
    )
    assert "1970s newspaper cartoon" in prompt
