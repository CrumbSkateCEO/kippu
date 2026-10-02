from __future__ import annotations

import unittest

from el_bienvenidor.domain.models import LandmarkLayer, LandmarkMap, LandmarkPoint


class LandmarkOverlayTests(unittest.TestCase):
    def test_draws_face_and_hand_vectors(self) -> None:
        try:
            import numpy as np
        except ModuleNotFoundError:
            self.skipTest("NumPy no está instalado en este entorno")
        from el_bienvenidor.ui.overlay import draw_landmark_map

        image = np.zeros((120, 160, 3), dtype=np.uint8)
        face = LandmarkLayer(
            "face",
            (LandmarkPoint(0.2, 0.2), LandmarkPoint(0.4, 0.2), LandmarkPoint(0.3, 0.4)),
            ((0, 1), (1, 2), (2, 0)),
        )
        hand = LandmarkLayer(
            "left_hand",
            (LandmarkPoint(0.7, 0.5), LandmarkPoint(0.8, 0.4)),
            ((0, 1),),
        )
        result = draw_landmark_map(image, LandmarkMap(face=face, left_hand=hand), mirrored=False)
        self.assertEqual(result.shape, image.shape)
        self.assertGreater(int(result.sum()), 0)

    def test_hud_does_not_cover_entire_frame(self) -> None:
        try:
            import numpy as np
        except ModuleNotFoundError:
            self.skipTest("NumPy no está instalado en este entorno")
        from el_bienvenidor.domain.models import AppSnapshot, AppState
        from el_bienvenidor.ui.overlay import draw_overlay

        image = np.full((240, 320, 3), 180, dtype=np.uint8)
        snapshot = AppSnapshot(AppState.IDLE, 0.0, "Levante una mano por encima del hombro")
        result = draw_overlay(image, snapshot)
        self.assertEqual(result.shape, image.shape)
        center = result[120, 160]
        self.assertGreater(int(center.mean()), 80)


if __name__ == "__main__":
    unittest.main()
