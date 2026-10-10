"""Composición de dependencias y ciclo principal de Kippu."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
import sys
from time import sleep
from typing import Any
from uuid import uuid4

from el_bienvenidor.camera.camera_service import CameraService, OpenCVCameraService
from el_bienvenidor.composition.layout import default_layout
from el_bienvenidor.config import AppSettings
from el_bienvenidor.core.clock import Clock, SystemClock
from el_bienvenidor.core.events import AppEvent, AppEventType, JobEventType
from el_bienvenidor.core.state_manager import StateManager
from el_bienvenidor.domain.errors import CameraError, ConfigurationError, KippuError, PrinterError
from el_bienvenidor.domain.models import AppState, CardData, CaptureRequest, FaceCrop, FrameId, FramePacket, GestureObservation, JobId, LandmarkMap, PrinterHealth
from el_bienvenidor.printer.cups_printer import CupsPrinter
from el_bienvenidor.printer.cups_queue_monitor import CupsQueueMonitor
from el_bienvenidor.printer.queue_monitor import NoopQueueMonitor, PrintMonitor, WindowsQueueMonitor
from el_bienvenidor.printer.win_printer import DryRunPrintBackend, PrintBackend, WindowsPrinter
from el_bienvenidor.services.job_worker import JobWorker
from el_bienvenidor.ui.fullscreen_view import FullscreenView, HeadlessView, OpenCVFullscreenView, UserCommand
from el_bienvenidor.ui.guest_form import GuestIntake, prompt_guest_card
from el_bienvenidor.vision.face_detector import FaceCropPolicy, FaceDetector, MediaPipeFaceDetector
from el_bienvenidor.vision.gesture_gate import GestureGate
from el_bienvenidor.vision.opencv_detectors import OpenCVFaceDetector, OpenCVPoseDetector, cpu_has_avx
from el_bienvenidor.vision.pose_detector import MediaPipePoseDetector, PoseDetector

LOGGER = logging.getLogger(__name__)


class SimulatedCamera:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._open = False
        self._frame_id = 0

    def open(self) -> Any:
        from el_bienvenidor.domain.models import CameraProbe
        self._open = True
        return CameraProbe(0, "simulated", (1280, 720), 30.0, True, "Cámara simulada")

    def read(self) -> FramePacket | None:
        if not self._open:
            return None
        self._frame_id += 1
        return FramePacket(FrameId(self._frame_id), self._clock.monotonic(), None, (1280, 720))

    def is_open(self) -> bool:
        return self._open

    def release(self) -> None:
        self._open = False


class SimulatedPoseDetector:
    """Mantiene saludo: permite verificar el recorrido completo sin hardware."""

    def observe(self, frame: FramePacket) -> GestureObservation:
        return GestureObservation(True, (0.5, 0.2), (0.5, 0.5), 1.0, "Saludo simulado")

    def landmark_map(self) -> LandmarkMap | None:
        return None

    def close(self) -> None:
        return None


class SimulatedFaceDetector:
    def crop_primary_face(self, frame: FramePacket, policy: FaceCropPolicy) -> FaceCrop:
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (720, 960), (184, 204, 213))
        draw = ImageDraw.Draw(image)
        draw.ellipse((190, 110, 530, 540), fill=(222, 180, 150))
        return FaceCrop(image, (0, 0, 720, 960), 1.0)

    def close(self) -> None:
        return None


@dataclass
class Application:
    settings: AppSettings
    clock: Clock
    state_manager: StateManager
    camera: CameraService
    pose_detector: PoseDetector
    gesture_gate: GestureGate
    worker: JobWorker
    printer: PrintBackend
    view: FullscreenView
    error_acknowledge_seconds: float = 3.0
    headless: bool = False
    _last_frame: FramePacket | None = None
    _last_landmark_map: LandmarkMap | None = None
    _guest: GuestIntake | None = None
    _needs_guest_intake: bool = True
    _consecutive_read_failures: int = 0
    _camera_retry_attempts: int = 0
    _next_camera_retry_s: float = 0.0
    _running: bool = False
    _shutdown_complete: bool = False

    def run(self, max_ticks: int | None = None) -> int:
        self._running = True
        self.worker.start()
        if not self.headless and self._needs_guest_intake:
            self._guest = prompt_guest_card(
                self.settings.ui,
                headline=self.settings.ui.card_headline,
                initial=self._guest,
                force_default=False,
            )
            self._needs_guest_intake = False
        self.view.open()
        ticks = 0
        try:
            while self._running and self.state_manager.state is not AppState.STOPPED:
                now = self.clock.monotonic()
                self._process_commands(now)
                self._ensure_started(now)
                self._consume_job_events(now)
                self._collect_guest_if_needed()
                self._tick_camera_and_vision(now)
                self._acknowledge_temporary_errors(now)
                landmarks = self._last_landmark_map if self.settings.ui.show_landmarks else None
                guest_name = self._guest.guest_name if self._guest else None
                self.view.render(
                    self.state_manager.snapshot(now, self.gesture_gate.state.elapsed(now), guest_name=guest_name),
                    self._last_frame,
                    landmarks,
                )
                ticks += 1
                if max_ticks is not None and ticks >= max_ticks:
                    break
                sleep(0.01)
        except KeyboardInterrupt:
            LOGGER.info("Cierre solicitado por teclado")
        finally:
            self.shutdown()
        return 0

    def shutdown(self) -> None:
        if self._shutdown_complete:
            return
        self._running = False
        self._shutdown_complete = True
        self.worker.stop(timeout_s=5.0)
        self.pose_detector.close()
        self.camera.release()
        self.view.close()
        if self.state_manager.state is not AppState.STOPPED:
            self.state_manager.dispatch(AppEvent(AppEventType.STOP), self.clock.monotonic())

    def _collect_guest_if_needed(self) -> None:
        if not self._needs_guest_intake or self.state_manager.state is not AppState.IDLE:
            return
        self.view.close()
        self._guest = prompt_guest_card(
            self.settings.ui,
            headline=self.settings.ui.card_headline,
            initial=self._guest,
            force_default=self.headless,
        )
        self.view.open()
        self._needs_guest_intake = False
        LOGGER.info(
            "Datos de carnet listos",
            extra={
                "event": "guest_intake",
                "guest_name": self._guest.guest_name,
                "organization": self._guest.organization or "",
                "role": self._guest.role or "",
            },
        )

    def _process_commands(self, now: float) -> None:
        for command in self.view.poll_commands():
            if command is UserCommand.QUIT:
                self._running = False
            elif command is UserCommand.CANCEL:
                self.state_manager.dispatch(AppEvent(AppEventType.CANCEL), now)
                self.gesture_gate.reset()
            elif command is UserCommand.RETRY and self.state_manager.state in {AppState.CAMERA_ERROR, AppState.PRINTER_ERROR, AppState.PROCESSING_ERROR}:
                self.state_manager.dispatch(AppEvent(AppEventType.RETRY), now)
            elif command is UserCommand.EDIT_GUEST and self.state_manager.state is AppState.IDLE:
                self._needs_guest_intake = True
            elif command is UserCommand.TRIGGER and self.state_manager.state in {AppState.IDLE, AppState.GREETING_HELD}:
                self.state_manager.dispatch(AppEvent(AppEventType.HOLD_MET), now)
                self.gesture_gate.reset()

    def _ensure_started(self, now: float) -> None:
        state = self.state_manager.state
        if state is AppState.CAMERA_ERROR and now < self._next_camera_retry_s:
            return
        if state is AppState.CAMERA_ERROR:
            self.state_manager.dispatch(AppEvent(AppEventType.RETRY), now)
            state = self.state_manager.state
        if state is not AppState.STARTUP:
            return
        try:
            camera_probe = self.camera.open()
            LOGGER.info(camera_probe.detail, extra={"event": "camera_probe"})
        except CameraError as error:
            self._camera_failed(now, str(error))
            return
        try:
            printer_probe = self.printer.probe()
            if printer_probe.health is not PrinterHealth.READY:
                raise PrinterError(printer_probe.detail)
            LOGGER.info(printer_probe.detail, extra={"event": "printer_probe"})
        except PrinterError as error:
            self.state_manager.dispatch(AppEvent(AppEventType.PRINTER_FAILURE, message=str(error)), now)
            return
        self._consecutive_read_failures = 0
        self._camera_retry_attempts = 0
        self.state_manager.dispatch(AppEvent(AppEventType.STARTUP_READY), now)

    def _tick_camera_and_vision(self, now: float) -> None:
        state = self.state_manager.state
        if state not in {AppState.IDLE, AppState.GREETING_HELD, AppState.COUNTDOWN}:
            return
        if self._needs_guest_intake:
            return
        frame = self.camera.read()
        if frame is None:
            self._consecutive_read_failures += 1
            if self._consecutive_read_failures >= self.settings.camera.read_failure_threshold:
                self._camera_failed(now, "La cámara dejó de entregar frames.")
            return
        self._consecutive_read_failures = 0
        self._last_frame = frame
        if state in {AppState.IDLE, AppState.GREETING_HELD, AppState.COUNTDOWN}:
            observation = self.pose_detector.observe(frame)
            self._last_landmark_map = self.pose_detector.landmark_map()
            if state in {AppState.IDLE, AppState.GREETING_HELD}:
                gate_state = self.gesture_gate.update(observation, now)
                if state is AppState.IDLE and observation.salute_detected:
                    self.state_manager.dispatch(AppEvent(AppEventType.GREETING_STARTED), now)
                elif state is AppState.GREETING_HELD and gate_state.active_since_monotonic_s is None:
                    self.state_manager.dispatch(AppEvent(AppEventType.GREETING_LOST), now)
                elif state is AppState.GREETING_HELD and gate_state.ready:
                    self.state_manager.dispatch(AppEvent(AppEventType.HOLD_MET), now)
                    self.gesture_gate.reset()
        if self.state_manager.countdown_finished(now):
            self._request_capture(now)

    def _request_capture(self, now: float) -> None:
        if self._last_frame is None:
            self._camera_failed(now, "No existe un frame válido para capturar.")
            return
        image = self._last_frame.image_bgr
        if image is not None and hasattr(image, "copy"):
            image = image.copy()
            if self.settings.camera.capture_mirrored:
                image = image[:, ::-1].copy()
        frame = replace(self._last_frame, image_bgr=image, captured_monotonic_s=now)
        uuid = uuid4()
        job_id = JobId(uuid)
        guest = self._guest or GuestIntake("VISITANTE")
        request = CaptureRequest(
            job_id=job_id,
            frame=frame,
            requested_monotonic_s=now,
            metadata=CardData(
                headline=self.settings.ui.card_headline,
                guest_name=guest.guest_name,
                issued_at=datetime.now(timezone.utc),
                serial=uuid.hex[:8].upper(),
                organization=guest.organization,
                role=guest.role,
            ),
        )
        self.state_manager.dispatch(AppEvent(AppEventType.COUNTDOWN_FINISHED, job_id=job_id), now)
        try:
            self.worker.submit(request)
        except RuntimeError as error:
            self.state_manager.dispatch(AppEvent(AppEventType.PROCESSING_FAILED, job_id=job_id, message=str(error)), now)

    def _consume_job_events(self, now: float) -> None:
        for event in self.worker.poll_events():
            if event.kind is JobEventType.PRINT_SUBMITTED:
                self.state_manager.dispatch(AppEvent(AppEventType.PRINT_SUBMITTED, event.job_id, event.message), now)
            elif event.kind is JobEventType.PRINT_COMPLETED:
                self.state_manager.dispatch(AppEvent(AppEventType.PRINT_COMPLETED, event.job_id, event.message), now)
                if self.settings.ui.ask_guest_each_job:
                    self._guest = None
                    self._needs_guest_intake = True
            elif event.kind is JobEventType.PROCESSING_FAILED:
                self.state_manager.dispatch(AppEvent(AppEventType.PROCESSING_FAILED, event.job_id, event.message), now)
            elif event.kind is JobEventType.PRINTER_FAILED:
                self.state_manager.dispatch(AppEvent(AppEventType.PRINTER_FAILURE, event.job_id, event.message), now)

    def _camera_failed(self, now: float, message: str) -> None:
        self.camera.release()
        self.gesture_gate.reset()
        self._last_landmark_map = None
        self._camera_retry_attempts += 1
        delay_index = min(len(self.settings.camera.reconnect_delays_seconds) - 1, self._camera_retry_attempts - 1)
        self._next_camera_retry_s = now + self.settings.camera.reconnect_delays_seconds[delay_index]
        self.state_manager.dispatch(AppEvent(AppEventType.CAMERA_FAILURE, message=message), now)

    def _acknowledge_temporary_errors(self, now: float) -> None:
        if self.state_manager.state is AppState.PROCESSING_ERROR and now - self.state_manager.state_since_monotonic_s >= self.error_acknowledge_seconds:
            self.state_manager.dispatch(AppEvent(AppEventType.ACKNOWLEDGE), now)
            if self.settings.ui.ask_guest_each_job:
                self._needs_guest_intake = True


def build_application(settings: AppSettings, *, real_printer: bool = False, simulate: bool = False, headless: bool = False) -> Application:
    """Ensambla Kippu. `real_printer` es opt-in incluso si el TOML fue alterado."""
    clock = SystemClock()
    layout = default_layout(settings.project_root)
    if real_printer and layout.template_path is None:
        raise ConfigurationError("La impresión real requiere assets/templates/carnet_base.png con el diseño aprobado.")
    if simulate:
        camera: CameraService = SimulatedCamera(clock)
        pose_detector: PoseDetector = SimulatedPoseDetector()
        face_detector: FaceDetector = SimulatedFaceDetector()
        printer: PrintBackend = DryRunPrintBackend()
        monitor: PrintMonitor = NoopQueueMonitor()
    else:
        camera = OpenCVCameraService(settings.camera)
        models_dir = settings.project_root / "assets" / "models"
        use_opencv = (
            settings.vision.backend == "opencv"
            or (settings.vision.backend == "auto" and not cpu_has_avx())
        )
        if use_opencv:
            LOGGER.info("Inicializando detectores de visión OpenCV (compatible con CPUs sin AVX)...")
            pose_detector = OpenCVPoseDetector(settings.vision, models_dir)
            face_detector = OpenCVFaceDetector(settings.vision, models_dir)
        else:
            try:
                pose_detector = MediaPipePoseDetector(settings.vision, models_dir)
                face_detector = MediaPipeFaceDetector(settings.vision, models_dir)
            except Exception as error:
                LOGGER.warning("Fallo al inicializar MediaPipe (%s). Usando respaldo OpenCV.", error)
                pose_detector = OpenCVPoseDetector(settings.vision, models_dir)
                face_detector = OpenCVFaceDetector(settings.vision, models_dir)
        if real_printer:
            if sys.platform == "win32":
                printer = WindowsPrinter(settings.printing)
                monitor = WindowsQueueMonitor(settings.printing)
            elif sys.platform.startswith("linux"):
                printer = CupsPrinter(settings.printing)
                monitor = CupsQueueMonitor(settings.printing)
            else:
                raise ConfigurationError("La impresión real está disponible en Windows y Linux con CUPS.")
        else:
            printer = DryRunPrintBackend()
            monitor = NoopQueueMonitor()
    worker = JobWorker(
        face_detector=face_detector,
        face_policy=FaceCropPolicy.from_settings(settings.vision),
        layout=layout,
        storage=settings.storage,
        printer=printer,
        monitor=monitor,
        print_settings=settings.printing,
    )
    return Application(
        settings=settings,
        clock=clock,
        state_manager=StateManager(),
        camera=camera,
        pose_detector=pose_detector,
        gesture_gate=GestureGate(settings.vision.salute_hold_seconds),
        worker=worker,
        printer=printer,
        view=HeadlessView() if headless else OpenCVFullscreenView(settings.ui),
        headless=headless,
    )


def run_diagnostic(settings: AppSettings, real_printer: bool) -> int:
    """Comprueba dispositivos sin capturar ni enviar tarjeta."""
    application = build_application(settings, real_printer=real_printer, headless=True)
    try:
        camera_probe = application.camera.open()
        print(f"CAMERA: {camera_probe.resolution[0]}x{camera_probe.resolution[1]} @ {camera_probe.fps:.1f} FPS — {camera_probe.detail}")
        printer_probe = application.printer.probe()
        print(f"PRINTER: {printer_probe.printer_name} — {printer_probe.health.value} — {printer_probe.detail}")
        print(
            f"PLATFORM: {sys.platform} — landmarks={'on' if settings.ui.show_landmarks else 'off'} "
            f"— guest_form={'on' if settings.ui.guest_form_enabled else 'off'}"
        )
        return 0
    except KippuError as error:
        print(f"DIAGNOSTIC ERROR: {error}")
        return 2
    finally:
        application.camera.release()
        application.pose_detector.close()
        application.worker.stop(timeout_s=0.1)
