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

    Optimizaciones anti-lag (v2)
    ----------------------------
    - **grab() + retrieve()** en vez de read(): ``grab()`` solo decodifica
      los metadatos del paquete de red, ``retrieve()`` decodifica la imagen.
      Para descartar frames atrasados, hacemos múltiples ``grab()`` sin
      ``retrieve()`` — esto es ~10× más rápido que ``read()`` completo.
    - **Sin .copy()**: los frames se almacenan por referencia. El hilo de Qt
      solo copia cuando necesita crear el QImage (no aquí).
    - **Conversión BGR→RGB lazy**: solo se convierte cuando se pide con
      ``get_latest_frame_rgb()``, no en cada captura.
    - **Buffer de OpenCV a 1**: ``CAP_PROP_BUFFERSIZE = 1`` minimiza los
      frames acumulados internamente por FFmpeg/OpenCV.
    - **Sin sleep en el loop**: ``grab()`` bloquea hasta que llega el próximo
      frame de la red → el hilo se auto-regula al FPS del stream.

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

        # Frame actual — escrito por el hilo de captura, leído desde Qt/brain.
        # Protegido por _lock. Se almacena SIN copiar para máxima velocidad.
        self._frame_bgr: Optional[np.ndarray] = None
        self._frame_rgb: Optional[np.ndarray] = None  # Cache lazy (se invalida al llegar frame nuevo)

        self._cap: Optional[cv2.VideoCapture] = None

        self._running = False
        self._lock = threading.Lock()
        self._reconnect_attempt = 0

        # Propiedades para compatibilidad con código existente
        self.current_frame: Optional[np.ndarray] = None

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
            self._frame_bgr = None
            self._frame_rgb = None
            self.current_frame = None

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
    # Bucle de captura — ANTI-LAG v2
    # ------------------------------------------------------------------

    def _update_loop(self) -> None:
        """
        Bucle interno. Lee frames tan rápido como el stream los entregue.

        **Estrategia anti-lag (v2)**:
        Usa ``grab()`` + ``retrieve()`` en lugar de ``read()``. La diferencia
        clave es que ``grab()`` solo obtiene el paquete comprimido del buffer
        sin decodificarlo, mientras que ``retrieve()`` hace la decodificación.

        Cuando ``drop_frames`` está activo:
        1. Se hacen N ``grab()`` para vaciar el buffer interno (cada uno es
           ultra-rápido, ~0.1ms vs ~5-15ms de un ``read()`` completo).
        2. Solo se hace ``retrieve()`` del ÚLTIMO frame grabbeado → siempre
           se decodifica el frame más reciente, no uno atrasado.

        Esto elimina el lag acumulado sin el costo de decodificar frames
        que se van a descartar de todos modos.
        """
        connected = self._connect()

        while self._running:
            if not connected or self._cap is None or not self._cap.isOpened():
                connected = self._connect()
                continue

            try:
                if self.drop_frames:
                    # --- Estrategia grab+retrieve simple ---
                    # Con las opciones de baja latencia (fflags=nobuffer,
                    # CAP_PROP_BUFFERSIZE=1) el socket RTSP ya entrega un
                    # solo frame por ciclo. Un grab() extra-loop bloqueaba
                    # hasta 5 intervalos de red (~200 ms) estrangulando a
                    # ~5 FPS.  Un único grab+retrieve es suficiente.
                    if self._cap.grab():
                        ret, frame = self._cap.retrieve()
                    else:
                        ret, frame = False, None
                else:
                    ret, frame = self._cap.read()

                if ret and frame is not None:
                    with self._lock:
                        self._frame_bgr = frame  # Sin .copy() → zero-copy
                        self._frame_rgb = None   # Invalidar cache RGB
                        self.current_frame = frame  # Compat con código viejo
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
        """
        Retorna el último frame (BGR) sin bloquear el hilo principal.

        Nota: retorna una referencia directa al array del frame (sin copy).
        Si el consumidor necesita mutar el array, debe hacer .copy() él mismo.
        """
        with self._lock:
            return self._frame_bgr

    def get_latest_frame_rgb(self) -> Optional[np.ndarray]:
        """
        Retorna el último frame en RGB con cache lazy.

        La conversión BGR→RGB solo se ejecuta cuando el frame cambia
        (una vez por frame nuevo), no en cada llamada.
        """
        with self._lock:
            if self._frame_bgr is None:
                return None
            # Cache: solo convertir si el frame cambió (cache invalidada)
            if self._frame_rgb is None:
                self._frame_rgb = cv2.cvtColor(self._frame_bgr, cv2.COLOR_BGR2RGB)
            return self._frame_rgb


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
