"""Un único worker que compone e imprime sin bloquear la vista previa."""

from __future__ import annotations

import logging
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread
import time

from el_bienvenidor.composition.card_composer import compose_card
from el_bienvenidor.composition.layout import CardLayout
from el_bienvenidor.config import PrintSettings, StorageSettings
from el_bienvenidor.core.events import JobEvent, JobEventType
from el_bienvenidor.domain.errors import FaceValidationError, KippuError, PrinterError
from el_bienvenidor.domain.models import CaptureRequest
from el_bienvenidor.infra.storage import job_directory
from el_bienvenidor.printer.queue_monitor import PrintMonitor
from el_bienvenidor.printer.win_printer import PrintBackend
from el_bienvenidor.vision.face_detector import FaceCropPolicy, FaceDetector

LOGGER = logging.getLogger(__name__)


class JobWorker:
    def __init__(
        self,
        face_detector: FaceDetector,
        face_policy: FaceCropPolicy,
        layout: CardLayout,
        storage: StorageSettings,
        printer: PrintBackend,
        monitor: PrintMonitor,
        print_settings: PrintSettings,
    ) -> None:
        self._face_detector = face_detector
        self._face_policy = face_policy
        self._layout = layout
        self._storage = storage
        self._printer = printer
        self._monitor = monitor
        self._print_settings = print_settings
        self._requests: Queue[CaptureRequest | None] = Queue(maxsize=1)
        self._events: Queue[JobEvent] = Queue()
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._run, name="kippu-job-worker", daemon=True)
        self._thread.start()

    def submit(self, request: CaptureRequest) -> None:
        try:
            self._requests.put_nowait(request)
        except Full as error:
            raise RuntimeError("Kippu ya tiene un trabajo en curso.") from error

    def poll_events(self) -> list[JobEvent]:
        events: list[JobEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except Empty:
                return events

    def stop(self, timeout_s: float) -> None:
        self._stop.set()
        try:
            self._requests.put_nowait(None)
        except Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
        self._face_detector.close()

    def _emit(self, event_type: JobEventType, request: CaptureRequest, message: str = "") -> None:
        self._events.put(JobEvent(event_type, request.job_id, message))

    def _run(self) -> None:
        while not self._stop.is_set():
            request = self._requests.get()
            if request is None:
                return
            self._process(request)

    def _process(self, request: CaptureRequest) -> None:
        self._emit(JobEventType.PROCESSING_STARTED, request)
        try:
            crop = self._face_detector.crop_primary_face(request.frame, self._face_policy)
            output = job_directory(request.job_id, self._storage) / "card.png"
            artifact = compose_card(crop, request.metadata, self._layout, output, request.job_id)
            self._emit(JobEventType.CARD_COMPOSED, request, str(artifact.png_path))
            started = time.monotonic()
            receipt = self._printer.submit(artifact)
            self._emit(JobEventType.PRINT_SUBMITTED, request, receipt.detail)
            receipt = self._monitor.monitor_submission(receipt)
            elapsed = time.monotonic() - started
            if elapsed < self._print_settings.minimum_printing_message_seconds:
                time.sleep(self._print_settings.minimum_printing_message_seconds - elapsed)
            if receipt.disposition.value in {"queue_error", "unknown_after_submit"}:
                self._emit(JobEventType.PRINTER_FAILED, request, receipt.detail)
            else:
                self._emit(JobEventType.PRINT_COMPLETED, request, receipt.detail)
        except FaceValidationError as error:
            self._emit(JobEventType.PROCESSING_FAILED, request, str(error))
        except PrinterError as error:
            self._emit(JobEventType.PRINTER_FAILED, request, str(error))
        except KippuError as error:
            self._emit(JobEventType.PROCESSING_FAILED, request, str(error))
        except Exception as error:  # El worker no puede derribar la UI.
            LOGGER.exception("Fallo inesperado de trabajo", extra={"job_id": str(request.job_id)})
            self._emit(JobEventType.PROCESSING_FAILED, request, "Error interno al preparar el carnet.")

