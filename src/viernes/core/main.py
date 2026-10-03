"""Orquestador Principal de Viernes."""

import sys
import logging
import threading
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


from viernes.ipcam.camera_stream import IPCameraStream
from viernes.dashboard.tv_view import ViernesDashboard
from viernes.voice.listener import VoiceListener
from viernes.llm.brain import ViernesBrain
from viernes.voice.speaker import VoiceSpeaker

logger = logging.getLogger(__name__)

class ViernesController(QObject):
    """
    Controlador central de Viernes.
    Coordina la cámara, la UI, el escuchador, el cerebro LLM y el hablante TTS
    usando el sistema de señales/slots de PyQt6 para comunicación thread-safe.
    """
    signal_user_spoke = pyqtSignal(str)
    signal_viernes_replied = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        logger.info("[INIT] Inicializando Controlador de Viernes...")
        
        self.camera = IPCameraStream("0")
        self.dashboard = ViernesDashboard(self.camera)
        self.brain = ViernesBrain()
        self.listener = VoiceListener(on_speech_detected=self.on_speech_detected_callback)
        self.speaker = VoiceSpeaker()
        
        self.signal_user_spoke.connect(self.slot_user_spoke)
        self.signal_viernes_replied.connect(self.slot_viernes_replied)
        
        logger.info("[INIT] Orquestación completada. Viernes en línea.")

    def start(self):
        """Inicia los servicios, muestra la UI y empieza a escuchar."""
        self.dashboard.showMaximized()
        self.listener.start()
        saludo_inicial = "Sistemas en línea. Te escucho."
        self.dashboard.update_subtitle(f"Viernes: {saludo_inicial}")
        self.speaker.speak(saludo_inicial)

    def on_speech_detected_callback(self, text: str):
        """Callback del hilo de VoiceListener. Emite señal al hilo principal."""
        logger.info(f"[EVENTO] Usuario habló: '{text}'")
        self.signal_user_spoke.emit(text)

    @pyqtSlot(str)
    def slot_user_spoke(self, text: str):
        """Actualiza el subtítulo y lanza la inferencia del LLM en segundo plano."""
        self.dashboard.update_subtitle(f"Usuario: {text}")
        threading.Thread(target=self._think_in_background, args=(text,), daemon=True).start()

    def _think_in_background(self, text: str):
        """Ejecuta la inferencia del LLM en un hilo secundario."""
        respuesta = self.brain.think(text)
        self.signal_viernes_replied.emit(respuesta)

    @pyqtSlot(str)
    def slot_viernes_replied(self, text: str):
        """Actualiza la UI con la respuesta de Viernes y la reproduce por voz."""
        self.dashboard.update_subtitle(f"Viernes: {text}")
        self.speaker.speak(text)

    def stop_all(self):
        """Apaga y libera los recursos de todos los módulos de forma limpia."""
        logger.info("[APAGADO] Solicitud de cierre recibida. Deteniendo módulos...")
        self.listener.stop()
        self.speaker.stop()


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
