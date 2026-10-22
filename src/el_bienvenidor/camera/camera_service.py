"""Acceso exclusivo y recuperable a una webcam mediante OpenCV."""

from __future__ import annotations

from dataclasses import dataclass
import sys
import threading
import time
from time import monotonic
from typing import Any, Protocol

from el_bienvenidor.config import CameraSettings
from el_bienvenidor.domain.errors import CameraUnavailableError
from el_bienvenidor.domain.models import CameraProbe, FrameId, FramePacket


class CameraService(Protocol):
    def open(self) -> CameraProbe: ...
    def read(self) -> FramePacket | None: ...
    def is_open(self) -> bool: ...
    def release(self) -> None: ...


@dataclass(frozen=True)
class FocusResult:
    requested_autofocus: bool
    requested_focus: int | None
    verified: bool
    detail: str


def _load_cv2() -> Any:
    try:
        import cv2
    except ModuleNotFoundError as error:
        raise CameraUnavailableError("OpenCV no está instalado en este entorno.") from error
    return cv2


def configure_focus(capture: Any, settings: CameraSettings) -> FocusResult:
    """Solicita foco manual; no afirma éxito si el driver no permite verificarlo."""
    cv2 = _load_cv2()
    try:
        capture.set(cv2.CAP_PROP_AUTOFOCUS, 1 if settings.autofocus else 0)
        if not settings.autofocus and settings.focus is not None:
            capture.set(cv2.CAP_PROP_FOCUS, settings.focus)
        autofocus_read = capture.get(cv2.CAP_PROP_AUTOFOCUS)
        focus_read = capture.get(cv2.CAP_PROP_FOCUS) if settings.focus is not None else None
    except Exception as error:
        return FocusResult(settings.autofocus, settings.focus, False, f"Driver no verificable: {error}")

    autofocus_ok = abs(float(autofocus_read) - float(1 if settings.autofocus else 0)) < 0.1
    focus_ok = settings.focus is None or focus_read is not None and abs(float(focus_read) - settings.focus) <= 2.0
    verified = autofocus_ok and focus_ok
    if verified:
        return FocusResult(settings.autofocus, settings.focus, True, "Foco confirmado por el driver.")
    return FocusResult(settings.autofocus, settings.focus, False, "El driver no confirmó el bloqueo de foco.")


class OpenCVCameraService:
    """
    Captura de cámara con hilo dedicado en segundo plano.
    Evita la acumulación de frames en el buffer del driver (latencia cero).
    """

    def __init__(self, settings: CameraSettings) -> None:
        self._settings = settings
        self._capture: Any | None = None
        self._frame_id = 0
        self._latest_image: Any | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def _backend_candidates(self, cv2: Any) -> tuple[tuple[str, int | None], ...]:
        """Devuelve backends apropiados para la plataforma, con fallback seguro."""
        requested = self._settings.backend.strip()
        if requested.lower() != "auto":
            backend = getattr(cv2, requested, None)
            if backend is None:
                raise CameraUnavailableError(f"El backend OpenCV configurado no existe: {requested}.")
            return ((requested, int(backend)), ("default", None))
        if sys.platform.startswith("linux"):
            names = ("CAP_V4L2", "CAP_GSTREAMER")
        elif sys.platform == "win32":
            names = ("CAP_DSHOW", "CAP_MSMF")
        elif sys.platform == "darwin":
            names = ("CAP_AVFOUNDATION",)
        else:
            names = ("CAP_V4L2",)
        candidates: list[tuple[str, int | None]] = []
        for name in names:
            backend = getattr(cv2, name, None)
            if backend is not None and (name, int(backend)) not in candidates:
                candidates.append((name, int(backend)))
        candidates.append(("default", None))
        return tuple(candidates)

    def _capture_worker(self) -> None:
        """Hilo en segundo plano que vacía constantemente el buffer de la webcam."""
        while self._running:
            cap = self._capture
            if cap is None or not cap.isOpened():
                time.sleep(0.01)
                continue
            try:
                success, image = cap.read()
                if success and image is not None and getattr(image, "size", 0) > 0:
                    with self._lock:
                        self._latest_image = image
                else:
                    time.sleep(0.005)
            except Exception:
                time.sleep(0.01)

    def open(self) -> CameraProbe:
        self.release()
        cv2 = _load_cv2()
        capture = None
        backend_name = "default"
        for candidate_name, backend in self._backend_candidates(cv2):
            candidate = cv2.VideoCapture(self._settings.index, backend) if backend is not None else cv2.VideoCapture(self._settings.index)
            if candidate.isOpened():
                capture = candidate
                backend_name = candidate_name
                break
            candidate.release()
        if capture is None:
            raise CameraUnavailableError(f"No se pudo abrir la cámara con índice {self._settings.index}.")

        # Tamaño de buffer mínimo para eliminar retraso
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._settings.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._settings.height)
        capture.set(cv2.CAP_PROP_FPS, self._settings.fps)
        focus_result = configure_focus(capture, self._settings)
        self._capture = capture

        # Leer un primer frame para inicializar _latest_image
        success, first_image = capture.read()
        if success and first_image is not None:
            with self._lock:
                self._latest_image = first_image

        # Iniciar hilo de lectura continua
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_worker, daemon=True, name="webcam-capture-thread"
        )
        self._thread.start()

        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        return CameraProbe(
            index=self._settings.index,
            backend=backend_name,
            resolution=(width, height),
            fps=fps,
            focus_verified=focus_result.verified,
            detail=focus_result.detail,
        )

    def read(self) -> FramePacket | None:
        if self._capture is None or not self._capture.isOpened() or not self._running:
            return None
        with self._lock:
            image = self._latest_image
        if image is None or getattr(image, "size", 0) == 0:
            return None
        self._frame_id += 1
        height, width = image.shape[:2]
        return FramePacket(FrameId(self._frame_id), monotonic(), image, (int(width), int(height)))

    def is_open(self) -> bool:
        return self._capture is not None and bool(self._capture.isOpened()) and self._running

    def release(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        if self._capture is not None:
            try:
                self._capture.release()
            finally:
                self._capture = None
        with self._lock:
            self._latest_image = None
