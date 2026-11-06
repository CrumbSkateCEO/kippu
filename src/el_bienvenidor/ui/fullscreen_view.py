"""Ventana OpenCV no interactiva salvo comandos operativos mínimos."""

from __future__ import annotations

from enum import Enum
import logging
from typing import Any, Protocol

from el_bienvenidor.config import UiSettings
from el_bienvenidor.domain.models import AppSnapshot, AppState, FramePacket, LandmarkMap
from el_bienvenidor.ui.overlay import draw_landmark_map, draw_overlay
from el_bienvenidor.ui.print_overlay import draw_print_screen

LOGGER = logging.getLogger(__name__)


class UserCommand(str, Enum):
    CANCEL = "cancel"
    RETRY = "retry"
    QUIT = "quit"
    TRIGGER = "trigger"
    EDIT_GUEST = "edit_guest"


class FullscreenView(Protocol):
    def open(self) -> None: ...
    def render(self, snapshot: AppSnapshot, preview: FramePacket | None, landmark_map: LandmarkMap | None = None) -> None: ...
    def poll_commands(self) -> list[UserCommand]: ...
    def close(self) -> None: ...


def _cv2() -> Any:
    try:
        import cv2
    except ModuleNotFoundError as error:
        raise RuntimeError("OpenCV no está instalado.") from error
    return cv2


# Estados en los que se muestra la pantalla post-foto en lugar del feed de cámara.
_POST_PHOTO_STATES = {AppState.PROCESSING, AppState.PRINTING}


class OpenCVFullscreenView:
    def __init__(
        self,
        settings: UiSettings,
        *,
        allow_inkless: bool = False,
        printer_name: str | None = None,
    ) -> None:
        self._settings = settings
        self._allow_inkless = allow_inkless
        self._printer_name = printer_name
        self._is_open = False

    def open(self) -> None:
        cv2 = _cv2()
        cv2.namedWindow(self._settings.window_name, cv2.WINDOW_NORMAL)
        if self._settings.fullscreen:
            cv2.setWindowProperty(self._settings.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        self._is_open = True

    def render(self, snapshot: AppSnapshot, preview: FramePacket | None, landmark_map: LandmarkMap | None = None) -> None:
        if not self._is_open:
            return
        cv2 = _cv2()
        if preview is None or preview.image_bgr is None:
            try:
                import numpy as np
            except ModuleNotFoundError as error:
                raise RuntimeError("NumPy no está instalado.") from error
            image = np.zeros((720, 1280, 3), dtype=np.uint8)
        else:
            image = preview.image_bgr[:, ::-1].copy()

        if snapshot.state in _POST_PHOTO_STATES:
            # Pantalla post-foto: miniatura del carnet + estado de impresión.
            frame = draw_print_screen(
                image,
                snapshot,
                allow_inkless=self._allow_inkless,
                printer_name=self._printer_name,
            )
        else:
            # HUD normal: feed de cámara con overlays de saludo/cuenta.
            image = draw_landmark_map(image, landmark_map, mirrored=True)
            frame = draw_overlay(image, snapshot)

        cv2.imshow(self._settings.window_name, frame)

    def poll_commands(self) -> list[UserCommand]:
        if not self._is_open:
            return []
        key = _cv2().waitKey(1) & 0xFF
        return {
            27: [UserCommand.CANCEL],
            ord("q"): [UserCommand.QUIT],
            ord("Q"): [UserCommand.QUIT],
            ord("r"): [UserCommand.RETRY],
            ord("R"): [UserCommand.RETRY],
            32: [UserCommand.TRIGGER],  # Barra espaciadora
            13: [UserCommand.TRIGGER],  # Enter
            ord("e"): [UserCommand.EDIT_GUEST],
            ord("E"): [UserCommand.EDIT_GUEST],
        }.get(key, [])

    def close(self) -> None:
        if self._is_open:
            _cv2().destroyWindow(self._settings.window_name)
        self._is_open = False


class HeadlessView:
    """Vista para diagnóstico, automatización y pruebas sin servidor gráfico."""

    def __init__(self) -> None:
        self._last: tuple[object, str] | None = None

    def open(self) -> None:
        return None

    def render(self, snapshot: AppSnapshot, preview: FramePacket | None, landmark_map: LandmarkMap | None = None) -> None:
        marker = (snapshot.state, snapshot.message)
        if marker != self._last:
            LOGGER.info(snapshot.message, extra={"state": snapshot.state.value, "job_id": str(snapshot.job_id) if snapshot.job_id else ""})
            self._last = marker

    def poll_commands(self) -> list[UserCommand]:
        return []

    def close(self) -> None:
        return None
