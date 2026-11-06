from __future__ import annotations

import subprocess
import tempfile
import time
import unittest

from el_bienvenidor.camera.camera_service import (
    OpenCVCameraService,
    PyAVIPCameraService,
    create_camera_service,
)
from el_bienvenidor.config import CameraSettings
from el_bienvenidor.domain.errors import CameraUnavailableError


class CameraServiceFactoryTests(unittest.TestCase):
    def test_factory_creates_opencv_for_webcam(self) -> None:
        settings = CameraSettings(source_type="webcam", index=0)
        service = create_camera_service(settings)
        self.assertIsInstance(service, OpenCVCameraService)

    def test_factory_creates_pyav_for_ip(self) -> None:
        settings = CameraSettings(
            source_type="ip",
            ip_url="rtsp://frww:nc6dd3@192.168.1.10:554/live/ch0",
        )
        service = create_camera_service(settings)
        self.assertIsInstance(service, PyAVIPCameraService)


class PyAVIPCameraServiceTests(unittest.TestCase):
    def test_build_options_contains_low_delay_flags(self) -> None:
        settings = CameraSettings(
            source_type="ip",
            ip_url="rtsp://example.com/live",
            rtsp_transport="tcp",
            low_delay=True,
        )
        service = PyAVIPCameraService(settings)
        options = service._build_options()
        self.assertEqual(options["rtsp_transport"], "tcp")
        self.assertEqual(options["fflags"], "nobuffer")
        self.assertEqual(options["flags"], "low_delay")

    def test_open_missing_url_raises_error(self) -> None:
        settings = CameraSettings(source_type="ip", ip_url="")
        service = PyAVIPCameraService(settings)
        with self.assertRaises(CameraUnavailableError):
            service.open()

    def test_open_unreachable_host_raises_error(self) -> None:
        # Port 1 is reserved and should be refused immediately on localhost
        settings = CameraSettings(
            source_type="ip",
            ip_url="rtsp://127.0.0.1:1/live",
            reconnect_delays_seconds=(0.1,),
        )
        service = PyAVIPCameraService(settings)
        with self.assertRaises(CameraUnavailableError):
            service.open()

    def test_capture_and_read_from_stream(self) -> None:
        # Start a local ffmpeg TCP stream
        server = subprocess.Popen(
            [
                "ffmpeg",
                "-re",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=320x240:rate=25",
                "-c:v",
                "mpeg2video",
                "-f",
                "mpegts",
                "tcp://127.0.0.1:9989?listen",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.4)
        try:
            settings = CameraSettings(
                source_type="ip",
                ip_url="tcp://127.0.0.1:9989",
                low_delay=True,
            )
            service = PyAVIPCameraService(settings)
            probe = service.open()
            self.assertTrue(service.is_open())
            self.assertEqual(probe.backend, "pyav")
            self.assertEqual(probe.resolution, (320, 240))

            # Allow worker thread to fetch at least one frame
            time.sleep(0.1)
            packet = service.read()
            self.assertIsNotNone(packet)
            assert packet is not None
            self.assertEqual(packet.source_size, (320, 240))
            self.assertEqual(packet.image_bgr.shape, (240, 320, 3))

            service.release()
            self.assertFalse(service.is_open())
            self.assertIsNone(service.read())
        finally:
            server.kill()
            server.wait()


if __name__ == "__main__":
    unittest.main()
