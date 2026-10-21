from __future__ import annotations

from pathlib import Path
import unittest

import cv2
import numpy as np

from el_bienvenidor.config import VisionSettings
from el_bienvenidor.domain.models import FrameId, FramePacket
from el_bienvenidor.vision.opencv_detectors import OpenCVPoseDetector


class OpenCVPoseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = VisionSettings()
        models_dir = Path("assets/models")
        self.detector = OpenCVPoseDetector(self.settings, models_dir)

    def test_face_and_neck_only_does_not_trigger_salute(self) -> None:
        fx, fy, fw, fh = 500, 200, 160, 200
        self.detector._face_detector.detect_raw = lambda _img: [(fx, fy, fw, fh, 0.95, None)]

        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        skin_color = (160, 180, 230)

        # Draw face, ears, neck, shoulders (no hand raised)
        cv2.rectangle(img, (fx, fy), (fx + fw, fy + fh), skin_color, -1)
        cv2.rectangle(img, (fx - 30, fy + 40), (fx, fy + 120), skin_color, -1)
        cv2.rectangle(img, (fx + fw, fy + 40), (fx + fw + 30, fy + 120), skin_color, -1)
        cv2.rectangle(img, (fx + 20, fy + fh), (fx + fw - 20, fy + fh + 80), skin_color, -1)
        cv2.rectangle(img, (fx - 100, fy + fh + 60), (fx + fw + 100, fy + fh + 200), (50, 50, 50), -1)

        pkt = FramePacket(FrameId(1), 0.0, img, (1280, 720))
        obs = self.detector.observe(pkt)
        self.assertFalse(obs.salute_detected)

    def test_hand_raised_beside_head_triggers_salute(self) -> None:
        fx, fy, fw, fh = 500, 200, 160, 200
        self.detector._face_detector.detect_raw = lambda _img: [(fx, fy, fw, fh, 0.95, None)]

        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        skin_color = (160, 180, 230)

        # Draw face
        cv2.rectangle(img, (fx, fy), (fx + fw, fy + fh), skin_color, -1)
        # Draw hand raised beside head on the right
        cv2.rectangle(img, (750, 150), (830, 260), skin_color, -1)

        pkt = FramePacket(FrameId(2), 0.1, img, (1280, 720))
        obs = self.detector.observe(pkt)
        self.assertTrue(obs.salute_detected)
        self.assertIsNotNone(obs.wrist)
        self.assertIn("right_hand", obs.reason)


if __name__ == "__main__":
    unittest.main()
