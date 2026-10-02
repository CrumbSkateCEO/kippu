"""Rutas de trabajo y persistencia atómica de artefactos privados."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from el_bienvenidor.config import StorageSettings
from el_bienvenidor.domain.models import JobId


def job_directory(job_id: JobId, settings: StorageSettings) -> Path:
    path = settings.jobs_directory / str(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_save_png(image: object, path: Path, dpi: tuple[int, int]) -> Path:
    """Escribe completamente un temporal y sólo después reemplaza el destino."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    image.save(temporary, format="PNG", dpi=dpi)  # type: ignore[attr-defined]
    os.replace(temporary, path)
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

