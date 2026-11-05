"""Tests unitarios de la pantalla post-foto (draw_print_screen)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import time


class PrintOverlayTests(unittest.TestCase):
    """Verifica que draw_print_screen produce un frame RGB válido para cada estado."""

    def _make_black_frame(self, h: int = 720, w: int = 1280):
        """Frame BGR negro de NumPy para usar como base."""
        import numpy as np
        return np.zeros((h, w, 3), dtype=np.uint8)

    def _make_snapshot(self, state, card_path=None, print_detail="", guest_name="VISITANTE"):
        from el_bienvenidor.domain.models import AppSnapshot, AppState
        return AppSnapshot(
            state=state,
            state_since_monotonic_s=0.0,
            message="Test message",
            card_path=card_path,
            print_detail=print_detail,
            guest_name=guest_name,
        )

    def test_processing_state_produces_valid_frame(self):
        """PROCESSING sin carnet disponible devuelve frame del mismo tamaño."""
        from el_bienvenidor.domain.models import AppState
        from el_bienvenidor.ui.print_overlay import draw_print_screen

        frame = self._make_black_frame()
        snapshot = self._make_snapshot(AppState.PROCESSING)
        result = draw_print_screen(frame, snapshot)

        self.assertEqual(result.shape, frame.shape)
        self.assertEqual(result.dtype.name, "uint8")

    def test_printing_state_produces_valid_frame(self):
        """PRINTING con detalle de impresora devuelve frame del mismo tamaño."""
        from el_bienvenidor.domain.models import AppState
        from el_bienvenidor.ui.print_overlay import draw_print_screen

        frame = self._make_black_frame()
        snapshot = self._make_snapshot(
            AppState.PRINTING,
            print_detail="HP DeskJet 2700 — job #42 en cola",
        )
        result = draw_print_screen(
            frame,
            snapshot,
            allow_inkless=True,
            printer_name="HP DeskJet 2700",
        )

        self.assertEqual(result.shape, frame.shape)

    def test_allow_inkless_flag_does_not_crash(self):
        """El aviso de modo sin tinta se renderiza sin excepciones."""
        from el_bienvenidor.domain.models import AppState
        from el_bienvenidor.ui.print_overlay import draw_print_screen

        frame = self._make_black_frame()
        snapshot = self._make_snapshot(AppState.PRINTING)
        # No debe lanzar excepción
        result = draw_print_screen(frame, snapshot, allow_inkless=True)
        self.assertIsNotNone(result)

    def test_card_path_missing_file_does_not_crash(self):
        """Si card_path apunta a un archivo inexistente se usa el placeholder."""
        from el_bienvenidor.domain.models import AppState
        from el_bienvenidor.ui.print_overlay import draw_print_screen

        frame = self._make_black_frame()
        snapshot = self._make_snapshot(
            AppState.PRINTING,
            card_path=Path("/tmp/nonexistent_card_kippu.png"),
        )
        result = draw_print_screen(frame, snapshot)
        self.assertEqual(result.shape, frame.shape)

    def test_card_path_valid_png_renders_thumbnail(self):
        """Si card_path es un PNG válido, se renderiza la miniatura sin errores."""
        import tempfile
        from el_bienvenidor.domain.models import AppState
        from el_bienvenidor.ui.print_overlay import draw_print_screen
        from PIL import Image

        # Creamos un PNG pequeño de prueba
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            img = Image.new("RGB", (1181, 1772), color=(22, 42, 62))
            img.save(tmp_path)

            frame = self._make_black_frame()
            snapshot = self._make_snapshot(AppState.PRINTING, card_path=tmp_path)
            result = draw_print_screen(frame, snapshot)
            self.assertEqual(result.shape, frame.shape)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_snapshot_carries_card_path_and_print_detail(self):
        """AppSnapshot almacena card_path y print_detail correctamente."""
        from el_bienvenidor.domain.models import AppSnapshot, AppState

        p = Path("/tmp/card.png")
        snap = AppSnapshot(
            state=AppState.PRINTING,
            state_since_monotonic_s=1.0,
            message="Enviando…",
            card_path=p,
            print_detail="HP DeskJet — job #7",
        )
        self.assertEqual(snap.card_path, p)
        self.assertEqual(snap.print_detail, "HP DeskJet — job #7")

    def test_state_manager_snapshot_propagates_card_path(self):
        """StateManager.snapshot() pasa card_path y print_detail al AppSnapshot."""
        from el_bienvenidor.core.state_manager import StateManager
        from el_bienvenidor.core.events import AppEvent, AppEventType
        from el_bienvenidor.domain.models import AppState

        sm = StateManager()
        sm.dispatch(AppEvent(AppEventType.STARTUP_READY), 0.0)
        sm.dispatch(AppEvent(AppEventType.HOLD_MET), 1.0)
        sm.dispatch(AppEvent(AppEventType.COUNTDOWN_FINISHED), 2.0)
        sm.dispatch(AppEvent(AppEventType.PRINT_SUBMITTED, message="CUPS ok"), 3.0)

        p = Path("/tmp/card.png")
        snap = sm.snapshot(3.5, card_path=p, print_detail="CUPS ok")

        self.assertEqual(snap.state, AppState.PRINTING)
        self.assertEqual(snap.card_path, p)
        self.assertEqual(snap.print_detail, "CUPS ok")

    def test_different_frame_sizes_work(self):
        """La función acepta frames de distinto tamaño sin errores."""
        from el_bienvenidor.domain.models import AppState
        from el_bienvenidor.ui.print_overlay import draw_print_screen
        import numpy as np

        for h, w in [(480, 640), (720, 1280), (1080, 1920)]:
            with self.subTest(size=(h, w)):
                frame = np.zeros((h, w, 3), dtype=np.uint8)
                snapshot = self._make_snapshot(AppState.PROCESSING)
                result = draw_print_screen(frame, snapshot)
                self.assertEqual(result.shape, (h, w, 3))


if __name__ == "__main__":
    unittest.main()

