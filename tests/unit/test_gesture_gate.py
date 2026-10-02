from __future__ import annotations

import unittest

from el_bienvenidor.domain.models import GestureObservation
from el_bienvenidor.vision.gesture_gate import GestureGate, GestureGateState, update_gesture_gate


VALID = GestureObservation(True, (0.5, 0.2), (0.5, 0.5), 0.9, "ok")
INVALID = GestureObservation(False, None, None, 0.0, "no")


class GestureGateTests(unittest.TestCase):
    def test_requires_continuous_duration(self) -> None:
        gate = GestureGate(1.5)
        self.assertFalse(gate.update(VALID, 10.0).ready)
        self.assertFalse(gate.update(VALID, 11.49).ready)
        self.assertTrue(gate.update(VALID, 11.5).ready)

    def test_invalid_observation_resets_elapsed_time(self) -> None:
        state = update_gesture_gate(GestureGateState(), VALID, 0.0, 1.5)
        state = update_gesture_gate(state, VALID, 1.0, 1.5)
        state = update_gesture_gate(state, INVALID, 1.5, 1.5)
        state = update_gesture_gate(state, VALID, 1.6, 1.5)
        self.assertFalse(state.ready)
        self.assertEqual(state.active_since_monotonic_s, 1.6)


if __name__ == "__main__":
    unittest.main()

