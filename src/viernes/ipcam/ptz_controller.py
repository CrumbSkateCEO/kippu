"""Control PTZ de cámara IP vía ONVIF (compatible con Gadnic/ICSee y cualquier cámara ONVIF)."""

import logging
import time
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# onvif-zeep es el cliente ONVIF para Python
try:
    from onvif import ONVIFCamera
    ONVIF_AVAILABLE = True
except ImportError:
    ONVIFCamera = None
    ONVIF_AVAILABLE = False
    logger.warning("Librería 'onvif-zeep' no instalada. Control PTZ desactivado.")


class PTZController:
    """
    Controlador de movimiento Pan/Tilt/Zoom para cámaras IP con ONVIF.
    
    Envía comandos de movimiento relativo (pasos discretos) o continuo
    y los detiene automáticamente tras un timeout.
    
    Uso típico:
        ptz = PTZController(host="192.168.1.100", port=8899, user="admin", password="12345")
        ptz.move("left")
        ptz.move("up", speed=0.4, duration=0.5)
    """

    # Vectores de dirección: (pan, tilt)  +pan=derecha, +tilt=arriba
    DIRECTIONS = {
        "left":       (-1.0,  0.0),
        "right":      ( 1.0,  0.0),
        "up":         ( 0.0,  1.0),
        "down":       ( 0.0, -1.0),
        "upper_left":  (-0.7,  0.7),
        "upper_right": ( 0.7,  0.7),
        "lower_left":  (-0.7, -0.7),
        "lower_right": ( 0.7, -0.7),
        "center":     ( 0.0,  0.0),   # Stop / ir al centro
    }

    def __init__(
        self,
        host: str,
        port: int = 8899,
        user: str = "admin",
        password: str = "12345",
        wsdl_dir: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self._camera: Optional[object] = None
        self._ptz_service = None
        self._media_service = None
        self._profile_token: Optional[str] = None
        self._stop_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._connected = False

        self._wsdl_dir = wsdl_dir  # None → onvif-zeep usa los incluidos en el paquete

        # Intentar conectar al inicializar
        self._connect()

    # -----------------------------------------------------------------------
    # Conexión
    # -----------------------------------------------------------------------

    def _connect(self) -> bool:
        """Establece la sesión ONVIF con la cámara."""
        if not ONVIF_AVAILABLE:
            logger.error("onvif-zeep no está instalado. Ejecuta: pip install onvif-zeep")
            return False

        if not self.host:
            return False

        import socket
        try:
            with socket.create_connection((self.host, self.port), timeout=1.0):
                pass
        except Exception as e:
            logger.warning(
                f"[PTZ] No se pudo alcanzar el puerto ONVIF de la cámara en {self.host}:{self.port} ({e}). "
                "Movimiento PTZ desactivado para evitar bloqueos."
            )
            self._connected = False
            return False

        try:
            kwargs = dict(host=self.host, port=self.port, user=self.user, passwd=self.password)
            if self._wsdl_dir:
                kwargs["wsdl_dir"] = self._wsdl_dir

            logger.info(f"Conectando a cámara ONVIF en {self.host}:{self.port}...")
            self._camera = ONVIFCamera(**kwargs)
            self._media_service = self._camera.create_media_service()
            self._ptz_service = self._camera.create_ptz_service()

            # Obtener el primer perfil de medios
            profiles = self._media_service.GetProfiles()
            if not profiles:
                logger.error("La cámara no devolvió ningún perfil de medios.")
                return False

            self._profile_token = profiles[0].token
            self._connected = True
            logger.info(f"PTZ listo. Perfil activo: {self._profile_token}")
            return True

        except Exception as e:
            logger.error(f"Error conectando a cámara ONVIF: {e}")
            self._connected = False
            return False

    def is_connected(self) -> bool:
        return self._connected

    # -----------------------------------------------------------------------
    # Movimiento
    # -----------------------------------------------------------------------

    def move(
        self,
        direction: str,
        speed: float = 0.3,
        duration: float = 0.6,
    ) -> bool:
        """
        Mueve la cámara en la dirección indicada durante 'duration' segundos.

        :param direction: Una de las claves de DIRECTIONS ('left', 'right', 'up', 'down', etc.)
        :param speed:     Velocidad (0.0 – 1.0). Por defecto 0.3 (suave).
        :param duration:  Tiempo de movimiento en segundos. Tras él se envía Stop.
        :return:          True si el comando se envió con éxito.
        """
        if not self._connected:
            logger.warning("PTZ no conectado. Intentando reconectar...")
            if not self._connect():
                return False

        direction = direction.lower().strip()

        if direction not in self.DIRECTIONS:
            logger.error(f"Dirección desconocida: '{direction}'. Válidas: {list(self.DIRECTIONS.keys())}")
            return False

        pan_sign, tilt_sign = self.DIRECTIONS[direction]

        if direction == "center":
            return self.stop()

        with self._lock:
            # Cancelar cualquier stop anterior pendiente
            if self._stop_timer and self._stop_timer.is_alive():
                self._stop_timer.cancel()

            try:
                request = self._ptz_service.create_type("ContinuousMove")
                request.ProfileToken = self._profile_token
                request.Velocity = {
                    "PanTilt": {
                        "x": pan_sign * speed,
                        "y": tilt_sign * speed,
                    },
                    "Zoom": {"x": 0.0},
                }
                self._ptz_service.ContinuousMove(request)
                logger.info(f"PTZ → {direction} (speed={speed}, dur={duration}s)")

                # Programar stop automático
                self._stop_timer = threading.Timer(duration, self._auto_stop)
                self._stop_timer.daemon = True
                self._stop_timer.start()
                return True

            except Exception as e:
                logger.error(f"Error enviando comando PTZ ContinuousMove: {e}")
                self._connected = False
                return False

    def stop(self) -> bool:
        """Detiene cualquier movimiento en curso."""
        if not self._connected:
            return False
        try:
            request = self._ptz_service.create_type("Stop")
            request.ProfileToken = self._profile_token
            request.PanTilt = True
            request.Zoom = False
            self._ptz_service.Stop(request)
            logger.info("PTZ detenido.")
            return True
        except Exception as e:
            logger.error(f"Error enviando Stop PTZ: {e}")
            self._connected = False
            return False

    def _auto_stop(self):
        """Llamado automáticamente por el timer tras el movimiento."""
        self.stop()

    def zoom(self, direction: str = "in", speed: float = 0.3, duration: float = 0.5) -> bool:
        """
        Controla el zoom óptico/digital.
        :param direction: 'in' (acercar) o 'out' (alejar).
        """
        if not self._connected:
            return False

        zoom_val = speed if direction == "in" else -speed

        with self._lock:
            if self._stop_timer and self._stop_timer.is_alive():
                self._stop_timer.cancel()
            try:
                request = self._ptz_service.create_type("ContinuousMove")
                request.ProfileToken = self._profile_token
                request.Velocity = {
                    "PanTilt": {"x": 0.0, "y": 0.0},
                    "Zoom": {"x": zoom_val},
                }
                self._ptz_service.ContinuousMove(request)
                self._stop_timer = threading.Timer(duration, self._auto_stop)
                self._stop_timer.daemon = True
                self._stop_timer.start()
                return True
            except Exception as e:
                logger.error(f"Error enviando comando Zoom: {e}")
                return False

    def go_home(self) -> bool:
        """Lleva la cámara a la posición 'home' predefinida en la cámara."""
        if not self._connected:
            return False
        try:
            request = self._ptz_service.create_type("GotoHomePosition")
            request.ProfileToken = self._profile_token
            request.Speed = None
            self._ptz_service.GotoHomePosition(request)
            logger.info("PTZ → home position")
            return True
        except Exception as e:
            logger.error(f"Error enviando GotoHome: {e}")
            return False
