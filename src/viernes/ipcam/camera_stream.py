"""Módulo para la captura de video RTSP con latencia cero."""

import cv2
import threading
import logging
import time
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

class IPCameraStream:
    """
    Gestor de stream RTSP que utiliza un hilo en segundo plano para leer continuamente
    los frames de la cámara. Esto evita que el buffer interno de OpenCV acumule frames
    antiguos, garantizando latencia cero al consultar el frame más reciente.
    """
    def __init__(self, rtsp_url: str):
        self.stream_url = rtsp_url
        self.current_frame: Optional[np.ndarray] = None
        self._cap: Optional[cv2.VideoCapture] = None
        
        self._running = False
        self._lock = threading.Lock()
        
        # Iniciar el hilo de actualización de frames
        self.start()

    def start(self) -> None:
        """Inicia el hilo de captura en segundo plano."""
        if self._running:
            return
            
        self._running = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        logger.info(f"Hilo de captura iniciado para RTSP: {self.stream_url}")

    def _connect(self) -> bool:
        """Intenta (re)conectar a la cámara."""
        if self._cap is not None:
            self._cap.release()
            
        logger.info(f"Conectando a cámara RTSP: {self.stream_url}")
        
        # En caso de recibir "0" u otro id numérico para webcam, lo casteamos a int
        # para que cv2.VideoCapture funcione localmente
        source = int(self.stream_url) if self.stream_url.isdigit() else self.stream_url
        self._cap = cv2.VideoCapture(source)
        
        if not self._cap.isOpened():
            logger.warning(f"No se pudo conectar a la cámara RTSP: {self.stream_url}")
            return False
            
        logger.info("Cámara conectada exitosamente.")
        return True

    def _update_loop(self) -> None:
        """
        Bucle interno del hilo. Mantiene el buffer limpio consumiendo frames
        constantemente y actualiza el último frame válido.
        Maneja la reconexión automática si se pierde la señal.
        """
        connected = self._connect()
        
        while self._running:
            if not connected or self._cap is None or not self._cap.isOpened():
                logger.warning("Cámara desconectada. Intentando reconectar en 3 segundos...")
                time.sleep(3.0)
                # Sólo reconectamos si el hilo sigue corriendo
                if self._running:
                    connected = self._connect()
                continue

            try:
                ret, frame = self._cap.read()
                if ret and frame is not None:
                    # Actualizar de forma segura el frame actual
                    with self._lock:
                        self.current_frame = frame
                else:
                    logger.error("Error al leer el frame (¿cámara desconectada?).")
                    connected = False
            except Exception as e:
                logger.error(f"Excepción en la lectura de la cámara: {e}")
                connected = False

        # Limpiar al salir del bucle
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        logger.info("Hilo de captura de cámara detenido.")

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """
        Retorna instantáneamente el último frame leído de la cámara sin bloquear el hilo principal.
        """
        with self._lock:
            # Retorna una copia para evitar condiciones de carrera si el frame original
            # se llegara a procesar/modificar en otro hilo mientras OpenCV lo recicla.
            if self.current_frame is not None:
                return self.current_frame.copy()
            return None

    def stop(self) -> None:
        """Detiene el hilo de lectura y libera los recursos de video de forma segura."""
        if not self._running:
            return
            
        logger.info("Deteniendo stream RTSP...")
        self._running = False
        
        # Esperar a que termine el hilo si estamos siendo llamados desde el hilo principal
        if threading.current_thread() is not self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            
        with self._lock:
            self.current_frame = None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Por defecto apuntamos a "0" para usar la webcam local si no tienes
    # la cámara IP conectada en este preciso momento, 
    # facilitando el debug de la lógica de latencia y threads.
    # Reemplaza con tu "rtsp://..." cuando conectes la cámara IP.
    test_rtsp_url = "0" 
    
    logger.info("Iniciando prueba independiente de IPCameraStream...")
    camera = IPCameraStream(test_rtsp_url)
    
    try:
        logger.info("Presiona 'q' en la ventana para salir.")
        while True:
            # Solicita el frame sin bloqueos y de latencia cero
            frame = camera.get_latest_frame()
            
            if frame is not None:
                cv2.imshow("Viernes IP Camera Stream", frame)
            else:
                # Si no hay frame, mostramos una pantalla de reconexión/error
                blank = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(blank, "Esperando conexion/frame...", (50, 240), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                cv2.imshow("Viernes IP Camera Stream", blank)
            
            # Limite a 30 FPS visualización / Tecla 'q' para salir
            if cv2.waitKey(33) & 0xFF == ord('q'):
                logger.info("Tecla 'q' presionada. Saliendo...")
                break
                
    except KeyboardInterrupt:
        logger.info("Interrupción manual capturada (Ctrl+C).")
    finally:
        camera.stop()
        cv2.destroyAllWindows()
        logger.info("Prueba finalizada de manera segura.")
