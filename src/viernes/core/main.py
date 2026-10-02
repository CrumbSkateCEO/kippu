"""Orquestador Principal de Viernes."""

import sys
import logging
import threading
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

# Agregamos la raíz del proyecto al sys.path para importaciones absolutas
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from src.viernes.ipcam.camera_stream import IPCameraStream
from src.viernes.dashboard.tv_view import ViernesDashboard
from src.viernes.voice.listener import VoiceListener
from src.viernes.llm.brain import ViernesBrain
from src.viernes.voice.speaker import VoiceSpeaker

logger = logging.getLogger(__name__)

class ViernesController(QObject):
    """
    Controlador central de Viernes.
    Hereda de QObject para utilizar el sistema de señales/slots de PyQt6.
    Coordina la cámara, la UI, el escuchador, el cerebro LLM y el hablante TTS.
    """
    # Señales para comunicación thread-safe
    signal_user_spoke = pyqtSignal(str)
    signal_viernes_replied = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        logger.info("[INIT] Inicializando Controlador de Viernes...")
        
        # 1. Cámara IP (El Ojo)
        logger.info("[INIT] Inicializando Cámara IP...")
        # NOTA: Cambiar "0" por la URL RTSP cuando se instale la cámara de seguridad
        self.camera = IPCameraStream("0")
        
        # 2. UI Dashboard (El Rostro/Pantalla)
        logger.info("[INIT] Inicializando Dashboard TV...")
        self.dashboard = ViernesDashboard(self.camera)
        
        # 3. Cerebro LLM (La Lógica)
        logger.info("[INIT] Inicializando Cerebro (Ollama)...")
        self.brain = ViernesBrain()
        
        # 4. Escuchador (El Oído) - Inicializar ANTES que el TTS para asegurar acceso a PyAudio/ALSA
        logger.info("[INIT] Inicializando Escuchador de Voz (Whisper)...")
        self.listener = VoiceListener(on_speech_detected=self.on_speech_detected_callback)

        # 5. Parlante TTS (La Boca)
        logger.info("[INIT] Inicializando Parlante (Piper TTS)...")
        self.speaker = VoiceSpeaker()
        
        # --- Conexión de Señales a Slots ---
        self.signal_user_spoke.connect(self.slot_user_spoke)
        self.signal_viernes_replied.connect(self.slot_viernes_replied)
        
        logger.info("[INIT] Orquestación completada. Viernes en línea.")

    def start(self):
        """Inicia los servicios, muestra la UI y empieza a escuchar."""
        logger.info("[START] Lanzando Dashboard...")
        self.dashboard.showMaximized()
        
        logger.info("[START] Activando el micrófono...")
        self.listener.start()
        
        # Bienvenida
        saludo_inicial = "Sistemas en línea. Te escucho."
        self.dashboard.update_subtitle(f"Viernes: {saludo_inicial}")
        self.speaker.speak(saludo_inicial)

    def on_speech_detected_callback(self, text: str):
        """
        CALLBACK DEL HILO SECUNDARIO (VoiceListener).
        Crucial: No interactuamos con la UI aquí directamente.
        Solo emitimos la señal para delegar la carga al hilo principal.
        """
        logger.info(f"[EVENTO] Usuario habló: '{text}' -> Emitiendo señal...")
        self.signal_user_spoke.emit(text)

    @pyqtSlot(str)
    def slot_user_spoke(self, text: str):
        """
        SLOT DEL HILO PRINCIPAL (PyQt).
        Actualiza el subtítulo inmediatamente y lanza el cerebro a pensar en el fondo.
        """
        logger.info(f"[SLOT] Actualizando UI con lo dicho por el usuario.")
        self.dashboard.update_subtitle(f"Usuario: {text}")
        
        # MODO ECO: Repetir lo que dijo el usuario para probar entrada y salida
        logger.info(f"[MODO ECO] Repitiendo el texto: '{text}'")
        self.signal_viernes_replied.emit(text)

    def _think_in_background(self, text: str):
        """HILO SECUNDARIO (LLM Inferencia)."""
        logger.info("[CEREBRO] Pensando respuesta...")
        respuesta = self.brain.think(text)
        logger.info(f"[EVENTO] Cerebro respondió: '{respuesta}' -> Emitiendo señal...")
        self.signal_viernes_replied.emit(respuesta)

    @pyqtSlot(str)
    def slot_viernes_replied(self, text: str):
        """
        SLOT DEL HILO PRINCIPAL (PyQt).
        Llamado cuando Ollama termina de generar la respuesta.
        """
        logger.info(f"[SLOT] Actualizando UI y activando voz de Viernes.")
        self.dashboard.update_subtitle(f"Viernes: {text}")
        
        # El speaker internamente ya encola el trabajo a su propio hilo asíncrono
        self.speaker.speak(text)

    def stop_all(self):
        """Apaga y libera los recursos de todos los módulos de forma limpia."""
        logger.info("\n[APAGADO] Solicitud de cierre recibida. Deteniendo módulos...")
        self.listener.stop()
        self.speaker.stop()
        # Nota: self.camera.stop() y self.dashboard.timer.stop() ya ocurren 
        # en el closeEvent() de ViernesDashboard.


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    app = QApplication(sys.argv)
    
    controller = ViernesController()
    
    # Enganchamos la señal de cierre de la app para limpiar hilos/dispositivos
    app.aboutToQuit.connect(controller.stop_all)
    
    # Iniciar flujo
    controller.start()
    
    logger.info("Entrando al Bucle de Eventos (Main Loop) de PyQt6...")
    sys.exit(app.exec())
