from __future__ import annotations

import unittest

from el_bienvenidor.config import VisionSettings
from el_bienvenidor.vision.pose_detector import Landmark, PoseLandmarks, is_salute


class PoseRuleTests(unittest.TestCase):
    def test_same_side_wrist_over_shoulder_is_salute(self) -> None:
        landmarks = PoseLandmarks(
            left_wrist=Landmark(0.4, 0.20, 0.9, 0.9),
            left_shoulder=Landmark(0.4, 0.40, 0.9, 0.9),
            right_wrist=None,
            right_shoulder=None,
        )
        self.assertTrue(is_salute(landmarks, VisionSettings()).salute_detected)

    def test_low_visibility_is_not_salute(self) -> None:
        landmarks = PoseLandmarks(
            left_wrist=Landmark(0.4, 0.20, 0.4, 0.4),
            left_shoulder=Landmark(0.4, 0.40, 0.9, 0.9),
            right_wrist=None,
            right_shoulder=None,
        )
        self.assertFalse(is_salute(landmarks, VisionSettings()).salute_detected)

    def test_zero_visibility_is_not_salute(self) -> None:
        landmarks = PoseLandmarks(
            left_wrist=Landmark(0.4, 0.20, 0.0, 0.0),
            left_shoulder=Landmark(0.4, 0.40, 0.9, 0.9),
            right_wrist=None,
            right_shoulder=None,
        )
        self.assertFalse(is_salute(landmarks, VisionSettings()).salute_detected)

    def test_index_fingertip_over_shoulder_is_salute(self) -> None:
        landmarks = PoseLandmarks(
            left_wrist=Landmark(0.4, 0.42, 0.9, 0.9),
            left_shoulder=Landmark(0.4, 0.40, 0.9, 0.9),
            right_wrist=None,
            right_shoulder=None,
            left_tips=(Landmark(0.45, 0.18, 0.9, 0.9),),
        )
        self.assertTrue(is_salute(landmarks, VisionSettings()).salute_detected)


if __name__ == "__main__":
    unittest.main()

