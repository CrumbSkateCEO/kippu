"""Logging rotativo estructurado sin imágenes ni datos biométricos."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from el_bienvenidor.config import LoggingSettings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("job_id", "event", "state", "error_code"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: LoggingSettings) -> None:
    settings.directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(settings.directory / "kippu.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=getattr(logging, settings.level, logging.INFO), handlers=[handler], force=True)

