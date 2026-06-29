from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.core.database import MediaAsset
from agent.skills.audio.music_manifest import is_music_track_allowed, music_track_manifest_key
from agent.skills.media.rights_check import (
    build_credits_block,
    enrich_candidate,
    filter_publishable,
    is_publishable,
    normalize_license,
    requires_attribution_for,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CC0 1.0", "CC0"),
        ("Public Domain", "PD"),
        ("domaine public", "PD"),
        ("CC BY 4.0", "CC-BY"),
        ("https://creativecommons.org/licenses/by/4.0/", "CC-BY"),
        ("Pexels License (libre d'utilisation)", "pexels"),
        ("Unsplash License (libre d'utilisation)", "unsplash"),
        ("synthetic-ai-generated", "ai_generated"),
        ("", None),
    ],
)
def test_normalize_license(raw: str, expected: str | None) -> None:
    assert normalize_license(raw) == expected


def test_normalize_license_ai_source() -> None:
    assert normalize_license(None, source="ai_image") == "ai_generated"


def test_normalize_license_rejects_sa() -> None:
    assert normalize_license("CC BY-SA 4.0") == "CC-BY-SA"


@pytest.mark.parametrize(
    ("license_norm", "expected"),
    [
        ("CC0", False),
        ("CC-BY", True),
        ("pexels", False),
        ("ai_generated", False),
    ],
)
def test_requires_attribution_for(license_norm: str, expected: bool) -> None:
    assert requires_attribution_for(license_norm) is expected


@pytest.mark.parametrize(
    ("item", "publishable"),
    [
        ({"license": "CC0", "source": "wikimedia"}, True),
        ({"license": "CC BY 4.0", "source": "wikimedia"}, True),
        ({"license": "CC BY-SA 4.0", "source": "wikimedia"}, False),
        ({"license": "CC BY-NC 4.0", "source": "wikimedia"}, False),
        ({"license": "Pexels License (libre d'utilisation)", "source": "pexels"}, True),
        ({"license": "synthetic-ai-generated", "source": "ai_image"}, True),
        ({"license": "Runway AI Generated (proprietary)", "source": "runway"}, False),
        ({"license": "", "source": "unknown"}, False),
    ],
)
def test_is_publishable(item: dict, publishable: bool) -> None:
    enriched = enrich_candidate(item)
    ok, _ = is_publishable(enriched)
    assert ok is publishable


def test_filter_publishable_splits_candidates() -> None:
    candidates = [
        {"source": "pexels", "license": "Pexels License (libre d'utilisation)", "url": "https://a"},
        {"source": "wikimedia", "license": "CC BY-SA 4.0", "url": "https://b"},
    ]
    accepted, rejected = filter_publishable(candidates)
    assert len(accepted) == 1
    assert accepted[0]["license"] == "pexels"
    assert len(rejected) == 1
    assert rejected[0]["_rejection_category"] == "license_rejected"


def test_enrich_candidate_extracts_author_from_pexels() -> None:
    item = enrich_candidate({
        "source": "pexels",
        "license": "Pexels License (libre d'utilisation)",
        "attribution": "Photo par Jane Doe via Pexels (https://pexels.com)",
        "url": "https://images.pexels.com/photo.jpg",
    })
    assert item["author"] == "Jane Doe"
    assert item["license"] == "pexels"
    assert item["source_url"] == "https://images.pexels.com/photo.jpg"
    assert item["requires_attribution"] is False


def test_build_credits_block_dedup_and_format() -> None:
    project_id = uuid.uuid4()
    assets = [
        MediaAsset(
            project_id=project_id,
            source="wikimedia",
            source_url="https://commons.wikimedia.org/file1.jpg",
            license="CC-BY",
            author="Alice",
            requires_attribution=True,
            asset_type="image",
        ),
        MediaAsset(
            project_id=project_id,
            source="wikimedia",
            source_url="https://commons.wikimedia.org/file1.jpg",
            license="CC-BY",
            author="Alice",
            requires_attribution=True,
            asset_type="image",
        ),
        MediaAsset(
            project_id=project_id,
            source="pexels",
            license="pexels",
            author="Bob",
            requires_attribution=False,
            asset_type="image",
        ),
    ]
    block = build_credits_block(assets)
    assert block.startswith("Crédits :")
    assert block.count("Alice") == 1
    assert "CC-BY" in block
    assert "Bob" not in block


def test_music_track_without_manifest_entry_excluded(tmp_path: Path) -> None:
    music_base = tmp_path / "music"
    mood_dir = music_base / "calme"
    mood_dir.mkdir(parents=True)
    track = mood_dir / "secret.mp3"
    track.write_bytes(b"\x00" * 100)

    manifest = {"calme/listed.mp3": {"license": "CC0", "author": "Test"}}
    key = music_track_manifest_key(track, music_base=music_base)
    assert key == "calme/secret.mp3"
    assert is_music_track_allowed(track, manifest, music_base=music_base) is False


def test_music_track_with_manifest_entry_allowed(tmp_path: Path) -> None:
    music_base = tmp_path / "music"
    mood_dir = music_base / "calme"
    mood_dir.mkdir(parents=True)
    track = mood_dir / "listed.mp3"
    track.write_bytes(b"\x00" * 100)

    manifest = {"calme/listed.mp3": {"license": "CC0", "author": "Test"}}
    assert is_music_track_allowed(track, manifest, music_base=music_base) is True


def test_select_music_excludes_unlisted_track(tmp_path: Path) -> None:
    from agent.skills.audio import music_selector

    music_base = tmp_path / "music"
    mood_dir = music_base / "calme"
    mood_dir.mkdir(parents=True)
    track = mood_dir / "unlisted.mp3"
    track.write_bytes(b"\x00" * 100)

    manifest = {}
    with patch.object(music_selector, "MUSIC_BASE", music_base):
        with patch.object(music_selector, "load_music_manifest", return_value=manifest):
            assert music_selector.select_music_for_mood("calme") is None

    manifest = {"calme/unlisted.mp3": {"license": "CC0", "author": "Artist"}}
    with patch.object(music_selector, "MUSIC_BASE", music_base):
        with patch.object(music_selector, "load_music_manifest", return_value=manifest):
            chosen = music_selector.select_music_for_mood("calme")
            assert chosen == track
