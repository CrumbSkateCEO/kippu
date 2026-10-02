from __future__ import annotations

import unittest

from el_bienvenidor.core.events import AppEvent, AppEventType
from el_bienvenidor.core.state_manager import StateManager
from el_bienvenidor.domain.models import AppState


class StateManagerTests(unittest.TestCase):
    def test_happy_path_returns_to_idle(self) -> None:
        manager = StateManager()
        self.assertEqual(manager.dispatch(AppEvent(AppEventType.STARTUP_READY), 0.0).current, AppState.IDLE)
        self.assertEqual(manager.dispatch(AppEvent(AppEventType.GREETING_STARTED), 1.0).current, AppState.GREETING_HELD)
        self.assertEqual(manager.dispatch(AppEvent(AppEventType.HOLD_MET), 2.5).current, AppState.COUNTDOWN)
        self.assertFalse(manager.countdown_finished(5.49))
        self.assertTrue(manager.countdown_finished(5.5))
        self.assertEqual(manager.dispatch(AppEvent(AppEventType.COUNTDOWN_FINISHED), 5.5).current, AppState.PROCESSING)
        self.assertEqual(manager.dispatch(AppEvent(AppEventType.PRINT_SUBMITTED), 6.0).current, AppState.PRINTING)
        self.assertEqual(manager.dispatch(AppEvent(AppEventType.PRINT_COMPLETED), 7.0).current, AppState.IDLE)

    def test_invalid_transition_does_not_mutate_state(self) -> None:
        manager = StateManager()
        transition = manager.dispatch(AppEvent(AppEventType.PRINT_COMPLETED), 1.0)
        self.assertFalse(transition.accepted)
        self.assertEqual(manager.state, AppState.STARTUP)

    def test_cancel_countdown_and_processing_error_recovery(self) -> None:
        manager = StateManager()
        manager.dispatch(AppEvent(AppEventType.STARTUP_READY), 0.0)
        manager.dispatch(AppEvent(AppEventType.GREETING_STARTED), 1.0)
        manager.dispatch(AppEvent(AppEventType.HOLD_MET), 2.5)
        self.assertEqual(manager.dispatch(AppEvent(AppEventType.CANCEL), 3.0).current, AppState.IDLE)
        manager.dispatch(AppEvent(AppEventType.GREETING_STARTED), 4.0)
        manager.dispatch(AppEvent(AppEventType.HOLD_MET), 5.5)
        manager.dispatch(AppEvent(AppEventType.COUNTDOWN_FINISHED), 8.5)
        self.assertEqual(manager.dispatch(AppEvent(AppEventType.PROCESSING_FAILED), 8.6).current, AppState.PROCESSING_ERROR)
        self.assertEqual(manager.dispatch(AppEvent(AppEventType.ACKNOWLEDGE), 11.6).current, AppState.IDLE)


if __name__ == "__main__":
    unittest.main()

