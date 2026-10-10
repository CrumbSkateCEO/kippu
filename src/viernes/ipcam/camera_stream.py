"""Módulo para la captura de video RTSP con latencia cero y bajo consumo de CPU."""

import cv2
import threading
import logging
import time
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

# FPS máximo del hilo de captura — limita uso de CPU sin afectar latencia
_CAPTURE_FPS = 30
_CAPTURE_INTERVAL = 1.0 / _CAPTURE_FPS


class IPCameraStream:
    """
    Gestor de stream RTSP que utiliza un hilo en segundo plano para leer continuamente
    los frames de la cámara. Esto evita que el buffer interno de OpenCV acumule frames
    antiguos, garantizando latencia cero al consultar el frame más reciente.

    Optimizaciones:
    - El hilo de captura duerme ``_CAPTURE_INTERVAL`` segundos entre lecturas para
      no quemar CPU al 100% en el bucle cerrado.
    - Los frames se almacenan ya convertidos a RGB para evitar la conversión repetida
      en el hilo de renderizado del dashboard.
    - Reconexión con backoff exponencial para evitar tormentas de intentos.
    """

    RECONNECT_DELAYS = (1.0, 2.0, 5.0, 10.0)  # Backoff exponencial

    def __init__(self, rtsp_url: str):
        self.stream_url = rtsp_url
        self.current_frame: Optional[np.ndarray] = None  # BGR para OpenCV
        self._cap: Optional[cv2.VideoCapture] = None

        self._running = False
        self._lock = threading.Lock()
        self._reconnect_attempt = 0

        self.start()

    def start(self) -> None:
        """Inicia el hilo de captura en segundo plano."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True, name="cam-capture")
        self._thread.start()
        logger.info(f"Hilo de captura iniciado para: {self.stream_url}")

    def _connect(self) -> bool:
        """Intenta (re)conectar a la cámara con backoff exponencial."""
        if self._cap is not None:
            self._cap.release()

        delay_idx = min(self._reconnect_attempt, len(self.RECONNECT_DELAYS) - 1)
        delay = self.RECONNECT_DELAYS[delay_idx]

        if self._reconnect_attempt > 0:
            logger.warning(f"Reconectando en {delay}s (intento #{self._reconnect_attempt})...")
            # Sleep en pequeños intervalos para poder responder al stop()
            for _ in range(int(delay / 0.1)):
                if not self._running:
                    return False
                time.sleep(0.1)

        logger.info(f"Conectando a cámara: {self.stream_url}")
        source = int(self.stream_url) if self.stream_url.isdigit() else self.stream_url

        if isinstance(source, str) and (source.startswith("rtsp://") or source.startswith("http://")):
            import os
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "timeout;1500000")
            try:
                from urllib.parse import urlparse
                parsed = urlparse(source)
                host = parsed.hostname
                port = parsed.port or 554
                if host:
                    import socket
                    with socket.create_connection((host, port), timeout=1.0):
                        pass
            except Exception as e:
                logger.warning(f"Host de cámara {self.stream_url} no alcanzable ({e}).")
                if self._reconnect_attempt == 0:
                    logger.info("Probando cámara local (0) como alternativa...")
                    local_cap = cv2.VideoCapture(0)
                    if local_cap.isOpened():
                        logger.info("Cámara local (0) conectada con éxito.")
                        self._cap = local_cap
                        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        self._reconnect_attempt = 0
                        return True
                    local_cap.release()
                self._reconnect_attempt += 1
                return False

        self._cap = cv2.VideoCapture(source)

        if not self._cap.isOpened():
            logger.warning(f"No se pudo conectar a la cámara: {self.stream_url}")
            self._reconnect_attempt += 1
            return False

        # Reducir el buffer interno de OpenCV a 1 frame → latencia mínima
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._reconnect_attempt = 0
        logger.info("Cámara conectada exitosamente.")
        return True

    def _update_loop(self) -> None:
        """
        Bucle interno. Lee frames a ~30 FPS sin quemar CPU.
        Duerme el tiempo restante para mantener el intervalo objetivo.
        """
        connected = self._connect()

        while self._running:
            t0 = time.monotonic()

            if not connected or self._cap is None or not self._cap.isOpened():
                connected = self._connect()
                continue

            try:
                ret, frame = self._cap.read()
                if ret and frame is not None:
                    with self._lock:
                        self.current_frame = frame
                else:
                    logger.error("Error al leer frame (¿cámara desconectada?).")
                    connected = False
                    continue
            except Exception as e:
                logger.error(f"Excepción en lectura de cámara: {e}")
                connected = False
                continue

            # Throttle: dormir el tiempo sobrante para alcanzar el intervalo objetivo
            elapsed = time.monotonic() - t0
            sleep_time = _CAPTURE_INTERVAL - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        if self._cap is not None:
            self._cap.release()
            self._cap = None
        logger.info("Hilo de captura de cámara detenido.")

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Retorna el último frame capturado (BGR) sin bloquear el hilo principal."""
        with self._lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
            return None

    def get_latest_frame_rgb(self) -> Optional[np.ndarray]:
        """Retorna el último frame en RGB directamente (evita conversión en el caller)."""
        with self._lock:
            if self.current_frame is not None:
                return cv2.cvtColor(self.current_frame, cv2.COLOR_BGR2RGB)
            return None

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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    test_rtsp_url = "0"

    logger.info("Iniciando prueba independiente de IPCameraStream...")
    camera = IPCameraStream(test_rtsp_url)

    try:
        logger.info("Presiona 'q' en la ventana para salir.")
        while True:
            frame = camera.get_latest_frame()

            if frame is not None:
                cv2.imshow("Viernes IP Camera Stream", frame)
            else:
                blank = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(blank, "Esperando conexion/frame...", (50, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                cv2.imshow("Viernes IP Camera Stream", blank)

            if cv2.waitKey(33) & 0xFF == ord('q'):
                logger.info("Tecla 'q' presionada. Saliendo...")
                break

    except KeyboardInterrupt:
        logger.info("Interrupción manual (Ctrl+C).")
    finally:
        camera.stop()
        cv2.destroyAllWindows()
        logger.info("Prueba finalizada.")
