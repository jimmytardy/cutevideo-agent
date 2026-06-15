from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agent.core.disk_guard import get_free_bytes, is_disk_sufficient


def test_get_free_bytes_uses_minimum_path(tmp_path: Path) -> None:
    path_a = tmp_path / "a"
    path_b = tmp_path / "b"
    path_a.mkdir()
    path_b.mkdir()
    with patch("agent.core.disk_guard.shutil.disk_usage") as mock_usage:
        mock_usage.side_effect = [
            type("U", (), {"free": 100})(),
            type("U", (), {"free": 50})(),
        ]
        assert get_free_bytes((path_a, path_b)) == 50


def test_is_disk_sufficient_respects_threshold() -> None:
    with patch("agent.core.disk_guard.get_free_bytes", return_value=20_000_000_000):
        with patch("agent.core.disk_guard.get_pipeline_settings") as mock_cfg:
            mock_cfg.return_value.min_free_disk_bytes = 10_000_000_000
            assert is_disk_sufficient() is True

    with patch("agent.core.disk_guard.get_free_bytes", return_value=1_000):
        with patch("agent.core.disk_guard.get_pipeline_settings") as mock_cfg:
            mock_cfg.return_value.min_free_disk_bytes = 10_000_000_000
            assert is_disk_sufficient() is False
