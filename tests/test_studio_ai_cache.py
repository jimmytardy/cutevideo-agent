"""Cache d'images IA de `studio.tools ai-image` et plafond de générations facturées.

Chaque image coûte de l'argent réel au propriétaire de la chaîne : le fournisseur est **toujours** simulé
(`generate_image` remplacé), jamais appelé. Ne jamais se reposer sur l'absence de clé pour s'en protéger —
rien dans le dépôt ne bloque le réseau pendant les tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from studio import media
from agent.skills.media_sources.ai.base import ImageBilledButLost
from studio.contracts import AI_USAGE_FILE, ContractError


def _setup(tmp_path: Path, monkeypatch, *, cap: int = 4) -> list[str]:
    """Run dir minimal, chaîne autorisée et plafond ; rend la liste à remplir des prompts facturés."""
    (tmp_path / "media").mkdir()
    monkeypatch.setenv("STUDIO_AI_MODELS", "flux_pro,flux_2_dev")
    monkeypatch.setenv("STUDIO_FAL_KEY", "fal-key")
    monkeypatch.setenv("STUDIO_MAX_AI_IMAGES", str(cap))
    return []


def _provider(billed: list[str], *, corrupt: bool = False) -> AsyncMock:
    def generate(prompt: str, out_dir: Path, **kwargs: object) -> dict[str, str]:
        billed.append(prompt)
        out_dir.mkdir(parents=True, exist_ok=True)
        src = out_dir / f"gen{len(billed)}.jpg"
        if corrupt:
            src.write_bytes(b"<html>not an image</html>")
        else:
            # Une teinte par génération : deux images distinctes ne peuvent pas être confondues.
            Image.new("RGB", (4, 4), (len(billed) * 40 % 256, 0, 0)).save(src)
        return {"local_generated": str(src), "attribution": "a", "provider_plan": str(kwargs["plan"])}

    return AsyncMock(side_effect=generate)


async def _ai_image(tmp_path: Path, fake: AsyncMock, prompt: str, name: str, **kwargs: object) -> dict:
    with patch("agent.skills.media_sources.ai_image.generate_image", new=fake), \
            patch.object(media, "probe_media", new=AsyncMock(return_value={})):
        return await media.generate_ai_image(tmp_path, prompt, name, **kwargs)  # type: ignore[arg-type]


def _billed_count(tmp_path: Path) -> int:
    return json.loads((tmp_path / AI_USAGE_FILE).read_text())["billed"]


@pytest.mark.asyncio
async def test_identical_prompt_is_served_from_the_cache(tmp_path: Path, monkeypatch) -> None:
    """Relancer un plan à l'identique entre deux itérations ne doit rien coûter."""
    billed = _setup(tmp_path, monkeypatch)
    fake = _provider(billed)

    first = await _ai_image(tmp_path, fake, "un tardigrade dans l'espace", "01_gerard")
    second = await _ai_image(tmp_path, fake, "un tardigrade dans l'espace", "01_gerard")

    assert first["reused"] is False and second["reused"] is True
    assert billed == ["un tardigrade dans l'espace"]
    assert _billed_count(tmp_path) == 1
    assert (tmp_path / first["path"]).read_bytes() == (tmp_path / second["path"]).read_bytes()


@pytest.mark.asyncio
async def test_cache_key_separates_prompt_model_and_aspect(tmp_path: Path, monkeypatch) -> None:
    billed = _setup(tmp_path, monkeypatch)
    fake = _provider(billed)

    await _ai_image(tmp_path, fake, "p", "01_a")
    await _ai_image(tmp_path, fake, "p AUTRE", "02_b")
    await _ai_image(tmp_path, fake, "p", "03_c", model="flux_2_dev")
    await _ai_image(tmp_path, fake, "p", "04_d", aspect="16:9")

    assert len(billed) == 4 and _billed_count(tmp_path) == 4


@pytest.mark.asyncio
async def test_same_name_with_a_new_prompt_is_billed_and_counted(tmp_path: Path, monkeypatch) -> None:
    """Le trou refermé : les crédits s'écrasent par chemin, le compteur de générations non."""
    billed = _setup(tmp_path, monkeypatch)
    fake = _provider(billed)

    await _ai_image(tmp_path, fake, "première version", "01_gerard")
    await _ai_image(tmp_path, fake, "seconde version", "01_gerard")

    credits = json.loads((tmp_path / "media" / "credits.json").read_text())
    assert list(credits) == ["media/01_gerard.jpg"]  # l'entrée a bien été écrasée
    assert len(billed) == 2 and _billed_count(tmp_path) == 2


@pytest.mark.asyncio
async def test_cap_bounds_billed_generations_but_never_the_cache(tmp_path: Path, monkeypatch) -> None:
    """Le plafond est une borne de dépense : au plafond, un prompt déjà payé passe encore."""
    billed = _setup(tmp_path, monkeypatch, cap=2)
    fake = _provider(billed)

    await _ai_image(tmp_path, fake, "p1", "01_a")
    await _ai_image(tmp_path, fake, "p2", "02_b")
    with pytest.raises(RuntimeError, match="plafond d'images IA atteint"):
        await _ai_image(tmp_path, fake, "p3", "03_c")

    reprise = await _ai_image(tmp_path, fake, "p1", "04_d")
    assert reprise["reused"] is True
    assert len(billed) == 2 and _billed_count(tmp_path) == 2


@pytest.mark.asyncio
async def test_corrupt_output_is_counted_and_never_cached(tmp_path: Path, monkeypatch) -> None:
    """Une image illisible a été facturée : elle consomme le plafond et ne doit pas polluer le cache."""
    billed = _setup(tmp_path, monkeypatch)
    fake = _provider(billed, corrupt=True)

    with pytest.raises(ContractError, match="image corrompue"):
        await _ai_image(tmp_path, fake, "p", "01_a")

    assert _billed_count(tmp_path) == 1
    good = _provider(billed)
    assert (await _ai_image(tmp_path, good, "p", "01_a"))["reused"] is False


@pytest.mark.asyncio
async def test_a_damaged_cache_entry_falls_back_to_a_new_generation(tmp_path: Path, monkeypatch) -> None:
    """Un cache abîmé coûte une génération, jamais une création ratée."""
    billed = _setup(tmp_path, monkeypatch)
    fake = _provider(billed)
    await _ai_image(tmp_path, fake, "p", "01_a")

    cached = next((tmp_path / "media" / ".ai" / ".cache").glob("*.jpg"))
    cached.write_bytes(b"tronque")
    assert (await _ai_image(tmp_path, fake, "p", "01_a"))["reused"] is False

    meta = next((tmp_path / "media" / ".ai" / ".cache").glob("*.json"))
    meta.write_text("{ pas du json")
    assert (await _ai_image(tmp_path, fake, "p", "01_a"))["reused"] is False
    assert len(billed) == 3


@pytest.mark.asyncio
async def test_a_refused_request_is_not_counted(tmp_path: Path, monkeypatch) -> None:
    """Clé invalide ou prompt bloqué : la requête n'a pas atteint le modèle, rien n'est dû."""
    _setup(tmp_path, monkeypatch)
    fake = AsyncMock(return_value=None)

    with pytest.raises(RuntimeError, match="clé refusée ou prompt bloqué"):
        await _ai_image(tmp_path, fake, "p", "01_a")

    # La réservation prise avant l'appel a bien été rendue.
    assert _billed_count(tmp_path) == 0


@pytest.mark.asyncio
async def test_an_image_billed_but_lost_is_counted(tmp_path: Path, monkeypatch) -> None:
    """fal a accepté la requête puis le téléchargement a échoué : c'est payé, donc c'est compté.

    Sans ce comptage, un CDN capricieux ferait boucler le rôle en facturant chaque tentative pendant
    que le plafond resterait immobile — exactement la fuite que ce compteur existe pour fermer.
    """
    _setup(tmp_path, monkeypatch)
    fake = AsyncMock(side_effect=ImageBilledButLost("flux_pro : téléchargement en 404"))

    with pytest.raises(RuntimeError, match="facturée mais image non récupérée"):
        await _ai_image(tmp_path, fake, "p", "01_a")

    assert _billed_count(tmp_path) == 1


@pytest.mark.asyncio
async def test_a_zero_cap_never_reaches_the_provider(tmp_path: Path, monkeypatch) -> None:
    billed = _setup(tmp_path, monkeypatch, cap=0)
    fake = _provider(billed)

    with pytest.raises(RuntimeError, match="plafond d'images IA atteint"):
        await _ai_image(tmp_path, fake, "p", "01_a")

    assert billed == [] and fake.await_count == 0


@pytest.mark.asyncio
async def test_a_meta_without_its_credit_is_treated_as_absent(tmp_path: Path, monkeypatch) -> None:
    """Méta d'un format antérieur ou écrite à la main : on régénère, on ne plante pas.

    Le rôle a `Write` et `Edit` sans restriction dans le run dir, donc une méta inattendue n'est pas
    qu'une hypothèse de corruption.
    """
    billed = _setup(tmp_path, monkeypatch)
    fake = _provider(billed)
    await _ai_image(tmp_path, fake, "p", "01_a")

    meta = next((tmp_path / "media" / ".ai" / ".cache").glob("*.json"))
    meta.write_text(json.dumps({"suffix": "jpg"}))  # ni `credit`, ni point devant le suffixe
    assert (await _ai_image(tmp_path, fake, "p", "01_a"))["reused"] is False
    assert len(billed) == 2


@pytest.mark.asyncio
async def test_a_reused_image_keeps_its_attribution(tmp_path: Path, monkeypatch) -> None:
    """Le crédit vient du cache, pas du fournisseur : il doit rester exact pour l'attribution publiée."""
    billed = _setup(tmp_path, monkeypatch)
    fake = _provider(billed)
    await _ai_image(tmp_path, fake, "p", "01_a")
    await _ai_image(tmp_path, fake, "p", "02_b")

    credits = json.loads((tmp_path / "media" / "credits.json").read_text())
    assert credits["media/02_b.jpg"] == credits["media/01_a.jpg"]
    assert credits["media/02_b.jpg"]["author"] == "flux_pro"
    assert credits["media/02_b.jpg"]["source"] == "ai_image"


@pytest.mark.asyncio
async def test_repeated_losses_eventually_hit_the_cap(tmp_path: Path, monkeypatch) -> None:
    """L'effet recherché : une panne de CDN s'arrête au plafond au lieu de facturer en boucle."""
    _setup(tmp_path, monkeypatch, cap=2)
    fake = AsyncMock(side_effect=ImageBilledButLost("flux_pro : téléchargement en 404"))

    for _ in range(2):
        with pytest.raises(RuntimeError, match="facturée mais image non récupérée"):
            await _ai_image(tmp_path, fake, "p", "01_a")
    with pytest.raises(RuntimeError, match="plafond d'images IA atteint"):
        await _ai_image(tmp_path, fake, "p", "01_a")

    assert fake.await_count == 2 and _billed_count(tmp_path) == 2


@pytest.mark.asyncio
async def test_an_unreadable_registry_refuses_to_spend(tmp_path: Path, monkeypatch) -> None:
    """Fail-closed : un registre abîmé ne doit pas rouvrir le budget en repartant de zéro."""
    billed = _setup(tmp_path, monkeypatch)
    fake = _provider(billed)
    await _ai_image(tmp_path, fake, "p", "01_a")

    (tmp_path / AI_USAGE_FILE).write_text('{"billed": "beaucoup"}')
    with pytest.raises(RuntimeError, match="registre de dépense des images IA illisible"):
        await _ai_image(tmp_path, fake, "autre prompt", "02_b")

    assert len(billed) == 1


@pytest.mark.asyncio
async def test_an_unclassified_failure_gives_the_reservation_back(tmp_path: Path, monkeypatch) -> None:
    """Panne que le fournisseur n'a pas su classer : elle n'a rien coûté, elle ne doit rien consommer.

    Cas réel : le rafraîchissement du jeton GCP échoue avant tout appel payant. Sans remboursement,
    quatre pannes de ce genre épuiseraient le plafond sans un centime dépensé.
    """
    _setup(tmp_path, monkeypatch)
    fake = AsyncMock(side_effect=ConnectionResetError("jeton GCP irrécupérable"))

    with pytest.raises(ConnectionResetError):
        await _ai_image(tmp_path, fake, "p", "01_a")

    assert _billed_count(tmp_path) == 0
