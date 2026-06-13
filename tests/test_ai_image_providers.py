"""Tests providers images IA Flux + Imagen 3."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.channel_config import AiFallbackConfig, AiImagePlan
from agent.skills.media_sources.ai.base import ImageGenerationRequest, ImageGenerationResult
from agent.skills.media_sources.ai.registry import generate_with_plan, provider_family


@pytest.mark.asyncio
async def test_flux_pro_success(tmp_path: Path) -> None:
    request = ImageGenerationRequest(
        prompt="chat drôle sur un canapé",
        output_dir=tmp_path,
        theme_category="animaux",
        editorial_tone="humoristique",
    )
    fake_image = b"fake-jpeg"
    flux_response = {"images": [{"url": "https://fal.ai/fake.jpg"}]}

    with (
        patch("agent.skills.media_sources.ai.flux_common.settings") as mock_settings,
        patch("aiohttp.ClientSession") as mock_session_cls,
    ):
        mock_settings.fal_key = "test-fal-key"
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session

        post_resp = AsyncMock()
        post_resp.status = 200
        post_resp.json = AsyncMock(return_value=flux_response)
        post_resp.__aenter__.return_value = post_resp

        get_resp = AsyncMock()
        get_resp.status = 200
        get_resp.read = AsyncMock(return_value=fake_image)
        get_resp.__aenter__.return_value = get_resp

        mock_session.post = MagicMock(return_value=post_resp)
        mock_session.get = MagicMock(return_value=get_resp)

        result = await generate_with_plan("flux_pro", request)

    assert result is not None
    assert result.provider_plan == "flux_pro"
    assert result.local_path.exists()


@pytest.mark.asyncio
async def test_flux_fails_returns_none_with_empty_fallback() -> None:
    from agent.skills.media_sources.ai_image import generate_image

    ai_cfg = AiFallbackConfig(
        plan=AiImagePlan.FLUX_PRO,
        fallback_chain=[],
    )
    with patch(
        "agent.skills.media_sources.ai_image.generate_with_plan",
        new=AsyncMock(return_value=None),
    ) as mock_gen:
        result = await generate_image(
            "test",
            Path("/tmp/test"),
            ai_cfg=ai_cfg,
        )
    assert result is None
    assert mock_gen.await_count == 1


@pytest.mark.asyncio
async def test_fallback_chain_tries_second_provider(tmp_path: Path) -> None:
    from agent.skills.media_sources.ai_image import generate_image

    ai_cfg = AiFallbackConfig(
        plan=AiImagePlan.FLUX_PRO,
        fallback_chain=["imagen3"],
    )
    fake_result = ImageGenerationResult(
        local_path=tmp_path / "ai_test.jpg",
        attribution="Imagen 3",
        license="synthetic-ai-generated",
        title="test",
        provider_plan="imagen3",
    )
    fake_result.local_path.write_bytes(b"x")

    with patch(
        "agent.skills.media_sources.ai_image.generate_with_plan",
        new=AsyncMock(side_effect=[None, fake_result]),
    ) as mock_gen:
        result = await generate_image(
            "test prompt",
            tmp_path,
            ai_cfg=ai_cfg,
        )

    assert result is not None
    assert result["provider_plan"] == "imagen3"
    assert mock_gen.await_count == 2


def test_provider_family_mapping() -> None:
    assert provider_family("flux_pro") == "flux"
    assert provider_family("imagen3") == "google"


def test_resolved_provider_chain() -> None:
    cfg = AiFallbackConfig(plan=AiImagePlan.FLUX_PRO, fallback_chain=["imagen3", "flux_pro"])
    assert cfg.resolved_provider_chain() == ["flux_pro", "imagen3"]
