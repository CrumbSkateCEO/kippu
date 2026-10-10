"""Módulo de Texto-a-Voz neuronal offline optimizado para latencia mínima (Piper TTS)."""

import logging
import threading
import queue
import time
import os
import contextlib
import urllib.request
from pathlib import Path
from typing import Optional

try:
    from piper.voice import PiperVoice
    import pyaudio
except ImportError:
    PiperVoice = None
    pyaudio = None

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _silence_stderr():
    """Silencia mensajes de bajo nivel a nivel de C (ALSA / JACK / PyAudio)."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        try:
            os.dup2(devnull, 2)
            yield
        finally:
            os.dup2(old_stderr, 2)
            os.close(old_stderr)
            os.close(devnull)
    except Exception:
        yield


class VoiceSpeaker:
    """
    Controlador de voz offline utilizando Piper TTS (voces neuronales).
    Hilo de fondo con cola para no bloquear la UI.

    Optimizaciones:
    - ``SynthesisConfig`` se crea UNA sola vez al cargar el modelo (no en cada síntesis).
    - ``length_scale`` reducido a 0.9 (habla un ~10% más rápida que la original 1.1).
    - Cola con ``maxsize=1``: si llega una respuesta nueva antes de terminar de hablar
      la anterior, la anterior se descarta automáticamente. Evita acumulación de deuda
      de audio cuando el LLM responde mientras el TTS sigue hablando.
    - Stream de PyAudio pre-abierto y reutilizado (evita la apertura por utterance).
    - Importaciones críticas fuera del loop de síntesis.
    """

    def __init__(self, models_dir: Optional[Path] = None, model_name: str = "es_AR-daniela-high"):
        """
        :param models_dir:  Directorio donde se guardan los modelos Piper.
        :param model_name:  Nombre del modelo de voz.
        """
        if PiperVoice is None or pyaudio is None:
            logger.error("Faltan dependencias. Ejecuta: uv pip install piper-tts PyAudio")

        if models_dir is None:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            models_dir = project_root / "assets" / "voices"

        models_dir.mkdir(parents=True, exist_ok=True)

        self.model_name = model_name
        self.onnx_path = models_dir / f"{self.model_name}.onnx"
        self.json_path = models_dir / f"{self.model_name}.onnx.json"

        # maxsize=1: descarta mensajes viejos si llega uno nuevo mientras habla
        self._queue: queue.Queue[Optional[str]] = queue.Queue(maxsize=1)
        self._running = False
        self.is_speaking = False

        # SynthesisConfig pre-instanciado (fuera del loop)
        self._syn_config = self._build_syn_config()

        self._start_thread()
        logger.info(f"VoiceSpeaker ({self.model_name}) iniciado.")

    # -----------------------------------------------------------------------
    # Config de síntesis (creada una sola vez)
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_syn_config():
        """Crea la configuración de síntesis. Devuelve None si no está disponible."""
        try:
            from piper.config import SynthesisConfig
            # length_scale < 1.0 → más rápido | noise_scale 0.667 → más natural
            return SynthesisConfig(length_scale=0.9, noise_scale=0.667, noise_w_scale=0.8)
        except ImportError:
            return None

    # -----------------------------------------------------------------------
    # Descarga del modelo
    # -----------------------------------------------------------------------

    def _ensure_model_downloaded(self) -> None:
        """Descarga el modelo neuronal si no existe localmente."""
        parts = self.model_name.split("-")
        if len(parts) == 3:
            locale, name, quality = parts
            lang_code = locale.split("_")[0]
            base_url = (
                f"https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                f"{lang_code}/{locale}/{name}/{quality}/"
            )
        else:
            base_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_AR/daniela/high/"

        for file_path, file_name in [
            (self.onnx_path, f"{self.model_name}.onnx"),
            (self.json_path, f"{self.model_name}.onnx.json"),
        ]:
            if not file_path.exists():
                logger.info(f"Descargando {file_name} (solo la primera vez)...")
                urllib.request.urlretrieve(base_url + file_name, str(file_path))
                logger.info(f"Descarga completada: {file_name}")

    # -----------------------------------------------------------------------
    # Hilo de síntesis
    # -----------------------------------------------------------------------

    def _speaker_worker(self) -> None:
        """
        Hilo demonio. Carga el modelo y el stream de audio UNA VEZ y los reutiliza
        entre utterances para eliminar el overhead de inicialización por frase.
        """
        if PiperVoice is None:
            logger.error("Motor de voz no disponible.")
            return

        try:
            self._ensure_model_downloaded()
        except Exception as e:
            logger.error(f"No se pudo descargar el modelo de voz: {e}")
            return

        logger.info("Cargando modelo neuronal Piper...")
        voice = PiperVoice.load(str(self.onnx_path))
        sample_rate = voice.config.sample_rate

        # Abrir stream de audio una sola vez
        with _silence_stderr():
            pa = pyaudio.PyAudio()
            stream = None
            try:
                stream = pa.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=sample_rate,
                    output=True,
                    frames_per_buffer=1024,  # Buffer pequeño → menor latencia de audio
                )
            except Exception as e:
                logger.error(f"No se pudo abrir el stream de audio: {e}")

        logger.info("Motor TTS listo. Esperando texto...")

        while self._running:
            try:
                text = self._queue.get(timeout=0.1)
                if text is None:
                    break  # Señal de apagado

                self.is_speaking = True
                logger.info(f"TTS sintetizando: '{text[:60]}{'...' if len(text)>60 else ''}'")

                if stream is not None:
                    try:
                        for chunk in voice.synthesize(text, syn_config=self._syn_config):
                            if not self._running:
                                break
                            stream.write(chunk.audio_int16_bytes)
                    except Exception as e:
                        logger.error(f"Error sintetizando: {e}")

                self._queue.task_done()

            except queue.Empty:
                self.is_speaking = False
            except Exception as e:
                logger.error(f"Error en speaker worker: {e}")
            finally:
                self.is_speaking = False

        # Limpieza
        with _silence_stderr():
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            pa.terminate()

        logger.info("VoiceSpeaker worker detenido.")

    def _start_thread(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._speaker_worker, daemon=True, name="tts-worker"
        )
        self._thread.start()

    # -----------------------------------------------------------------------
    # API pública
    # -----------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """
        Encola texto para síntesis. Si la cola está llena (ya hay un mensaje
        esperando), descarta el nuevo y habla solo el actual.
        Retorna instantáneamente sin bloquear.
        """
        if not text or not text.strip():
            return
        text = text.strip()
        try:
            # put_nowait: si la cola está llena lanza Full en lugar de bloquear
            self._queue.put_nowait(text)
        except queue.Full:
            # Descartar el mensaje más viejo y poner el nuevo
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(text)
            except queue.Full:
                pass

    def interrupt(self) -> None:
        """Vacía la cola de audio pendiente (interrumpe lo que está por decir)."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break

    def wait_until_done(self) -> None:
        """Bloquea hasta que todos los audios encolados hayan terminado."""
        self._queue.join()
        while self.is_speaking and self._running:
            time.sleep(0.05)

    def stop(self) -> None:
        """Detiene el hilo secundario limpiamente."""
        if not self._running:
            return
        self._running = False
        # Señal de apagado para desbloquear el queue.get
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("VoiceSpeaker detenido.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    print("=========================================================")
    print(" Prueba de VoiceSpeaker optimizado (Piper TTS Offline)")
    print("=========================================================\n")

    speaker = VoiceSpeaker()
    time.sleep(0.5)

    speaker.speak("Hola, soy Viernes. Mi síntesis de voz es más rápida ahora.")
    speaker.speak("Este proceso es completamente asíncrono y offline.")

    try:
        speaker.wait_until_done()
    except KeyboardInterrupt:
        print("\nInterrupción manual.")
    finally:
        speaker.stop()
        print("\nPrueba finalizada.")
