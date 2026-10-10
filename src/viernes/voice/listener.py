"""Escuchador de micrófono optimizado para latencia mínima con Whisper local."""

import logging
import threading
from typing import Callable, Optional
import speech_recognition as sr

logger = logging.getLogger(__name__)


class VoiceListener:
    """
    Escucha continua del micrófono en segundo plano usando Whisper local.

    Optimizaciones de latencia:
    - ``pause_threshold`` reducido a 0.6s (era 1.0s) → detecta fin de frase 0.4s antes.
    - ``phrase_threshold`` reducido a 0.2s para no descartar frases cortas.
    - ``non_speaking_duration`` reducido a 0.3s → menos cola silenciosa al final.
    - Calibración de ruido de fondo en 1s (era 2s) → arranque más rápido.
    - ``model_size="tiny"`` por defecto en lugar de ``"base"`` → 3-5× más rápido,
      la pérdida de precisión en español es mínima para frases simples.
    - ``dynamic_energy_threshold=False`` + umbral fijo para evitar recalibraciones
      automáticas que elevan el threshold en entornos silenciosos entre frases.
    """

    def __init__(
        self,
        on_speech_detected: Callable[[str], None],
        language: str = "es",
        model_size: str = "tiny",           # tiny: ~200ms en CPU | base: ~600ms
        energy_threshold: int = 350,        # Sensibilidad al ruido
        pause_threshold: float = 0.6,       # Segundos de silencio para detectar fin de frase
        calibration_duration: float = 1.0,  # Segundos de calibración de ruido inicial
    ):
        """
        :param on_speech_detected:   Callback invocado con el texto transcripto.
        :param language:             Idioma para Whisper ('es' para español).
        :param model_size:           Tamaño del modelo Whisper ('tiny', 'base', 'small').
        :param energy_threshold:     Umbral fijo de energía del micrófono.
        :param pause_threshold:      Segundos de silencio para cerrar una frase.
        :param calibration_duration: Segundos de calibración de ruido ambiente al inicio.
        """
        self.on_speech_detected = on_speech_detected
        self.language = language
        self.model_size = model_size

        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()

        # --- Parámetros críticos de latencia ---
        self.recognizer.pause_threshold = pause_threshold
        self.recognizer.phrase_threshold = 0.2
        self.recognizer.non_speaking_duration = 0.3
        self.recognizer.energy_threshold = energy_threshold
        # Deshabilitar ajuste dinámico → evita que el umbral suba demasiado entre frases
        self.recognizer.dynamic_energy_threshold = False

        self._stop_listening_func = None
        self._is_listening = False

        self._calibrate(calibration_duration)

    def _calibrate(self, duration: float) -> None:
        """Calibra el ruido de fondo una sola vez al inicio."""
        logger.info(f"Calibrando ruido de fondo ({duration}s)...")
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=duration)
            logger.info(f"Calibración OK. Umbral de energía: {self.recognizer.energy_threshold:.0f}")
        except AttributeError:
            logger.error("No se pudo abrir el micrófono (ALSA locked/no device).")
        except Exception as e:
            logger.warning(f"Aviso durante calibración: {e}")

    def _audio_callback(self, recognizer: sr.Recognizer, audio: sr.AudioData) -> None:
        """
        Callback interno ejecutado en el hilo secundario al detectar fin de frase.
        Ejecuta Whisper directamente sin IPC ni subprocesos adicionales.
        """
        try:
            text = recognizer.recognize_whisper(
                audio,
                model=self.model_size,
                language=self.language,
            )
            text = text.strip()
            if text:
                logger.info(f"Transcripto: '{text}'")
                self.on_speech_detected(text)
        except sr.UnknownValueError:
            logger.debug("Audio no reconocible (ruido ambiental).")
        except sr.RequestError as e:
            logger.error(f"Error en STT: {e}")
        except Exception as e:
            logger.error(f"Excepción procesando audio: {e}")

    def start(self) -> None:
        """Inicia la escucha continua en background (no bloqueante)."""
        if self._is_listening:
            logger.warning("VoiceListener ya está en ejecución.")
            return

        logger.info("Iniciando escucha continua...")
        try:
            # phrase_time_limit=None → deja que pause_threshold controle el corte
            self._stop_listening_func = self.recognizer.listen_in_background(
                self.microphone,
                self._audio_callback,
                phrase_time_limit=None,
            )
            self._is_listening = True
        except AttributeError:
            logger.error("Micrófono no disponible (ALSA Locked).")
        except Exception as e:
            logger.error(f"Fallo al iniciar escucha: {e}")

    def stop(self) -> None:
        """Detiene la escucha y el hilo secundario."""
        if not self._is_listening or not self._stop_listening_func:
            return

        logger.info("Deteniendo escucha del micrófono...")
        self._stop_listening_func(wait_for_stop=False)
        self._is_listening = False


if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    def on_speech(texto: str):
        print(f"\n>>> [CALLBACK] Texto detectado: {texto}\n")

    listener = VoiceListener(on_speech_detected=on_speech, model_size="tiny")

    try:
        listener.start()
        logger.info("Habla por el micrófono (Ctrl+C para salir)")
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Interrupción manual.")
    finally:
        listener.stop()
        logger.info("Prueba finalizada.")
