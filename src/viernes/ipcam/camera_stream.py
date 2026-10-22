"""Captura de video RTSP con latencia cero y opciones FFmpeg configurables."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _apply_ffmpeg_options(options_str: str) -> None:
    """
    Aplica opciones FFmpeg al proceso actual mediante la variable de entorno
    ``OPENCV_FFMPEG_CAPTURE_OPTIONS``.

    El formato esperado es ``clave;valor|clave;valor`` (separador ``|`` entre
    pares y ``;`` entre clave y valor), exactamente como lo espera OpenCV.

    Ejemplo:
        ``"rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|timeout;2000000"``
    """
    if not options_str:
        return
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = options_str
    logger.debug("OPENCV_FFMPEG_CAPTURE_OPTIONS = %s", options_str)


class IPCameraStream:
    """
    Gestor de stream RTSP que utiliza un hilo en segundo plano para leer
    continuamente los frames de la cámara evitando acumulación en el buffer.

    Parámetros FFmpeg de baja latencia
    ------------------------------------
    Se configuran vía ``ffmpeg_options`` (string ``clave;valor|clave;valor``):

    - ``rtsp_transport;tcp``       → usa TCP en lugar de UDP (más estable en LAN)
    - ``fflags;nobuffer``          → deshabilita el buffer de FFmpeg (latencia mínima)
    - ``flags;low_delay``          → activa el modo low-delay del decodificador
    - ``timeout;2000000``          → timeout de conexión en µs (2 s)
    - ``analyzeduration;100000``   → reduce el tiempo de análisis del stream
    - ``probesize;32``             → reduce el probesize (menos overhead inicial)

    Reconexión
    ----------
    Backoff exponencial configurable. El hilo puede responder a ``stop()``
    entre intentos (sleep fragmentado).
    """

    RECONNECT_DELAYS = (1.0, 2.0, 5.0, 10.0)  # Backoff exponencial en segundos

    def __init__(
        self,
        rtsp_url: str,
        ffmpeg_options: str = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|timeout;2000000|analyzeduration;100000|probesize;32",
        drop_frames: bool = True,
    ) -> None:
        """
        :param rtsp_url:        URL RTSP o índice de cámara local (e.g. ``"0"``).
        :param ffmpeg_options:  String de opciones FFmpeg para baja latencia.
        :param drop_frames:     Si es True, descarta frames si el decodificador
                                va retrasado (evita acumulación de lag).
        """
        self.stream_url = rtsp_url
        self.ffmpeg_options = ffmpeg_options
        self.drop_frames = drop_frames

        self.current_frame: Optional[np.ndarray] = None  # BGR
        self._current_frame_rgb: Optional[np.ndarray] = None  # RGB (pre-convertido en el hilo de captura)
        self._cap: Optional[cv2.VideoCapture] = None

        self._running = False
        self._lock = threading.Lock()
        self._reconnect_attempt = 0

        self.start()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inicia el hilo de captura en segundo plano."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._update_loop, daemon=True, name="cam-capture"
        )
        self._thread.start()
        logger.info("Hilo de captura iniciado para: %s", self.stream_url)

    def stop(self) -> None:
        """Detiene el hilo de lectura y libera los recursos de video."""
        if not self._running:
            return
        logger.info("Deteniendo stream de cámara...")
        self._running = False
        if threading.current_thread() is not self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        with self._lock:
            self.current_frame = None
            self._current_frame_rgb = None

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------

    def _is_rtsp_or_http(self, source: str) -> bool:
        return source.startswith(("rtsp://", "rtsps://", "http://", "https://"))

    def _probe_host(self, url: str) -> bool:
        """Comprueba si el host del stream es alcanzable (1 s timeout)."""
        try:
            from urllib.parse import urlparse
            import socket

            parsed = urlparse(url)
            host = parsed.hostname
            port = parsed.port or 554
            if host:
                with socket.create_connection((host, port), timeout=1.0):
                    pass
            return True
        except Exception as exc:
            logger.warning("Host no alcanzable (%s): %s", self.stream_url, exc)
            return False

    def _open_capture(self, source) -> cv2.VideoCapture:
        """Abre el VideoCapture con las opciones FFmpeg configuradas."""
        if isinstance(source, str) and self._is_rtsp_or_http(source):
            # Aplicar opciones FFmpeg ANTES de abrir el capture
            _apply_ffmpeg_options(self.ffmpeg_options)
            cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        else:
            cap = cv2.VideoCapture(source)

        if cap.isOpened():
            # Buffer interno de OpenCV a 1 frame → latencia mínima
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        return cap

    def _connect(self) -> bool:
        """Intenta (re)conectar a la cámara con backoff exponencial."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

        delay_idx = min(self._reconnect_attempt, len(self.RECONNECT_DELAYS) - 1)
        delay = self.RECONNECT_DELAYS[delay_idx]

        if self._reconnect_attempt > 0:
            logger.warning(
                "Reconectando en %.1fs (intento #%d)...", delay, self._reconnect_attempt
            )
            for _ in range(int(delay / 0.1)):
                if not self._running:
                    return False
                time.sleep(0.1)

        logger.info("Conectando a cámara: %s", self.stream_url)

        # Determinar la fuente (int para cámara local, str para URL)
        if isinstance(self.stream_url, str) and self.stream_url.isdigit():
            source = int(self.stream_url)
        else:
            source = self.stream_url

        # Para streams RTSP comprobar alcanzabilidad antes de abrir
        if isinstance(source, str) and self._is_rtsp_or_http(source):
            if not self._probe_host(source):
                if self._reconnect_attempt == 0:
                    # Fallback a cámara local en el primer intento
                    logger.info("Probando cámara local (0) como alternativa...")
                    fallback = cv2.VideoCapture(0)
                    if fallback.isOpened():
                        fallback.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        self._cap = fallback
                        self._reconnect_attempt = 0
                        logger.info("Cámara local (0) conectada.")
                        return True
                    fallback.release()
                self._reconnect_attempt += 1
                return False

        cap = self._open_capture(source)

        if not cap.isOpened():
            logger.warning("No se pudo abrir el stream: %s", self.stream_url)
            self._reconnect_attempt += 1
            return False

        self._cap = cap
        self._reconnect_attempt = 0
        logger.info("Cámara conectada exitosamente.")
        return True

    # ------------------------------------------------------------------
    # Bucle de captura
    # ------------------------------------------------------------------

    def _update_loop(self) -> None:
        """
        Bucle interno. Lee frames tan rápido como el stream los entregue.
        Con RTSP/FFmpeg, read() bloquea hasta que llega el próximo frame de la red,
        por lo que no necesita throttle adicional — agregar sleep solo acumula lag.
        Si ``drop_frames`` está activo, lee frames extra para llegar al más reciente.
        """
        connected = self._connect()

        while self._running:
            if not connected or self._cap is None or not self._cap.isOpened():
                connected = self._connect()
                continue

            try:
                ret, frame = self._cap.read()

                if ret and frame is not None:
                    if self.drop_frames:
                        # Vaciar el buffer interno leyendo frames adicionales sin guardarlos
                        # Esto descarta frames acumulados manteniendo el más reciente
                        for _ in range(3):
                            r, f = self._cap.read()
                            if r and f is not None:
                                frame = f
                            else:
                                break
                    # Convertir a RGB en el hilo de captura para no bloquear Qt
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    with self._lock:
                        self.current_frame = frame
                        self._current_frame_rgb = frame_rgb
                else:
                    logger.error("Error leyendo frame — posible desconexión.")
                    connected = False
                    continue

            except Exception as exc:
                logger.error("Excepción en lectura de cámara: %s", exc)
                connected = False
                continue

        if self._cap is not None:
            self._cap.release()
            self._cap = None
        logger.info("Hilo de captura de cámara detenido.")

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Retorna el último frame (BGR) sin bloquear el hilo principal."""
        with self._lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
            return None

    def get_latest_frame_rgb(self) -> Optional[np.ndarray]:
        """
        Retorna el último frame en RGB pre-convertido en el hilo de captura.
        No hace conversión en el hilo de Qt → sin lag en la UI.
        """
        with self._lock:
            if self._current_frame_rgb is not None:
                return self._current_frame_rgb.copy()
            return None


# ---------------------------------------------------------------------------
# Prueba standalone
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    url = sys.argv[1] if len(sys.argv) > 1 else "0"
    logger.info("Iniciando prueba de IPCameraStream con URL: %s", url)
    camera = IPCameraStream(url)

    try:
        logger.info("Presiona 'q' en la ventana para salir.")
        while True:
            frame = camera.get_latest_frame()
            if frame is not None:
                cv2.imshow("IPCameraStream — prueba", frame)
            else:
                blank = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(
                    blank,
                    "Sin señal...",
                    (50, 240),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (255, 255, 255),
                    2,
                )
                cv2.imshow("IPCameraStream — prueba", blank)

            if cv2.waitKey(33) & 0xFF == ord("q"):
                break
    except KeyboardInterrupt:
        logger.info("Interrupción manual (Ctrl+C).")
    finally:
        camera.stop()
        cv2.destroyAllWindows()
        logger.info("Prueba finalizada.")
