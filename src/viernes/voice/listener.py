"""Placeholder para el escuchador del micrófono y Speech-to-Text."""

import logging
import threading
from typing import Callable, Optional
import speech_recognition as sr

logger = logging.getLogger(__name__)

class VoiceListener:
    """
    Escucha continua del micrófono en segundo plano.
    Implementa VAD básico a través de SpeechRecognition y utiliza Whisper
    para la transcripción a texto de forma local.
    """
    def __init__(self, on_speech_detected: Callable[[str], None], language: str = "es", model_size: str = "base"):
        """
        :param on_speech_detected: Callback que se invoca cuando se transcribe una frase válida.
        :param language: Código de idioma ('es' para español).
        :param model_size: Tamaño del modelo de Whisper ('tiny', 'base', 'small', etc).
        """
        self.on_speech_detected = on_speech_detected
        self.language = language
        self.model_size = model_size
        
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        
        self.recognizer.pause_threshold = 1.0
        self.recognizer.energy_threshold = 400
        self.recognizer.dynamic_energy_threshold = True
        
        self._stop_listening_func = None
        self._is_listening = False
        
        logger.info("Calibrando ruido de fondo del micrófono (2 segundos)...")
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=2)
            logger.info(f"Calibración completada. Umbral de energía: {self.recognizer.energy_threshold}")
        except AttributeError:
            logger.error("Error crítico: No se pudo abrir el micrófono (ALSA locked/no device). Revisa tu hardware.")
        except Exception as e:
            logger.warning(f"Aviso durante la calibración del micrófono: {e}")

    def _audio_callback(self, recognizer: sr.Recognizer, audio: sr.AudioData):
        """Callback interno ejecutado en el hilo secundario cuando el VAD detecta fin de frase."""
        logger.info("Audio capturado, procesando transcripción...")
        try:
            text = recognizer.recognize_whisper(audio, model=self.model_size, language=self.language)
            text = text.strip()
            
            if text:
                logger.info(f"Viernes escuchó: '{text}'")
                self.on_speech_detected(text)
                
        except sr.UnknownValueError:
            logger.debug("No se pudo entender el audio (ruido ambiental).")
        except sr.RequestError as e:
            logger.error(f"Error en el servicio de STT: {e}")
        except Exception as e:
            logger.error(f"Excepción inesperada procesando audio: {e}")

    def start(self):
        """Inicia el hilo de escucha en segundo plano de manera no bloqueante."""
        if self._is_listening:
            logger.warning("El VoiceListener ya está en ejecución.")
            return

        logger.info("Iniciando escucha continua en background...")
        try:
            self._stop_listening_func = self.recognizer.listen_in_background(
                self.microphone, 
                self._audio_callback
            )
            self._is_listening = True
        except AttributeError:
            logger.error("No se pudo iniciar la escucha: Micrófono no disponible (ALSA Locked).")
        except Exception as e:
            logger.error(f"Fallo al iniciar escucha continua: {e}")

    def stop(self):
        """Detiene la escucha y el hilo secundario."""
        if not self._is_listening or not self._stop_listening_func:
            return
            
        logger.info("Deteniendo escucha del micrófono...")
        self._stop_listening_func(wait_for_stop=False)
        self._is_listening = False


if __name__ == "__main__":
    import time
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Callback de prueba
    def on_speech(texto: str):
        print(f"\n>>>> [NOTIFICACIÓN CALLBACK] Texto detectado: {texto}\n")

    logger.info("Instanciando VoiceListener de prueba con modelo 'base'...")
    # Puedes usar 'tiny' si quieres más velocidad en CPU a costa de un poco de precisión.
    listener = VoiceListener(on_speech_detected=on_speech, model_size="base")
    
    try:
        listener.start()
        logger.info("¡La prueba está activa! Habla por el micrófono (Presiona Ctrl+C para salir)")
        
        # Mantenemos el hilo principal vivo simulando que la app (PyQt) u otro ciclo
        # se está ejecutando independientemente sin bloquearse.
        while True:
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        logger.info("Interrupción manual (Ctrl+C).")
    finally:
        listener.stop()
        logger.info("Prueba finalizada.")
