"""Tipos inmutables que cruzan los límites entre módulos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, NewType
from uuid import UUID

FrameId = NewType("FrameId", int)
JobId = NewType("JobId", UUID)
Point = tuple[float, float]


@dataclass(frozen=True)
class LandmarkPoint:
    """Punto normalizado producido por el modelo de visión.

    Las coordenadas ``x`` e ``y`` están normalizadas respecto del frame; ``z``
    conserva la profundidad relativa que entrega MediaPipe. No se persisten:
    sólo se usan para dibujar el mapa de la vista previa actual.
    """

    x: float
    y: float
    z: float = 0.0
    visibility: float | None = None
    presence: float | None = None


@dataclass(frozen=True)
class LandmarkLayer:
    """Puntos y aristas (vectores) de una parte del cuerpo."""

    name: str
    points: tuple[LandmarkPoint, ...]
    connections: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class LandmarkMap:
    """Mapa efímero completo para superponer sobre un frame de cámara."""

    pose: LandmarkLayer | None = None
    face: LandmarkLayer | None = None
    left_hand: LandmarkLayer | None = None
    right_hand: LandmarkLayer | None = None

    def layers(self) -> tuple[LandmarkLayer, ...]:
        return tuple(layer for layer in (self.pose, self.face, self.left_hand, self.right_hand) if layer is not None)


class AppState(str, Enum):
    STARTUP = "startup"
    IDLE = "idle"
    GREETING_HELD = "greeting_held"
    COUNTDOWN = "countdown"
    PROCESSING = "processing"
    PRINTING = "printing"
    CAMERA_ERROR = "camera_error"
    PRINTER_ERROR = "printer_error"
    PROCESSING_ERROR = "processing_error"
    STOPPED = "stopped"


class PrinterDisposition(str, Enum):
    ACCEPTED = "accepted"
    PRE_START_FAILURE = "pre_start_failure"
    UNKNOWN_AFTER_SUBMIT = "unknown_after_submit"
    QUEUE_ERROR = "queue_error"


class PrinterHealth(str, Enum):
    READY = "ready"
    OFFLINE = "offline"
    PAUSED = "paused"
    PAPER_OUT = "paper_out"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FramePacket:
    frame_id: FrameId
    captured_monotonic_s: float
    image_bgr: Any
    source_size: tuple[int, int]


@dataclass(frozen=True)
class GestureObservation:
    salute_detected: bool
    wrist: Point | None
    shoulder: Point | None
    confidence: float
    reason: str


@dataclass(frozen=True)
class CaptureRequest:
    job_id: JobId
    frame: FramePacket
    requested_monotonic_s: float
    metadata: "CardData"


@dataclass(frozen=True)
class FaceCrop:
    image_rgb: Any
    source_box_px: tuple[int, int, int, int]
    confidence: float


@dataclass(frozen=True)
class CardData:
    """Datos impresos en el carnet vertical 10×15.

    ``guest_name`` es el campo principal; ``organization`` y ``role``
    completan el bloque de identidad cuando el operador los captura.
    """

    headline: str
    guest_name: str | None
    issued_at: datetime
    serial: str
    organization: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class CardArtifact:
    job_id: JobId
    png_path: Path
    pixel_size: tuple[int, int]
    dpi: tuple[int, int]
    sha256: str


@dataclass(frozen=True)
class PrintReceipt:
    job_id: JobId
    printer_name: str
    spooler_job_id: int | None
    submitted_at: datetime
    disposition: PrinterDisposition
    detail: str


@dataclass(frozen=True)
class CameraProbe:
    index: int
    backend: str
    resolution: tuple[int, int]
    fps: float
    focus_verified: bool
    detail: str


@dataclass(frozen=True)
class PrinterProbe:
    printer_name: str
    health: PrinterHealth
    printable_size_px: tuple[int, int] | None
    dpi: tuple[int, int] | None
    detail: str


@dataclass(frozen=True)
class PrinterStatus:
    health: PrinterHealth
    raw_status: int
    detail: str


@dataclass(frozen=True)
class JobStatus:
    found: bool
    raw_status: int
    detail: str


@dataclass(frozen=True)
class AppSnapshot:
    state: AppState
    state_since_monotonic_s: float
    message: str
    job_id: JobId | None = None
    greeting_elapsed_s: float = 0.0
    countdown_value: int | None = None
    guest_name: str | None = None


@dataclass(frozen=True)
class Transition:
    previous: AppState
    current: AppState
    accepted: bool
    reason: str
    at_monotonic_s: float


@dataclass(frozen=True)
class RetentionReport:
    deleted_job_directories: int = 0
    skipped_job_directories: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)
