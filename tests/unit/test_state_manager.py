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
    def test_idle_manual_trigger_transitions_to_countdown(self) -> None:
        manager = StateManager()
        manager.dispatch(AppEvent(AppEventType.STARTUP_READY), 0.0)
        self.assertEqual(manager.state, AppState.IDLE)
        # Disparo manual con Espacio/Enter desde IDLE
        self.assertEqual(manager.dispatch(AppEvent(AppEventType.HOLD_MET), 1.0).current, AppState.COUNTDOWN)

    def test_processing_error_allows_immediate_retry(self) -> None:
        manager = StateManager()
        manager.dispatch(AppEvent(AppEventType.STARTUP_READY), 0.0)
        manager.dispatch(AppEvent(AppEventType.HOLD_MET), 1.0)
        manager.dispatch(AppEvent(AppEventType.COUNTDOWN_FINISHED), 4.0)
        manager.dispatch(AppEvent(AppEventType.PROCESSING_FAILED), 4.1)
        self.assertEqual(manager.state, AppState.PROCESSING_ERROR)
        self.assertEqual(manager.dispatch(AppEvent(AppEventType.RETRY), 4.2).current, AppState.IDLE)

    def test_snapshot_includes_guest_name(self) -> None:
        manager = StateManager()
        manager.dispatch(AppEvent(AppEventType.STARTUP_READY), 0.0)
        snap = manager.snapshot(1.0, guest_name="Ada Lovelace")
        self.assertEqual(snap.guest_name, "Ada Lovelace")


if __name__ == "__main__":
    unittest.main()

