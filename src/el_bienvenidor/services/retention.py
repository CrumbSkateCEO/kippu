"""Retención explícita de artefactos de trabajos terminados."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from el_bienvenidor.config import StorageSettings
from el_bienvenidor.domain.models import RetentionReport


def purge_expired_jobs(now: datetime, policy: StorageSettings) -> RetentionReport:
    if policy.jobs_directory.name != "jobs":
        return RetentionReport(errors=("La retención sólo opera sobre un directorio llamado 'jobs'.",))
    if not policy.jobs_directory.exists():
        return RetentionReport()
    deleted = 0
    skipped = 0
    errors: list[str] = []
    cutoff = now.timestamp() - policy.retention_hours * 3600
    for path in policy.jobs_directory.iterdir():
        if not path.is_dir():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                shutil.rmtree(path)
                deleted += 1
            else:
                skipped += 1
        except OSError as error:
            errors.append(f"{path.name}: {error}")
    return RetentionReport(deleted, skipped, tuple(errors))


def purge_now(policy: StorageSettings) -> RetentionReport:
    return purge_expired_jobs(datetime.now(timezone.utc), policy)
