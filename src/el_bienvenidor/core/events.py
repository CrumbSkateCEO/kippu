"""Eventos que alimentan la máquina de estados."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from el_bienvenidor.domain.models import JobId


class AppEventType(str, Enum):
    STARTUP_READY = "startup_ready"
    CAMERA_FAILURE = "camera_failure"
    PRINTER_FAILURE = "printer_failure"
    RETRY = "retry"
    GREETING_STARTED = "greeting_started"
    GREETING_LOST = "greeting_lost"
    HOLD_MET = "hold_met"
    COUNTDOWN_FINISHED = "countdown_finished"
    CANCEL = "cancel"
    PRINT_SUBMITTED = "print_submitted"
    PRINT_COMPLETED = "print_completed"
    PROCESSING_FAILED = "processing_failed"
    ACKNOWLEDGE = "acknowledge"
    STOP = "stop"


@dataclass(frozen=True)
class AppEvent:
    kind: AppEventType
    job_id: JobId | None = None
    message: str = ""


class JobEventType(str, Enum):
    PROCESSING_STARTED = "processing_started"
    CARD_COMPOSED = "card_composed"
    PRINT_SUBMITTED = "print_submitted"
    PRINT_COMPLETED = "print_completed"
    PROCESSING_FAILED = "processing_failed"
    PRINTER_FAILED = "printer_failed"


@dataclass(frozen=True)
class JobEvent:
    kind: JobEventType
    job_id: JobId
    message: str = ""

