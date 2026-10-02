"""Relojes intercambiables para producción y pruebas."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    def __init__(self, initial_s: float = 0.0) -> None:
        self._now_s = initial_s

    def monotonic(self) -> float:
        return self._now_s

    def advance(self, seconds: float) -> None:
        self._now_s += seconds

