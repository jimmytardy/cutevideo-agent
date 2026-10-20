"""Tests providers images IA Flux + Imagen 3 et choix du modèle par `ai-image`."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from agent.skills.media_sources.ai.base import ImageGenerationRequest, ImageGenerationResult
from agent.skills.media_sources.ai.flux_common import _flux_model_for_plan
from agent.skills.media_sources.ai.registry import generate_with_plan, models_up_to, provider_family


def _mock_fal(mock_session_cls: MagicMock, image_url: str) -> MagicMock:
    mock_session = AsyncMock()
    mock_session_cls.return_value.__aenter__.return_value = mock_session

    post_resp = AsyncMock()
    post_resp.status = 200
    post_resp.json = AsyncMock(return_value={"images": [{"url": image_url}]})
    post_resp.__aenter__.return_value = post_resp

    get_resp = AsyncMock()
    get_resp.status = 200
    get_resp.read = AsyncMock(return_value=b"fake-jpeg")
    get_resp.__aenter__.return_value = get_resp

    mock_session.post = MagicMock(return_value=post_resp)
    mock_session.get = MagicMock(return_value=get_resp)
    return mock_session


# Charge utile attendue de chaque plan, **figée en dur** d'après les schémas publiés par fal : aucun
# endpoint n'accepte les mêmes champs, et fal ignore en silence ceux qu'il ne connaît pas. Dériver ces
# attentes du code rejouerait sa logique au lieu de la confronter aux schémas réels.
# À noter : l'ultra se dimensionne par `aspect_ratio` (défaut 16:9) et n'a pas d'`image_size` — lui envoyer
# un `image_size` renvoyait du paysage pour un Short vertical.
EXPECTED_PAYLOADS: dict[str, dict] = {
    "flux_pro": {  # fal-ai/flux-2-pro
        "output_format": "jpeg", "image_size": {"width": 1080, "height": 1920},
        "enable_safety_checker": True, "safety_tolerance": "2",
    },
    "flux_2_dev": {  # fal-ai/flux-2
        "output_format": "jpeg", "image_size": {"width": 1080, "height": 1920},
        "enable_safety_checker": True, "guidance_scale": 2.5,
    },
    "flux_ultra": {  # fal-ai/flux-pro/v1.1-ultra
        "output_format": "jpeg", "aspect_ratio": "9:16", "safety_tolerance": "2", "raw": True,
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("plan", ["flux_pro", "flux_2_dev", "flux_ultra"])
async def test_flux_success_sends_prompt_as_is(tmp_path: Path, plan: str) -> None:
    request = ImageGenerationRequest(
        prompt="a cat on a sofa", output_dir=tmp_path, fal_api_key="test-fal-key",
        aspect_ratio="9:16", image_width=1080, image_height=1920,
    )
    with patch("aiohttp.ClientSession") as mock_session_cls:
        session = _mock_fal(mock_session_cls, "https://fal.ai/fake.jpg")
        result = await generate_with_plan(plan, request)

    assert result is not None
    assert result.provider_plan == plan
    assert result.local_path.exists()
    payload = session.post.call_args.kwargs["json"]
    assert payload["prompt"] == "a cat on a sofa"
    assert ("raw" in payload) == (plan == "flux_ultra")

    # L'endpoint réellement appelé, et la charge utile complète : fal ignore les champs inconnus, donc une
    # charge utile fausse ne lèverait pas — seules ces assertions peuvent la détecter.
    assert session.post.call_args.args[0] == f"https://fal.run/{_flux_model_for_plan(plan)}"
    assert {k: v for k, v in payload.items() if k != "prompt"} == EXPECTED_PAYLOADS[plan]


@pytest.mark.asyncio
async def test_flux_without_key_returns_none(tmp_path: Path) -> None:
    request = ImageGenerationRequest(prompt="x", output_dir=tmp_path)
    assert await generate_with_plan("flux_pro", request) is None


@pytest.mark.asyncio
async def test_generate_image_uses_requested_plan(tmp_path: Path) -> None:
    from agent.skills.media_sources.ai_image import generate_image

    fake_result = ImageGenerationResult(
        local_path=tmp_path / "dev.jpg",
        attribution="FLUX 2 Dev",
        license="synthetic-ai-generated",
        title="test",
        provider_plan="flux_2_dev",
    )
    with patch(
        "agent.skills.media_sources.ai_image.generate_with_plan",
        new=AsyncMock(return_value=fake_result),
    ) as mock_gen:
        result = await generate_image("test", tmp_path, plan="flux_2_dev")

    assert result is not None
    assert result["provider_plan"] == "flux_2_dev"
    assert mock_gen.await_args.args[0] == "flux_2_dev"


def test_provider_family_mapping() -> None:
    assert provider_family("flux_pro") == "flux"
    assert provider_family("imagen3") == "google"


def test_models_up_to_keeps_cheaper_models_default_first() -> None:
    assert models_up_to("flux_pro") == ["flux_pro", "flux_schnell", "imagen3_fast", "flux_2_dev", "imagen3"]
    assert models_up_to("flux_schnell") == ["flux_schnell"]
    assert models_up_to("off") == []


def test_usable_ai_models_needs_owner_keys() -> None:
    from studio.contracts import Brief
    from studio.launcher import usable_ai_models

    brief = Brief(theme="t", ai_models=["flux_pro", "imagen3_fast", "flux_2_dev"])
    fal_only = SimpleNamespace(fal="k", gcp_credentials_json=None)
    assert usable_ai_models(brief, fal_only) == ["flux_pro", "flux_2_dev"]  # type: ignore[arg-type]
    assert usable_ai_models(brief.model_copy(update={"max_ai_images": 0}), fal_only) == []  # type: ignore[arg-type]
    assert usable_ai_models(Brief(theme="t"), fal_only) == ["flux_2_dev"]  # type: ignore[arg-type]
    assert usable_ai_models(brief, None) == []


@pytest.mark.asyncio
async def test_studio_ai_image_refuses_model_outside_channel_plan(tmp_path: Path, monkeypatch) -> None:
    from studio import media

    monkeypatch.setenv("STUDIO_AI_MODELS", "flux_2_dev,flux_schnell")
    with pytest.raises(RuntimeError, match="non autorisé"):
        await media.generate_ai_image(tmp_path, "x", "05_x", model="flux_ultra")

    monkeypatch.setenv("STUDIO_AI_MODELS", "")
    with pytest.raises(RuntimeError, match="indisponibles"):
        await media.generate_ai_image(tmp_path, "x", "05_x")


@pytest.mark.asyncio
async def test_studio_ai_image_defaults_to_first_allowed_model(tmp_path: Path, monkeypatch) -> None:
    from studio import media

    (tmp_path / "media").mkdir()
    monkeypatch.setenv("STUDIO_AI_MODELS", "flux_pro,flux_2_dev")
    monkeypatch.setenv("STUDIO_FAL_KEY", "fal-key")
    src = tmp_path / "gen.jpg"
    Image.new("RGB", (4, 4), "red").save(src)
    fake = AsyncMock(return_value={"local_generated": str(src), "attribution": "a", "provider_plan": "flux_pro"})
    with patch("agent.skills.media_sources.ai_image.generate_image", new=fake), \
            patch.object(media, "probe_media", new=AsyncMock(return_value={})):
        out = await media.generate_ai_image(tmp_path, "x", "05_x")

    assert out["path"] == "media/05_x.jpg"
    assert fake.await_args.kwargs["plan"] == "flux_pro"
    assert fake.await_args.kwargs["fal_api_key"] == "fal-key"
    credits = json.loads((tmp_path / "media" / "credits.json").read_text())
    assert credits["media/05_x.jpg"]["author"] == "flux_pro"


@pytest.mark.asyncio
async def test_studio_ai_image_rejects_corrupt_output(tmp_path: Path, monkeypatch) -> None:
    from studio import media
    from studio.contracts import ContractError

    (tmp_path / "media").mkdir()
    monkeypatch.setenv("STUDIO_AI_MODELS", "flux_pro")
    monkeypatch.setenv("STUDIO_FAL_KEY", "fal-key")
    src = tmp_path / "gen.jpg"
    src.write_bytes(b"<html>not an image</html>")
    fake = AsyncMock(return_value={"local_generated": str(src), "attribution": "a", "provider_plan": "flux_pro"})
    with patch("agent.skills.media_sources.ai_image.generate_image", new=fake), \
            pytest.raises(ContractError, match="image corrompue"):
        await media.generate_ai_image(tmp_path, "x", "05_x")
    assert not (tmp_path / "media" / "05_x.jpg").exists()
    # Génération facturée malgré tout : comptée dans le quota, mais jamais sous un chemin utilisable.
    credits = json.loads((tmp_path / "media" / "credits.json").read_text())
    assert list(credits) == ["gen.jpg"] and credits["gen.jpg"]["unusable"] is True
