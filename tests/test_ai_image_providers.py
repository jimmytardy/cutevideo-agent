"""Tests providers images IA Flux + Imagen 3 et choix du modèle par `ai-image`."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from PIL import Image

from agent.skills.media_sources.ai.base import (
    ImageBilledButLost,
    ImageGenerationRequest,
    ImageGenerationResult,
)
from agent.skills.media_sources.ai.flux_common import _flux_model_for_plan
from agent.skills.media_sources.ai.registry import generate_with_plan, models_up_to, provider_family
from studio.contracts import AI_USAGE_FILE


def _post_session(
    mock_session_cls: MagicMock, *, status: int = 200, json_value=None, json_error=None
) -> MagicMock:
    """Session dont seul le POST de génération est configuré — fal et Vertex ne diffèrent que par le
    corps rendu, et aucun des deux n'atteint de second appel quand ce POST échoue."""
    mock_session = AsyncMock()
    mock_session_cls.return_value.__aenter__.return_value = mock_session
    post_resp = AsyncMock()
    post_resp.status = status
    post_resp.text = AsyncMock(return_value="refusé")
    post_resp.json = AsyncMock(return_value=json_value, side_effect=json_error)
    post_resp.__aenter__.return_value = post_resp
    mock_session.post = MagicMock(return_value=post_resp)
    return mock_session


def _mock_fal(mock_session_cls: MagicMock, image_url: str) -> MagicMock:
    """Parcours complet de fal : POST de génération, puis GET de l'image produite."""
    mock_session = _post_session(mock_session_cls, json_value={"images": [{"url": image_url}]})
    get_resp = AsyncMock()
    get_resp.status = 200
    get_resp.read = AsyncMock(return_value=b"fake-jpeg")
    get_resp.__aenter__.return_value = get_resp
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
    # Génération facturée malgré tout : comptée dans le registre de dépense, et créditée sous un chemin
    # qui n'entrera jamais dans une timeline, donc jamais dans l'attribution publiée.
    assert json.loads((tmp_path / AI_USAGE_FILE).read_text())["billed"] == 1
    credits = json.loads((tmp_path / "media" / "credits.json").read_text())
    assert list(credits) == ["gen.jpg"] and credits["gen.jpg"]["unusable"] is True


# ── frontière de facturation ────────────────────────────────────────────────────
# Le code 200 (`fal.run` comme Vertex) est le moment où l'image est produite, donc payée. En deçà, un
# échec ne doit rien coûter (`None`) ; au-delà, il doit être compté (`ImageBilledButLost`), sans quoi un
# rôle qui réessaie derrière une panne réseau facture le propriétaire de la chaîne à chaque tentative
# sans jamais approcher le plafond.

def _flux_request(tmp_path: Path) -> ImageGenerationRequest:
    return ImageGenerationRequest(prompt="p", output_dir=tmp_path, fal_api_key="fal-key")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "label"),
    [
        ({"json_value": {"images": []}}, "réponse sans image"),
        ({"json_error": ValueError("corps illisible")}, "réponse illisible"),
        ({"json_error": TimeoutError()}, "réponse illisible"),
    ],
)
async def test_flux_counts_a_failure_after_the_billing_boundary(tmp_path: Path, kwargs, label) -> None:
    with patch("aiohttp.ClientSession") as session_cls:
        _post_session(session_cls, **kwargs)
        with pytest.raises(ImageBilledButLost, match=label):
            await generate_with_plan("flux_pro", _flux_request(tmp_path))


@pytest.mark.asyncio
async def test_flux_does_not_count_a_connection_timeout(tmp_path: Path) -> None:
    """Délai écoulé avant la connexion : la requête n'est jamais partie, rien n'est dû."""
    with patch("aiohttp.ClientSession") as session_cls:
        session = _post_session(session_cls)
        session.post.return_value.__aenter__.side_effect = aiohttp.ConnectionTimeoutError("connexion")
        assert await generate_with_plan("flux_pro", _flux_request(tmp_path)) is None


async def _imagen(tmp_path: Path, **kwargs):
    gcp = SimpleNamespace(project_id="p", location="europe-west1", credentials_json="{}")
    request = ImageGenerationRequest(prompt="p", output_dir=tmp_path, gcp_credentials=gcp)
    with patch("aiohttp.ClientSession") as session_cls, \
            patch("agent.skills.media_sources.ai.imagen3._get_gcp_access_token",
                  new=AsyncMock(return_value=("tok", "proj", "europe-west1"))):
        _post_session(session_cls, **kwargs)
        return await generate_with_plan("imagen3", request)


@pytest.mark.asyncio
async def test_imagen_treats_a_filtered_prompt_as_free(tmp_path: Path) -> None:
    """Vertex signale une sortie écartée par ses filtres en ne rendant aucune prédiction : rien n'est dû."""
    assert await _imagen(tmp_path, json_value={"predictions": []}) is None
    assert await _imagen(tmp_path, status=400) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("payload", "reason"), [
    ({"predictions": [{}]}, "prédiction sans image"),
    ({"predictions": [{"bytesBase64Encoded": "A"}]}, "image perdue"),  # base64 au remplissage invalide
])
async def test_imagen_counts_a_lost_image(tmp_path: Path, payload, reason) -> None:
    # `match` distingue les deux causes : sans lui, un cas passerait pour la raison de l'autre.
    with pytest.raises(ImageBilledButLost, match=reason):
        await _imagen(tmp_path, json_value=payload)


@pytest.mark.asyncio
async def test_flux_counts_a_lost_download(tmp_path: Path) -> None:
    with patch("aiohttp.ClientSession") as session_cls:
        session = _mock_fal(session_cls, "https://cdn/img.jpg")
        session.get.return_value.status = 404
        with pytest.raises(ImageBilledButLost):
            await generate_with_plan("flux_pro", _flux_request(tmp_path))


@pytest.mark.asyncio
async def test_flux_does_not_count_a_refusal(tmp_path: Path) -> None:
    """Statut non 200 : fal n'a rien produit, donc rien n'est dû."""
    with patch("aiohttp.ClientSession") as session_cls:
        _post_session(session_cls, status=422)
        assert await generate_with_plan("flux_pro", _flux_request(tmp_path)) is None

    with patch("aiohttp.ClientSession") as session_cls:
        session = _post_session(session_cls)
        session.post.return_value.__aenter__.side_effect = aiohttp.ClientConnectionError("injoignable")
        assert await generate_with_plan("flux_pro", _flux_request(tmp_path)) is None
        session.post.assert_called_once()
