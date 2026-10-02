"""Carga y validación de configuración local TOML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from el_bienvenidor.domain.errors import ConfigurationError

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass(frozen=True)
class CameraSettings:
    index: int = 0
    backend: str = "auto"
    width: int = 1280
    height: int = 720
    fps: int = 30
    autofocus: bool = True
    focus: int | None = None
    capture_mirrored: bool = False
    read_failure_threshold: int = 8
    reconnect_delays_seconds: tuple[float, ...] = (1.0, 2.0, 5.0)


@dataclass(frozen=True)
class VisionSettings:
    landmark_confidence: float = 0.50
    vertical_margin: float = 0.03
    salute_hold_seconds: float = 1.0
    pose_detection_confidence: float = 0.5
    face_confidence: float = 0.80
    secondary_face_area_ratio: float = 0.65
    minimum_face_height_px: int = 80


@dataclass(frozen=True)
class PrintSettings:
    dry_run: bool = True
    expected_width_px: int = 1181
    expected_height_px: int = 1772
    expected_dpi: int = 300
    minimum_printing_message_seconds: float = 1.5
    monitor_window_seconds: float = 20.0
    printer_name: str | None = None


@dataclass(frozen=True)
class StorageSettings:
    jobs_directory: Path
    retention_hours: float = 24.0


@dataclass(frozen=True)
class UiSettings:
    window_name: str = "Kippu"
    fullscreen: bool = True
    show_landmarks: bool = True
    guest_form_enabled: bool = True
    card_headline: str = "¡Bienvenido!"
    form_width: int = 960
    form_height: int = 720
    ask_guest_each_job: bool = True


@dataclass(frozen=True)
class LoggingSettings:
    directory: Path
    level: str = "INFO"


@dataclass(frozen=True)
class AppSettings:
    camera: CameraSettings
    vision: VisionSettings
    printing: PrintSettings
    storage: StorageSettings
    ui: UiSettings
    logging: LoggingSettings
    project_root: Path


def _table(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigurationError(f"La sección [{name}] debe ser una tabla TOML.")
    return value


def _relative_to_root(value: str, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def load_settings(path: Path) -> AppSettings:
    """Carga TOML y resuelve rutas relativas respecto de la raíz del proyecto."""
    if not path.is_file():
        raise ConfigurationError(f"No existe el archivo de configuración: {path}")
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    root = path.resolve().parent.parent
    camera = _table(raw, "camera")
    vision = _table(raw, "vision")
    printing = _table(raw, "print")
    storage = _table(raw, "storage")
    ui = _table(raw, "ui")
    logging = _table(raw, "logging")
    printer_name = str(printing.get("printer_name", "")).strip() or None
    settings = AppSettings(
        camera=CameraSettings(
            index=int(camera.get("index", 0)),
            backend=str(camera.get("backend", "auto")),
            width=int(camera.get("width", 1280)),
            height=int(camera.get("height", 720)),
            fps=int(camera.get("fps", 30)),
            autofocus=bool(camera.get("autofocus", True)),
            focus=(None if camera.get("focus") is None else int(camera.get("focus"))),
            capture_mirrored=bool(camera.get("capture_mirrored", False)),
            read_failure_threshold=int(camera.get("read_failure_threshold", 8)),
            reconnect_delays_seconds=tuple(float(item) for item in camera.get("reconnect_delays_seconds", [1, 2, 5])),
        ),
        vision=VisionSettings(
            landmark_confidence=float(vision.get("landmark_confidence", 0.50)),
            vertical_margin=float(vision.get("vertical_margin", 0.03)),
            salute_hold_seconds=float(vision.get("salute_hold_seconds", 1.0)),
            pose_detection_confidence=float(vision.get("pose_detection_confidence", 0.5)),
            face_confidence=float(vision.get("face_confidence", 0.80)),
            secondary_face_area_ratio=float(vision.get("secondary_face_area_ratio", 0.65)),
            minimum_face_height_px=int(vision.get("minimum_face_height_px", 80)),
        ),
        printing=PrintSettings(
            dry_run=bool(printing.get("dry_run", True)),
            expected_width_px=int(printing.get("expected_width_px", 1181)),
            expected_height_px=int(printing.get("expected_height_px", 1772)),
            expected_dpi=int(printing.get("expected_dpi", 300)),
            minimum_printing_message_seconds=float(printing.get("minimum_printing_message_seconds", 1.5)),
            monitor_window_seconds=float(printing.get("monitor_window_seconds", 20)),
            printer_name=printer_name,
        ),
        storage=StorageSettings(
            jobs_directory=_relative_to_root(str(storage.get("jobs_directory", "data/jobs")), root),
            retention_hours=float(storage.get("retention_hours", 24)),
        ),
        ui=UiSettings(
            window_name=str(ui.get("window_name", "Kippu")),
            fullscreen=bool(ui.get("fullscreen", True)),
            show_landmarks=bool(ui.get("show_landmarks", True)),
            guest_form_enabled=bool(ui.get("guest_form_enabled", True)),
            card_headline=str(ui.get("card_headline", "¡Bienvenido!")).strip() or "¡Bienvenido!",
            form_width=int(ui.get("form_width", 960)),
            form_height=int(ui.get("form_height", 720)),
            ask_guest_each_job=bool(ui.get("ask_guest_each_job", True)),
        ),
        logging=LoggingSettings(
            directory=_relative_to_root(str(logging.get("directory", "logs")), root),
            level=str(logging.get("level", "INFO")).upper(),
        ),
        project_root=root,
    )
    validate_settings(settings)
    return settings


def validate_settings(settings: AppSettings) -> None:
    camera = settings.camera
    vision = settings.vision
    printing = settings.printing
    if camera.index < 0 or camera.width < 320 or camera.height < 240 or camera.fps <= 0:
        raise ConfigurationError("La configuración de cámara es inválida.")
    if not camera.backend.strip():
        raise ConfigurationError("camera.backend debe ser un backend OpenCV o 'auto'.")
    if camera.read_failure_threshold < 1 or not camera.reconnect_delays_seconds:
        raise ConfigurationError("La recuperación de cámara requiere umbrales y demoras positivas.")
    if any(delay <= 0 for delay in camera.reconnect_delays_seconds):
        raise ConfigurationError("Las demoras de reconexión deben ser mayores que cero.")
    for value, name in (
        (vision.landmark_confidence, "landmark_confidence"),
        (vision.pose_detection_confidence, "pose_detection_confidence"),
        (vision.face_confidence, "face_confidence"),
        (vision.secondary_face_area_ratio, "secondary_face_area_ratio"),
    ):
        if not 0 < value <= 1:
            raise ConfigurationError(f"vision.{name} debe estar entre 0 y 1.")
    if vision.vertical_margin < 0 or vision.salute_hold_seconds <= 0 or vision.minimum_face_height_px <= 0:
        raise ConfigurationError("Los umbrales de visión deben ser positivos.")
    if (printing.expected_width_px, printing.expected_height_px, printing.expected_dpi) != (1181, 1772, 300):
        raise ConfigurationError("Kippu requiere salida fija de 1181x1772 px a 300 DPI.")
    if printing.minimum_printing_message_seconds < 0 or printing.monitor_window_seconds <= 0:
        raise ConfigurationError("Los tiempos de impresión son inválidos.")
    if settings.storage.retention_hours < 0:
        raise ConfigurationError("storage.retention_hours no puede ser negativo.")
    if settings.ui.form_width < 640 or settings.ui.form_height < 480:
        raise ConfigurationError("ui.form_width/form_height deben ser al menos 640x480.")
    if not settings.ui.card_headline.strip():
        raise ConfigurationError("ui.card_headline no puede estar vacío.")
    data_root = (settings.project_root / "data").resolve()
    try:
        settings.storage.jobs_directory.resolve().relative_to(data_root)
    except ValueError as error:
        raise ConfigurationError("storage.jobs_directory debe estar dentro de data/ del proyecto.") from error
