"""Motion tracker liviano para seguimiento de movimiento con PTZ.

Detecta movimiento en el frame usando diferencia de frames y calcula
la dirección dominante para que el PTZ la siga. No usa redes neuronales
ni MediaPipe — solo operaciones simples de OpenCV para máximo rendimiento.

Uso típico:
    tracker = MotionTracker(camera_stream, ptz_controller)
    tracker.start()   # Empieza a seguir movimiento automáticamente
    tracker.stop()    # Para el seguimiento
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional, TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from viernes.ipcam.camera_stream import IPCameraStream
    from viernes.ipcam.ptz_controller import PTZController

logger = logging.getLogger(__name__)


class MotionTracker:
    """
    Detector de movimiento liviano que envía comandos PTZ para seguir
    la zona con mayor actividad.

    Estrategia:
    1. Toma frames a intervalos regulares (configurable, default ~5 fps).
    2. Calcula la diferencia absoluta entre frame actual y anterior.
    3. Aplica threshold + erosión para eliminar ruido.
    4. Calcula el centroide de la zona con movimiento.
    5. Si el centroide está fuera de la "zona muerta" central, envía
       un comando PTZ proporcional para centrar al sujeto.

    La "zona muerta" evita jitter constante: solo se mueve cuando el
    movimiento está claramente descentrado (>25% del borde).
    """

    def __init__(
        self,
        camera_stream: "IPCameraStream",
        ptz_controller: "PTZController",
        *,
        check_interval: float = 0.2,    # Segundos entre chequeos (~5 fps)
        min_area: int = 500,             # Área mínima de contorno para considerar movimiento real
        dead_zone: float = 0.25,         # Fracción del frame que es "zona muerta" central (no mover)
        ptz_speed: float = 0.15,         # Velocidad PTZ suave para tracking
        ptz_duration: float = 0.25,      # Duración corta de cada micro-movimiento
        cooldown: float = 0.8,           # Segundos entre comandos PTZ para no saturar
    ):
        self.camera = camera_stream
        self.ptz = ptz_controller

        self.check_interval = check_interval
        self.min_area = min_area
        self.dead_zone = dead_zone
        self.ptz_speed = ptz_speed
        self.ptz_duration = ptz_duration
        self.cooldown = cooldown

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._prev_gray: Optional[np.ndarray] = None
        self._last_ptz_time = 0.0

        # Estado público para que el brain consulte
        self.is_tracking = False
        self.last_direction: Optional[str] = None

    def start(self) -> None:
        """Inicia el tracking en un hilo de fondo."""
        if self._running:
            logger.info("[TRACK] Ya está activo.")
            return
        self._running = True
        self._prev_gray = None
        self._thread = threading.Thread(
            target=self._track_loop, daemon=True, name="motion-tracker"
        )
        self._thread.start()
        self.is_tracking = True
        logger.info("[TRACK] Motion tracking iniciado.")

    def stop(self) -> None:
        """Detiene el tracking."""
        if not self._running:
            return
        self._running = False
        self.is_tracking = False
        self.last_direction = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("[TRACK] Motion tracking detenido.")

    def _track_loop(self) -> None:
        """Bucle de detección de movimiento."""
        while self._running:
            try:
                self._process_frame()
            except Exception as e:
                logger.error(f"[TRACK] Error en tracking: {e}")
            time.sleep(self.check_interval)

        self._prev_gray = None

    def _process_frame(self) -> None:
        """Procesa un frame para detectar movimiento y enviar comando PTZ."""
        frame = self.camera.get_latest_frame()
        if frame is None:
            return

        # Reducir resolución para procesamiento rápido
        small = cv2.resize(frame, (320, 240), interpolation=cv2.INTER_NEAREST)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            return

        # Diferencia absoluta entre frames
        delta = cv2.absdiff(self._prev_gray, gray)
        self._prev_gray = gray

        # Threshold para binarizar el movimiento
        _, thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)

        # Erosión + dilatación para eliminar ruido y unir regiones cercanas
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        thresh = cv2.erode(thresh, kernel, iterations=1)
        thresh = cv2.dilate(thresh, kernel, iterations=3)

        # Encontrar contornos de movimiento
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return

        # Filtrar contornos pequeños (ruido) y encontrar el más grande
        valid = [c for c in contours if cv2.contourArea(c) >= self.min_area]
        if not valid:
            return

        # Contorno con mayor área = objeto principal en movimiento
        largest = max(valid, key=cv2.contourArea)
        M = cv2.moments(largest)
        if M["m00"] == 0:
            return

        # Centroide del movimiento (en coordenadas del frame reducido 320×240)
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])

        # Normalizar a [-1, 1] donde (0,0) es el centro
        h, w = gray.shape
        norm_x = (cx / w) * 2 - 1  # -1 = izquierda, +1 = derecha
        norm_y = (cy / h) * 2 - 1  # -1 = arriba, +1 = abajo

        # ¿Está fuera de la zona muerta?
        dz = self.dead_zone
        if abs(norm_x) < dz and abs(norm_y) < dz:
            return  # Movimiento centrado, no hacer nada

        # Cooldown: no enviar comandos PTZ demasiado seguido
        now = time.time()
        if (now - self._last_ptz_time) < self.cooldown:
            return

        # Determinar dirección
        direction = self._compute_direction(norm_x, norm_y, dz)
        if direction is None:
            return

        # Enviar comando PTZ
        self.last_direction = direction
        self._last_ptz_time = now
        self.ptz.move(direction, speed=self.ptz_speed, duration=self.ptz_duration)
        # Resetear frame previo para que el propio paneo de la cámara no
        # sea detectado como movimiento en el siguiente ciclo.
        self._prev_gray = None
        logger.debug(f"[TRACK] Movimiento detectado → PTZ '{direction}' (cx={norm_x:.2f}, cy={norm_y:.2f})")

    @staticmethod
    def _compute_direction(norm_x: float, norm_y: float, dz: float) -> Optional[str]:
        """Calcula la dirección PTZ según la posición normalizada del centroide."""
        moving_h = abs(norm_x) > dz
        moving_v = abs(norm_y) > dz

        if not moving_h and not moving_v:
            return None

        # Priorizar diagonales si ambos ejes se desvían
        if moving_h and moving_v:
            h_dir = "right" if norm_x > 0 else "left"
            v_dir = "lower" if norm_y > 0 else "upper"
            return f"{v_dir}_{h_dir}"
        elif moving_h:
            return "right" if norm_x > 0 else "left"
        else:
            return "down" if norm_y > 0 else "up"
