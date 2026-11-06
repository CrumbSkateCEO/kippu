from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from el_bienvenidor.camera.ptz_tracker import (
    NoopPtzTracker,
    OnvifPtzTracker,
    PtzSettings,
    create_ptz_tracker,
    resolve_ptz_credentials,
)


class ResolvePtzCredentialsTests(unittest.TestCase):
    def test_extracts_from_rtsp_url(self) -> None:
        settings = PtzSettings(enabled=True)
        url = "rtsp://frww:nc6dd3@192.168.1.10:554/live/ch0"
        resolved = resolve_ptz_credentials(settings, ip_url=url)
        self.assertEqual(resolved.host, "192.168.1.10")
        self.assertEqual(resolved.user, "frww")
        self.assertEqual(resolved.password, "nc6dd3")

    def test_preserves_explicit_config(self) -> None:
        settings = PtzSettings(
            enabled=True,
            host="192.168.1.50",
            user="custom_user",
            password="custom_password",
        )
        url = "rtsp://frww:nc6dd3@192.168.1.10:554/live/ch0"
        resolved = resolve_ptz_credentials(settings, ip_url=url)
        self.assertEqual(resolved.host, "192.168.1.50")
        self.assertEqual(resolved.user, "custom_user")
        self.assertEqual(resolved.password, "custom_password")


class PtzTrackerFactoryTests(unittest.TestCase):
    def test_returns_noop_when_disabled(self) -> None:
        settings = PtzSettings(enabled=False, host="192.168.1.10")
        tracker = create_ptz_tracker(settings)
        self.assertIsInstance(tracker, NoopPtzTracker)
        self.assertFalse(tracker.is_connected)
        self.assertTrue(tracker.connect())
        tracker.update(300, 200, 640, 480)
        tracker.clear_target()
        tracker.stop()

    def test_returns_onvif_when_enabled(self) -> None:
        settings = PtzSettings(enabled=True, host="192.168.1.10")
        tracker = create_ptz_tracker(settings)
        self.assertIsInstance(tracker, OnvifPtzTracker)


class OnvifPtzTrackerLogicTests(unittest.TestCase):
    def test_deadzone_results_in_zero_velocity(self) -> None:
        settings = PtzSettings(
            enabled=True,
            host="192.168.1.10",
            deadzone_x=0.1,
            deadzone_y=0.1,
            pan_speed=0.4,
            tilt_speed=0.3,
        )
        tracker = OnvifPtzTracker(settings)
        tracker._connected = True
        tracker._running = True

        # Center is (320, 240); (330, 245) is inside 10% deadzone
        tracker.update(330, 245, 640, 480)
        with tracker._lock:
            self.assertEqual(tracker._pending, (0.0, 0.0))

    def test_proportional_velocity_outside_deadzone(self) -> None:
        settings = PtzSettings(
            enabled=True,
            host="192.168.1.10",
            deadzone_x=0.08,
            deadzone_y=0.08,
            pan_speed=0.5,
            tilt_speed=0.4,
            invert_pan=False,
            invert_tilt=False,
        )
        tracker = OnvifPtzTracker(settings)
        tracker._connected = True
        tracker._running = True

        # Target at right (640, 240) -> positive pan, zero tilt
        tracker.update(640, 240, 640, 480)
        with tracker._lock:
            pan, tilt = tracker._pending
            self.assertAlmostEqual(pan, 0.5)
            self.assertAlmostEqual(tilt, 0.0)

        # Target at top left (0, 0) -> negative pan, positive tilt (+y in ONVIF is up)
        tracker.update(0, 0, 640, 480)
        with tracker._lock:
            pan, tilt = tracker._pending
            self.assertAlmostEqual(pan, -0.5)
            self.assertAlmostEqual(tilt, 0.4)

    def test_invert_pan_and_tilt(self) -> None:
        settings = PtzSettings(
            enabled=True,
            host="192.168.1.10",
            deadzone_x=0.05,
            deadzone_y=0.05,
            pan_speed=0.5,
            tilt_speed=0.5,
            invert_pan=True,
            invert_tilt=True,
        )
        tracker = OnvifPtzTracker(settings)
        tracker._connected = True
        tracker._running = True

        # Target at right (600, 240); with invert_pan, pan should be negative
        tracker.update(600, 240, 640, 480)
        with tracker._lock:
            pan, tilt = tracker._pending
            self.assertLess(pan, 0.0)

    def test_clear_target(self) -> None:
        settings = PtzSettings(enabled=True, host="192.168.1.10")
        tracker = OnvifPtzTracker(settings)
        tracker._connected = True
        tracker._running = True

        tracker.update(600, 400, 640, 480)
        tracker.clear_target()
        with tracker._lock:
            self.assertEqual(tracker._pending, (0.0, 0.0))


class OnvifPtzTrackerMockIntegrationTests(unittest.TestCase):
    @patch("socket.create_connection")
    @patch("onvif.ONVIFCamera")
    def test_connect_and_movement(self, mock_cam_cls: MagicMock, mock_socket: MagicMock) -> None:
        mock_socket.return_value.__enter__.return_value = MagicMock()

        mock_cam = MagicMock()
        mock_cam_cls.return_value = mock_cam
        mock_media = MagicMock()
        mock_ptz = MagicMock()
        mock_cam.create_media_service.return_value = mock_media
        mock_cam.create_ptz_service.return_value = mock_ptz

        profile_mock = MagicMock()
        profile_mock.token = "profile_main"
        mock_media.GetProfiles.return_value = [profile_mock]

        settings = PtzSettings(
            enabled=True,
            host="192.168.1.10",
            port=8899,
            command_rate_hz=50.0,
            pan_speed=0.3,
        )
        tracker = OnvifPtzTracker(settings)
        success = tracker.connect()
        self.assertTrue(success)
        self.assertTrue(tracker.is_connected)
        self.assertEqual(tracker._profile_token, "profile_main")

        # Update target
        tracker.update(600, 240, 640, 480)
        time.sleep(0.08)
        self.assertTrue(mock_ptz.create_type.called or mock_ptz.ContinuousMove.called)

        # Clear target
        tracker.clear_target()
        time.sleep(0.08)

        tracker.stop()
        self.assertFalse(tracker.is_connected)


if __name__ == "__main__":
    unittest.main()

