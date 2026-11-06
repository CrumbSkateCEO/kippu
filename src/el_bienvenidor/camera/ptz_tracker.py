"""Seguimiento de rostro mediante cámara IP motorizada (ONVIF PTZ).

Controla el movimiento Pan/Tilt de la cámara IP para mantener el rostro
de la persona centrado en la toma utilizando los landmarks de MediaPipe.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import socket
import threading
import time
from typing import Any
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PtzSettings:
    """Configuración del seguimiento facial PTZ ONVIF."""

    enabled: bool = False
    host: str = ""
    port: int = 8899
    user: str = ""
    password: str = ""
    profile_token: str = ""
    pan_speed: float = 0.30
    tilt_speed: float = 0.25
    deadzone_x: float = 0.08
    deadzone_y: float = 0.08
    command_rate_hz: float = 10.0
    invert_pan: bool = False
    invert_tilt: bool = False


class OnvifPtzTracker:
    """Controlador de seguimiento facial en tiempo real vía ONVIF ContinuousMove."""

    def __init__(self, settings: PtzSettings) -> None:
        self._settings = settings
        self._camera: Any = None
        self._ptz_service: Any = None
        self._media_service: Any = None
        self._profile_token: str = settings.profile_token
        self._active_port: int = settings.port
        self._lock = threading.Lock()
        self._pending: tuple[float, float] = (0.0, 0.0)
        self._is_moving: bool = False
        self._running: bool = False
        self._connected: bool = False
        self._thread: threading.Thread | None = None
        self._min_interval = 1.0 / max(1.0, settings.command_rate_hz)

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        """Conecta a la cámara ONVIF con comprobación previa de socket."""
        try:
            from onvif import ONVIFCamera
        except ModuleNotFoundError:
            LOGGER.warning("onvif-zeep no está instalado. Movimiento PTZ desactivado.")
            return False

        host = self._settings.host.strip()
        if not host:
            LOGGER.debug("No se configuró host para PTZ.")
            return False

        # Intentar conectar al puerto configurado y fallback a puertos comunes (8899, 80, 8000)
        candidate_ports = [self._settings.port]
        for fallback in (8899, 80, 8000):
            if fallback not in candidate_ports:
                candidate_ports.append(fallback)

        found_port: int | None = None
        for port in candidate_ports:
            try:
                with socket.create_connection((host, port), timeout=0.8):
                    found_port = port
                    break
            except Exception:
                continue

        if found_port is None:
            LOGGER.warning(
                "PTZ: no se pudo alcanzar el puerto ONVIF de la cámara en %s (probados: %s).",
                host,
                candidate_ports,
            )
            return False

        self._active_port = found_port
        try:
            LOGGER.info("PTZ: conectando a cámara ONVIF en %s:%d...", host, self._active_port)
            cam = ONVIFCamera(
                host=host,
                port=self._active_port,
                user=self._settings.user,
                passwd=self._settings.password,
            )
            media = cam.create_media_service()
            ptz = cam.create_ptz_service()

            if not self._profile_token:
                profiles = media.GetProfiles()
                if not profiles:
                    LOGGER.warning("PTZ: la cámara no devolvió perfiles de medios.")
                    return False
                first = profiles[0]
                token = getattr(first, "token", getattr(first, "_token", ""))
                self._profile_token = str(token)

            self._camera = cam
            self._media_service = media
            self._ptz_service = ptz
            self._connected = True
            LOGGER.info("PTZ listo. Perfil activo: %s", self._profile_token)

            # Detener movimiento previo residual
            self._send_stop()

            # Iniciar hilo de despacho
            self._running = True
            self._thread = threading.Thread(
                target=self._sender_loop,
                daemon=True,
                name="onvif-ptz-worker",
            )
            self._thread.start()
            return True

        except Exception as error:
            LOGGER.warning("Error conectando a cámara ONVIF (%s:%d): %s", host, self._active_port, error)
            self._connected = False
            return False

    def update(
        self,
        face_cx: float,
        face_cy: float,
        frame_w: int,
        frame_h: int,
    ) -> None:
        """Actualiza el objetivo según la posición del rostro respecto al centro del cuadro."""
        if not self._connected or not self._running or frame_w <= 0 or frame_h <= 0:
            return

        half_w = frame_w / 2.0
        half_h = frame_h / 2.0

        # Normalizar error entre -1.0 y 1.0
        err_x = (face_cx - half_w) / half_w  # positivo = cara a la derecha
        err_y = (face_cy - half_h) / half_h  # positivo = cara abajo

        # Comprobar zona muerta (deadzone)
        if abs(err_x) <= self._settings.deadzone_x and abs(err_y) <= self._settings.deadzone_y:
            pan_vel = 0.0
            tilt_vel = 0.0
        else:
            # Control proporcional saturado
            pan_raw = err_x / max(0.1, 1.0 - self._settings.deadzone_x) if abs(err_x) > self._settings.deadzone_x else 0.0
            tilt_raw = err_y / max(0.1, 1.0 - self._settings.deadzone_y) if abs(err_y) > self._settings.deadzone_y else 0.0

            # En ONVIF: +X = derecha, +Y = arriba (inverso a coordenadas de imagen donde Y crece hacia abajo)
            pan_vel = float(max(-1.0, min(1.0, pan_raw))) * self._settings.pan_speed
            tilt_vel = float(max(-1.0, min(1.0, -tilt_raw))) * self._settings.tilt_speed

            if self._settings.invert_pan:
                pan_vel = -pan_vel
            if self._settings.invert_tilt:
                tilt_vel = -tilt_vel

        with self._lock:
            self._pending = (pan_vel, tilt_vel)

    def clear_target(self) -> None:
        """Indica que no hay objetivo actual para detener el movimiento."""
        with self._lock:
            self._pending = (0.0, 0.0)

    def stop(self) -> None:
        """Detiene el hilo de control y envía Stop a la cámara."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        if self._connected:
            self._send_stop()
        self._connected = False
        self._is_moving = False

    def _sender_loop(self) -> None:
        while self._running:
            t0 = time.monotonic()
            with self._lock:
                pan_vel, tilt_vel = self._pending

            is_zero = (abs(pan_vel) < 0.01 and abs(tilt_vel) < 0.01)
            if is_zero:
                if self._is_moving:
                    self._send_stop()
                    self._is_moving = False
            else:
                self._send_move(pan_vel, tilt_vel)
                self._is_moving = True

            elapsed = time.monotonic() - t0
            sleep_time = self._min_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _send_move(self, pan: float, tilt: float) -> None:
        if self._ptz_service is None or not self._profile_token:
            return
        try:
            req = self._ptz_service.create_type("ContinuousMove")
            req.ProfileToken = self._profile_token
            req.Velocity = {
                "PanTilt": {"x": pan, "y": tilt},
                "Zoom": {"x": 0.0},
            }
            self._ptz_service.ContinuousMove(req)
        except Exception:
            try:
                self._ptz_service.ContinuousMove({
                    "ProfileToken": self._profile_token,
                    "Velocity": {"PanTilt": {"x": pan, "y": tilt}},
                })
            except Exception as error:
                LOGGER.debug("Error enviando ContinuousMove PTZ: %s", error)

    def _send_stop(self) -> None:
        if self._ptz_service is None or not self._profile_token:
            return
        try:
            req = self._ptz_service.create_type("Stop")
            req.ProfileToken = self._profile_token
            req.PanTilt = True
            req.Zoom = False
            self._ptz_service.Stop(req)
        except Exception:
            try:
                self._ptz_service.Stop({"ProfileToken": self._profile_token})
            except Exception as error:
                LOGGER.debug("Error enviando Stop PTZ: %s", error)


class NoopPtzTracker:
    """Implementación nula cuando el PTZ está desactivado."""

    @property
    def is_connected(self) -> bool:
        return False

    def connect(self) -> bool:
        return True

    def update(self, face_cx: float, face_cy: float, frame_w: int, frame_h: int) -> None:
        pass

    def clear_target(self) -> None:
        pass

    def stop(self) -> None:
        pass


def resolve_ptz_credentials(settings: PtzSettings, ip_url: str = "") -> PtzSettings:
    """Completa host, usuario y contraseña desde ip_url si no fueron configurados manualmente."""
    host = settings.host
    user = settings.user
    password = settings.password

    if (not host or not user or not password) and ip_url:
        try:
            parsed = urlsplit(ip_url)
            if not host and parsed.hostname:
                host = parsed.hostname
            if not user and parsed.username:
                user = parsed.username
            if not password and parsed.password:
                password = parsed.password
        except Exception:
            pass

    return PtzSettings(
        enabled=settings.enabled,
        host=host,
        port=settings.port,
        user=user,
        password=password,
        profile_token=settings.profile_token,
        pan_speed=settings.pan_speed,
        tilt_speed=settings.tilt_speed,
        deadzone_x=settings.deadzone_x,
        deadzone_y=settings.deadzone_y,
        command_rate_hz=settings.command_rate_hz,
        invert_pan=settings.invert_pan,
        invert_tilt=settings.invert_tilt,
    )


def create_ptz_tracker(settings: PtzSettings, ip_url: str = "") -> OnvifPtzTracker | NoopPtzTracker:
    """Crea el tracker adecuado según la configuración."""
    resolved = resolve_ptz_credentials(settings, ip_url)
    if resolved.enabled and resolved.host:
        return OnvifPtzTracker(resolved)
    return NoopPtzTracker()

