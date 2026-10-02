from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from uuid import uuid4

from PIL import Image

from el_bienvenidor.composition.layout import CardLayout
from el_bienvenidor.config import PrintSettings, StorageSettings
from el_bienvenidor.core.events import JobEventType
from el_bienvenidor.domain.models import CardData, CaptureRequest, FaceCrop, FrameId, FramePacket, JobId
from el_bienvenidor.printer.queue_monitor import NoopQueueMonitor
from el_bienvenidor.printer.win_printer import DryRunPrintBackend
from el_bienvenidor.services.job_worker import JobWorker
from el_bienvenidor.vision.face_detector import FaceCropPolicy


class FakeFaceDetector:
    def crop_primary_face(self, frame: FramePacket, policy: FaceCropPolicy) -> FaceCrop:
        return FaceCrop(Image.new("RGB", (600, 800), (10, 20, 30)), (0, 0, 600, 800), 0.99)

    def close(self) -> None:
        return None


class JobWorkerDryRunTests(unittest.TestCase):
    def test_worker_creates_card_and_completes_without_real_printer(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = StorageSettings(root / "jobs", retention_hours=24)
            worker = JobWorker(
                face_detector=FakeFaceDetector(),
                face_policy=FaceCropPolicy(0.8, 0.65, 50),
                layout=CardLayout(),
                storage=settings,
                printer=DryRunPrintBackend(),
                monitor=NoopQueueMonitor(),
                print_settings=PrintSettings(minimum_printing_message_seconds=0.0),
            )
            job_id = JobId(uuid4())
            request = CaptureRequest(
                job_id,
                FramePacket(FrameId(1), 0.0, None, (1280, 720)),
                0.0,
                CardData("Bienvenido", None, datetime.now(timezone.utc), "TEST"),
            )
            worker.start()
            try:
                worker.submit(request)
                deadline = time.monotonic() + 3.0
                events = []
                while time.monotonic() < deadline:
                    events.extend(worker.poll_events())
                    if any(event.kind is JobEventType.PRINT_COMPLETED for event in events):
                        break
                    time.sleep(0.02)
                self.assertIn(JobEventType.CARD_COMPOSED, [event.kind for event in events])
                self.assertIn(JobEventType.PRINT_SUBMITTED, [event.kind for event in events])
                self.assertIn(JobEventType.PRINT_COMPLETED, [event.kind for event in events])
                self.assertTrue((settings.jobs_directory / str(job_id) / "card.png").is_file())
            finally:
                worker.stop(timeout_s=1.0)


if __name__ == "__main__":
    unittest.main()

