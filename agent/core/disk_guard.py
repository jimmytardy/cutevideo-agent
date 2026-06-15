from __future__ import annotations

import shutil
from pathlib import Path

from agent.core.config import get_pipeline_settings

DEFAULT_WORK_PATHS = (Path("./tmp"), Path("./output"))


class DiskSpaceError(RuntimeError):
    """Espace disque insuffisant pour démarrer un pipeline."""


def get_free_bytes(paths: tuple[Path, ...] | None = None) -> int:
    """Retourne l'espace libre minimal parmi les chemins de travail."""
    work_paths = paths or DEFAULT_WORK_PATHS
    free_values: list[int] = []
    for path in work_paths:
        target = path
        target.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(target)
        free_values.append(int(usage.free))
    return min(free_values) if free_values else 0


def is_disk_sufficient() -> bool:
    cfg = get_pipeline_settings()
    return get_free_bytes() >= cfg.min_free_disk_bytes


def format_disk_wait_message() -> str:
    cfg = get_pipeline_settings()
    free = get_free_bytes()
    required = cfg.min_free_disk_bytes
    free_gb = free / (1024**3)
    required_gb = required / (1024**3)
    return (
        f"En attente : espace disque insuffisant "
        f"({free_gb:.1f} Go libres, {required_gb:.1f} Go requis)"
    )


def ensure_disk_for_pipeline() -> None:
    if not is_disk_sufficient():
        raise DiskSpaceError(format_disk_wait_message())
