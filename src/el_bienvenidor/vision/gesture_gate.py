"""Filtro temporal puro para evitar activar por una pose de un solo frame."""

from __future__ import annotations

from dataclasses import dataclass

from el_bienvenidor.domain.models import GestureObservation

_MISS_GRACE_S = 0.35


@dataclass(frozen=True)
class GestureGateState:
    active_since_monotonic_s: float | None = None
    last_valid_monotonic_s: float | None = None
    ready: bool = False

    def elapsed(self, now_monotonic_s: float) -> float:
        return 0.0 if self.active_since_monotonic_s is None else max(0.0, now_monotonic_s - self.active_since_monotonic_s)


def update_gesture_gate(
    previous: GestureGateState,
    observation: GestureObservation,
    now_s: float,
    hold_s: float,
    miss_grace_s: float = _MISS_GRACE_S,
) -> GestureGateState:
    if observation.salute_detected:
        active_since = previous.active_since_monotonic_s if previous.active_since_monotonic_s is not None else now_s
        return GestureGateState(active_since, now_s, now_s - active_since >= hold_s)
    if (
        previous.active_since_monotonic_s is not None
        and previous.last_valid_monotonic_s is not None
        and now_s - previous.last_valid_monotonic_s <= miss_grace_s
    ):
        return previous
    return GestureGateState()


class GestureGate:
    def __init__(self, hold_seconds: float) -> None:
        self._hold_seconds = hold_seconds
        self._state = GestureGateState()

    @property
    def state(self) -> GestureGateState:
        return self._state

    def update(self, observation: GestureObservation, now_s: float) -> GestureGateState:
        self._state = update_gesture_gate(self._state, observation, now_s, self._hold_seconds)
        return self._state

    def reset(self) -> None:
        self._state = GestureGateState()
