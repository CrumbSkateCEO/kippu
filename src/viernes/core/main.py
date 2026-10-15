"""Orquestador Principal de Viernes — optimizado para latencia mínima con streaming."""

import sys
import logging
import threading
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from viernes.ipcam.camera_stream import IPCameraStream
from viernes.ipcam.ptz_controller import PTZController
from viernes.dashboard.tv_view import ViernesDashboard
from viernes.voice.listener import VoiceListener
from viernes.llm.brain import ViernesBrain
from viernes.voice.speaker import VoiceSpeaker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Carga de configuración (cacheada, solo se lee una vez)
# ---------------------------------------------------------------------------

_config_cache: dict | None = None

def _load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    candidates = [
        Path("config/config.toml"),
        Path(__file__).resolve().parents[4] / "config" / "config.toml",
    ]
    for path in candidates:
        if path.exists():
            try:
                if sys.version_info >= (3, 11):
                    import tomllib
                    with open(path, "rb") as f:
                        _config_cache = tomllib.load(f)
                else:
                    import tomli
                    with open(path, "rb") as f:
                        _config_cache = tomli.load(f)
                logger.info(f"Config cargado desde: {path}")
                return _config_cache
            except Exception as e:
                logger.warning(f"Error cargando config: {e}")

    logger.warning("config.toml no encontrado. Usando valores por defecto.")
    _config_cache = {}
    return _config_cache


# ---------------------------------------------------------------------------
# Controlador Principal
# ---------------------------------------------------------------------------

class ViernesController(QObject):
    """
    Controlador central de Viernes. Coordina todos los módulos usando
    señales/slots de PyQt6 para comunicación thread-safe.

    Optimizaciones:
    - El LLM usa streaming: cada oración se entrega al TTS sin esperar el texto
      completo. Latencia percibida: primer sílaba en <500ms.
    - Si el usuario habla mientras Viernes responde, la respuesta en curso
      se cancela (brain.cancel_current) y el TTS se interrumpe (speaker.interrupt).
    - El hilo de inferencia se marca como daemon y no se bloquea entre turnos.
    - Config se lee una sola vez y se cachea.
    """

    signal_user_spoke = pyqtSignal(str)
    signal_sentence_ready = pyqtSignal(str)    # Una oración lista para mostrar/hablar
    signal_viernes_done = pyqtSignal()          # Respuesta completa terminada
    signal_camera_action = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        logger.info("[INIT] Inicializando Viernes...")

        cfg = _load_config()
        ipcam_cfg = cfg.get("ipcam", {})
        llm_cfg = cfg.get("llm", {})

        # --- Cámara RTSP con opciones FFmpeg de baja latencia ---
        rtsp_url = ipcam_cfg.get("rtsp_url", "0")
        ffmpeg_options = ipcam_cfg.get(
            "rtsp_ffmpeg_options",
            "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|timeout;2000000|analyzeduration;100000|probesize;32",
        )
        drop_frames = ipcam_cfg.get("rtsp_drop_frames", True)
        self.camera = IPCameraStream(
            rtsp_url,
            ffmpeg_options=ffmpeg_options,
            drop_frames=drop_frames,
        )

        # --- PTZ ONVIF (opcional) ---
        self.ptz: PTZController | None = None
        ptz_host = ipcam_cfg.get("host", "")
        if ptz_host:
            self.ptz = PTZController(
                host=ptz_host,
                port=ipcam_cfg.get("onvif_port", 8899),
                user=ipcam_cfg.get("user", "admin"),
                password=ipcam_cfg.get("password", "12345"),
            )
            if not self.ptz.is_connected():
                logger.warning("[PTZ] No conectado. Movimiento desactivado.")
                self.ptz = None
        else:
            logger.info("[PTZ] Sin host configurado. PTZ desactivado.")

        # --- Dashboard ---
        self.dashboard = ViernesDashboard(self.camera)

        # --- LLM con visión y PTZ ---
        model_name = llm_cfg.get("model", "llava")
        self.brain = ViernesBrain(
            model_name=model_name,
            camera_stream=self.camera,
            ptz_controller=self.ptz,
            on_camera_action=self._on_camera_action_callback,
        )

        # --- Voz ---
        self.listener = VoiceListener(on_speech_detected=self._on_speech_detected_callback)
        # VoiceSpeaker puede fallar si piper-tts o PyAudio no están instalados.
        # En ese caso Viernes funciona sin voz (solo texto en pantalla).
        try:
            self.speaker: VoiceSpeaker | None = VoiceSpeaker()
        except Exception as exc:
            logger.warning(
                "[TTS] No se pudo inicializar VoiceSpeaker: %s. "
                "Viernes continuará sin síntesis de voz.",
                exc,
            )
            self.speaker = None

        # --- Estado de inferencia ---
        self._inference_lock = threading.Lock()  # Solo una inferencia a la vez

        # --- Señales ---
        self.signal_user_spoke.connect(self._slot_user_spoke)
        self.signal_sentence_ready.connect(self._slot_sentence_ready)
        self.signal_viernes_done.connect(self._slot_viernes_done)
        self.signal_camera_action.connect(self._slot_camera_action)

        logger.info("[INIT] Viernes listo.")

    # -----------------------------------------------------------------------
    # Ciclo de vida
    # -----------------------------------------------------------------------

    def start(self) -> None:
        self.dashboard.showMaximized()
        self.listener.start()

        caps = []
        if self.camera:
            caps.append("visión")
        if self.ptz:
            caps.append("control de cámara")

        saludo = (
            f"Sistemas en línea. Tengo {' y '.join(caps)} activos. Te escucho."
            if caps
            else "Sistemas en línea. Te escucho."
        )
        self.dashboard.update_subtitle(f"Viernes: {saludo}")
        if self.speaker:
            self.speaker.speak(saludo)

    # -----------------------------------------------------------------------
    # Callbacks (desde hilos externos → emiten señales al hilo Qt)
    # -----------------------------------------------------------------------

    def _on_speech_detected_callback(self, text: str) -> None:
        logger.info(f"[STT] '{text}'")
        self.signal_user_spoke.emit(text)

    def _on_camera_action_callback(self, description: str) -> None:
        logger.info(f"[CAM] {description}")
        self.signal_camera_action.emit(description)

    # -----------------------------------------------------------------------
    # Slots (hilo principal de Qt)
    # -----------------------------------------------------------------------

    @pyqtSlot(str)
    def _slot_user_spoke(self, text: str) -> None:
        """
        El usuario habló. Cancela cualquier inferencia en curso, interrumpe
        el TTS y lanza la nueva inferencia en streaming.
        """
        # Cancelar respuesta anterior si Viernes aún estaba hablando/pensando
        self.brain.cancel_current()
        if self.speaker:
            self.speaker.interrupt()

        self.dashboard.update_subtitle(f"Usuario: {text}")
        threading.Thread(
            target=self._stream_response,
            args=(text,),
            daemon=True,
            name="llm-stream",
        ).start()

    def _stream_response(self, text: str) -> None:
        """
        Genera la respuesta del LLM en streaming, enviando cada oración al TTS
        y a la UI sin esperar el texto completo.

        Ejecutado en un hilo secundario. Usa _inference_lock para serializar
        múltiples llamadas concurrentes (la más reciente gana gracias al
        cancel_token del brain).
        """
        with self._inference_lock:
            full_response = []

            try:
                for sentence in self.brain.think_stream(text):
                    if not sentence:
                        continue
                    full_response.append(sentence)

                    # Enviar cada oración al TTS y a la UI inmediatamente
                    if self.speaker:
                        self.speaker.speak(sentence)
                    self.signal_sentence_ready.emit(sentence)

            except Exception as e:
                logger.error(f"Error en stream de respuesta: {e}")
                error_msg = "Hubo un error procesando tu pregunta."
                if self.speaker:
                    self.speaker.speak(error_msg)
                self.signal_sentence_ready.emit(error_msg)

            finally:
                self.signal_viernes_done.emit()

    @pyqtSlot(str)
    def _slot_sentence_ready(self, sentence: str) -> None:
        """Actualiza el subtítulo del dashboard con cada oración recibida."""
        self.dashboard.update_subtitle(f"Viernes: {sentence}")

    @pyqtSlot()
    def _slot_viernes_done(self) -> None:
        """La respuesta completa terminó. Volver al estado de escucha."""
        # El dashboard vuelve al estado LISTENING automáticamente vía update_subtitle
        pass

    @pyqtSlot(str)
    def _slot_camera_action(self, description: str) -> None:
        self.dashboard.update_subtitle(description)

    # -----------------------------------------------------------------------
    # Apagado
    # -----------------------------------------------------------------------

    def stop_all(self) -> None:
        logger.info("[APAGADO] Deteniendo módulos...")
        self.brain.cancel_current()
        self.listener.stop()
        if self.speaker:
            self.speaker.stop()
        self.camera.stop()
        if self.ptz:
            self.ptz.stop()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    app = QApplication(sys.argv)
    controller = ViernesController()
    app.aboutToQuit.connect(controller.stop_all)
    controller.start()
    logger.info("Entrando al loop de eventos de PyQt6...")
    sys.exit(app.exec())
