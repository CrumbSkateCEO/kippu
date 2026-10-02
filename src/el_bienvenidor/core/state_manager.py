"""Máquina de estados pura de la experiencia Kippu."""

from __future__ import annotations

import math

from el_bienvenidor.core.events import AppEvent, AppEventType
from el_bienvenidor.domain.models import AppSnapshot, AppState, Transition


_MESSAGES: dict[AppState, str] = {
    AppState.STARTUP: "Preparando la cámara…",
    AppState.IDLE: "Levante una mano por encima del hombro",
    AppState.GREETING_HELD: "Perfecto, mantenga el saludo",
    AppState.COUNTDOWN: "Sonría, vamos a capturar",
    AppState.PROCESSING: "Componiendo su carnet…",
    AppState.PRINTING: "Enviando a impresión…",
    AppState.CAMERA_ERROR: "Revise la cámara y pulse R",
    AppState.PRINTER_ERROR: "Revise papel, tapa y cola de impresión",
    AppState.PROCESSING_ERROR: "No pudimos preparar la foto. Inténtelo de nuevo.",
    AppState.STOPPED: "Kippu detenido",
}


class StateManager:
    """Acepta eventos explícitos; nunca consulta hardware ni reloj por sí mismo."""

    def __init__(self, countdown_seconds: float = 3.0) -> None:
        self._state = AppState.STARTUP
        self._state_since = 0.0
        self._job_id = None
        self._countdown_seconds = countdown_seconds
        self._message_override = ""

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def state_since_monotonic_s(self) -> float:
        return self._state_since

    def dispatch(self, event: AppEvent, at_monotonic_s: float) -> Transition:
        previous = self._state
        target = self._target_for(event)
        if target is None:
            return Transition(previous, previous, False, f"Evento no válido: {event.kind.value}", at_monotonic_s)
        self._state = target
        self._state_since = at_monotonic_s
        self._message_override = event.message
        if event.job_id is not None:
            self._job_id = event.job_id
        if target in {AppState.IDLE, AppState.CAMERA_ERROR, AppState.PRINTER_ERROR, AppState.PROCESSING_ERROR, AppState.STOPPED}:
            if target == AppState.IDLE:
                self._job_id = None
        return Transition(previous, target, True, event.kind.value, at_monotonic_s)

    def _target_for(self, event: AppEvent) -> AppState | None:
        if event.kind is AppEventType.STOP:
            return AppState.STOPPED
        if self._state in {AppState.CAMERA_ERROR, AppState.PRINTER_ERROR} and event.kind is AppEventType.RETRY:
            return AppState.STARTUP
        if self._state is AppState.STARTUP:
            return {
                AppEventType.STARTUP_READY: AppState.IDLE,
                AppEventType.CAMERA_FAILURE: AppState.CAMERA_ERROR,
                AppEventType.PRINTER_FAILURE: AppState.PRINTER_ERROR,
            }.get(event.kind)
        if self._state is AppState.IDLE:
            return {
                AppEventType.GREETING_STARTED: AppState.GREETING_HELD,
                AppEventType.CAMERA_FAILURE: AppState.CAMERA_ERROR,
                AppEventType.PRINTER_FAILURE: AppState.PRINTER_ERROR,
            }.get(event.kind)
        if self._state is AppState.GREETING_HELD:
            return {
                AppEventType.GREETING_LOST: AppState.IDLE,
                AppEventType.HOLD_MET: AppState.COUNTDOWN,
                AppEventType.CAMERA_FAILURE: AppState.CAMERA_ERROR,
                AppEventType.PRINTER_FAILURE: AppState.PRINTER_ERROR,
            }.get(event.kind)
        if self._state is AppState.COUNTDOWN:
            return {
                AppEventType.CANCEL: AppState.IDLE,
                AppEventType.COUNTDOWN_FINISHED: AppState.PROCESSING,
                AppEventType.CAMERA_FAILURE: AppState.CAMERA_ERROR,
                AppEventType.PRINTER_FAILURE: AppState.PRINTER_ERROR,
            }.get(event.kind)
        if self._state is AppState.PROCESSING:
            return {
                AppEventType.PRINT_SUBMITTED: AppState.PRINTING,
                AppEventType.PROCESSING_FAILED: AppState.PROCESSING_ERROR,
                AppEventType.PRINTER_FAILURE: AppState.PRINTER_ERROR,
            }.get(event.kind)
        if self._state is AppState.PRINTING:
            return {
                AppEventType.PRINT_COMPLETED: AppState.IDLE,
                AppEventType.PRINTER_FAILURE: AppState.PRINTER_ERROR,
            }.get(event.kind)
        if self._state is AppState.PROCESSING_ERROR and event.kind is AppEventType.ACKNOWLEDGE:
            return AppState.IDLE
        return None

    def countdown_finished(self, now_monotonic_s: float) -> bool:
        return self._state is AppState.COUNTDOWN and (now_monotonic_s - self._state_since) >= self._countdown_seconds

    def snapshot(self, now_monotonic_s: float, greeting_elapsed_s: float = 0.0) -> AppSnapshot:
        countdown_value: int | None = None
        if self._state is AppState.COUNTDOWN:
            elapsed = max(0.0, now_monotonic_s - self._state_since)
            countdown_value = max(1, math.ceil(self._countdown_seconds - elapsed))
        message = self._message_override or _MESSAGES[self._state]
        return AppSnapshot(
            state=self._state,
            state_since_monotonic_s=self._state_since,
            message=message,
            job_id=self._job_id,
            greeting_elapsed_s=greeting_elapsed_s,
            countdown_value=countdown_value,
        )

