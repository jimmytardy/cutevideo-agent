"""Médias du run dir : une image doit se décoder entièrement avant d'entrer dans `media/` (studio/media.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from studio import media
from studio.contracts import ContractError, read_json, write_json


def _png(path: Path) -> bytes:
    Image.new("RGB", (8, 8), "blue").save(path)
    return path.read_bytes()


def test_verify_image_accepts_valid_and_rejects_unreadable(tmp_path: Path) -> None:
    good = tmp_path / "ok.png"
    data = _png(good)
    media.verify_image(good)  # ne lève pas

    truncated = tmp_path / "cut.png"
    truncated.write_bytes(data[: len(data) // 2])
    with pytest.raises(ContractError, match="image corrompue"):
        media.verify_image(truncated)

    html = tmp_path / "page.jpg"  # un 200 HTML renvoyé sous un nom d'image
    html.write_bytes(b"<html><body>Not found</body></html>")
    with pytest.raises(ContractError, match="page.jpg"):
        media.verify_image(html)


@pytest.mark.asyncio
async def test_download_candidate_rejects_corrupt_image_and_evicts_cache(tmp_path: Path, monkeypatch) -> None:
    write_json(tmp_path / "media" / "candidates.json", {
        "c1": {"url": "https://example.test/a.jpg", "asset_type": "image", "source": "pexels", "license": "pexels"},
    })
    payload = {"bytes": b"not an image"}

    async def fake_fetch(url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload["bytes"])

    monkeypatch.setattr(media, "_fetch", fake_fetch)
    with pytest.raises(ContractError, match="image corrompue"):
        await media.download_candidate(tmp_path, "c1", "01_a")
    assert not (tmp_path / "media" / ".cache" / "c1.jpg").exists()  # pas réutilisé à la tentative suivante
    assert not (tmp_path / "media" / "01_a.jpg").exists()
    assert not (tmp_path / "media" / "credits.json").exists()  # aucun crédit fantôme

    payload["bytes"] = _png(tmp_path / "real.png")
    out = await media.download_candidate(tmp_path, "c1", "01_a")
    assert out["kind"] == "image" and out["path"] == "media/01_a.jpg"
    assert (tmp_path / "media" / ".cache" / "c1.jpg").exists()
    assert "media/01_a.jpg" in read_json(tmp_path / "media" / "credits.json", {})


@pytest.mark.asyncio
async def test_download_candidate_rejects_corrupt_video_and_thumbnail(tmp_path: Path, monkeypatch) -> None:
    write_json(tmp_path / "media" / "candidates.json", {
        "c2": {"url": "https://example.test/b.mp4", "asset_type": "video", "source": "pexels", "license": "pexels",
               "thumbnail_url": "https://example.test/b.jpg"},
    })

    async def fake_fetch(url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"<html>rate limited</html>")

    monkeypatch.setattr(media, "_fetch", fake_fetch)
    with pytest.raises(ContractError, match="média corrompu"):
        await media.download_candidate(tmp_path, "c2", "02_b")
    assert not (tmp_path / "media" / ".cache" / "c2.mp4").exists()
    assert not (tmp_path / "media" / "credits.json").exists()
    with pytest.raises(ContractError, match="image corrompue"):
        await media._preview_source(tmp_path, "c2")
    assert not (tmp_path / "media" / ".cache" / "c2_thumb.jpg").exists()
