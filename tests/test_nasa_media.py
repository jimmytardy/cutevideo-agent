from __future__ import annotations

from agent.skills.media_sources.nasa import (
    pick_nasa_image_url,
    pick_nasa_thumbnail,
    pick_nasa_video_url,
    _extract_year,
)


def test_pick_nasa_video_url_prefers_medium() -> None:
    manifest = [
        "http://images-assets.nasa.gov/video/demo/demo~orig.mp4",
        "http://images-assets.nasa.gov/video/demo/demo~medium.mp4",
        "http://images-assets.nasa.gov/video/demo/demo~preview.mp4",
    ]
    assert pick_nasa_video_url(manifest) == "https://images-assets.nasa.gov/video/demo/demo~medium.mp4"


def test_pick_nasa_video_url_skips_sidecar_renditions() -> None:
    manifest = [
        "http://images-assets.nasa.gov/video/demo/demo~medium_1.mp4",
        "http://images-assets.nasa.gov/video/demo/demo~preview.mp4",
    ]
    assert pick_nasa_video_url(manifest) == "https://images-assets.nasa.gov/video/demo/demo~preview.mp4"


def test_pick_nasa_image_url_prefers_orig() -> None:
    links = [
        {"href": "https://images-assets.nasa.gov/image/PIA14417/PIA14417~small.jpg", "render": "image"},
        {"href": "https://images-assets.nasa.gov/image/PIA14417/PIA14417~orig.jpg", "render": "image"},
    ]
    assert pick_nasa_image_url(links) == "https://images-assets.nasa.gov/image/PIA14417/PIA14417~orig.jpg"


def test_pick_nasa_thumbnail_from_manifest() -> None:
    manifest = [
        "https://images-assets.nasa.gov/video/demo/demo~medium.mp4",
        "https://images-assets.nasa.gov/video/demo/demo~large.jpg",
    ]
    thumb = pick_nasa_thumbnail(manifest, [])
    assert thumb == "https://images-assets.nasa.gov/video/demo/demo~large.jpg"


def test_extract_year_from_period() -> None:
    assert _extract_year("Années 1960") == "1960"
    assert _extract_year("") is None
