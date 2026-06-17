from __future__ import annotations

from agent.skills.video.ken_burns import _build_static_filter, _build_zoom_filter


def test_ken_burns_filter_is_centered_without_pan() -> None:
    vf = _build_zoom_filter(
        1920, 1080, 25, 125,
        zoom_factor=0.03,
        pan_enabled=False,
        pan_direction=0,
    )
    assert "n/" in vf
    assert "eval=frame" in vf
    assert "zoompan" not in vf
    assert "scale=2880:1620" in vf
    assert "flags=lanczos" in vf


def test_ken_burns_filter_linear_zoom() -> None:
    vf = _build_zoom_filter(
        1080, 1920, 30, 150,
        zoom_factor=0.03,
        pan_enabled=False,
        pan_direction=0,
    )
    assert "(1+0.03*n/150)" in vf
    assert "scale=1080:1920:flags=lanczos" in vf


def test_ken_burns_filter_pan_when_enabled() -> None:
    vf = _build_zoom_filter(
        1920, 1080, 25, 125,
        zoom_factor=0.03,
        pan_enabled=True,
        pan_direction=1,
    )
    assert "40*n/" in vf


def test_ken_burns_static_when_zoom_zero() -> None:
    vf = _build_zoom_filter(
        1920, 1080, 25, 125,
        zoom_factor=0.0,
        pan_enabled=False,
        pan_direction=0,
    )
    assert vf == _build_static_filter(1920, 1080, 25)
