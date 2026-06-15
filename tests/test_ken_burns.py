from __future__ import annotations

from agent.skills.video.ken_burns import _build_zoom_filter


def test_ken_burns_filter_is_centered_without_pan() -> None:
    vf = _build_zoom_filter(
        1920, 1080, 25, 125,
        zoom_factor=0.05,
        pan_enabled=False,
        pan_direction=0,
    )
    assert "on/" in vf
    assert "iw/2-(iw/zoom/2)" in vf
    assert "scale=3840:2160" in vf


def test_ken_burns_filter_linear_zoom() -> None:
    vf = _build_zoom_filter(
        1080, 1920, 30, 150,
        zoom_factor=0.05,
        pan_enabled=False,
        pan_direction=0,
    )
    assert "zoompan=z='1+0.05*on/150'" in vf


def test_ken_burns_filter_pan_when_enabled() -> None:
    vf = _build_zoom_filter(
        1920, 1080, 25, 125,
        zoom_factor=0.05,
        pan_enabled=True,
        pan_direction=1,
    )
    assert "40*on/" in vf
