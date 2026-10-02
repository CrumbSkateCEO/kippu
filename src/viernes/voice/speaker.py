"""Módulo de Texto-a-Voz (TTS) neuronal offline para Viernes utilizando Piper TTS."""

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
    Controlador de voz offline utilizando Piper TTS (Voces Neuronales).
    Implementa un hilo en segundo plano con una cola de mensajes para evitar 
    congelar la interfaz principal. Descarga automáticamente el modelo de voz.
    """
    def __init__(self, models_dir: Optional[Path] = None, model_name: str = "es_AR-daniela-high"):
        """
        :param models_dir: Directorio donde se guardan las voces (por defecto kippu/assets/voices).
        :param model_name: Nombre del modelo de voz (por defecto "es_AR-daniela-high").
        """
        if PiperVoice is None or pyaudio is None:
            logger.error("Faltan dependencias. Ejecuta: uv pip install piper-tts PyAudio")
            
        # Determinar el directorio de los modelos
        if models_dir is None:
            # Asume que estamos en src/viernes/voice/speaker.py
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            models_dir = project_root / "assets" / "voices"
            
        models_dir.mkdir(parents=True, exist_ok=True)
        
        # Archivos del modelo (voz de alta calidad "es_AR-daniela-high" - español de Argentina)
        self.model_name = model_name
        self.onnx_path = models_dir / f"{self.model_name}.onnx"
        self.json_path = models_dir / f"{self.model_name}.onnx.json"
        
        self._ensure_model_downloaded()
        
        self._queue = queue.Queue()
        self._running = False
        self.is_speaking = False
        
        # Iniciar el hilo de procesamiento de voz
        self._start_thread()
        logger.info(f"VoiceSpeaker neuronal ({self.model_name}) inicializado en background.")

    def _ensure_model_downloaded(self):
        """Descarga el modelo neuronal de alta calidad si no existe localmente."""
        # Desglosa el formato locale-nombre-calidad (ej: es_AR-daniela-high o es_MX-claude-high)
        parts = self.model_name.split("-")
        if len(parts) == 3:
            locale, name, quality = parts
            lang_code = locale.split("_")[0]
            base_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang_code}/{locale}/{name}/{quality}/"
        else:
            base_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_AR/daniela/high/"
        
        for file_path, file_name in [(self.onnx_path, f"{self.model_name}.onnx"), 
                                     (self.json_path, f"{self.model_name}.onnx.json")]:
            if not file_path.exists():
                logger.info(f"Descargando modelo de voz {file_name} (esto se hace solo una vez)...")
                url = base_url + file_name
                urllib.request.urlretrieve(url, str(file_path))
                logger.info(f"Descarga de {file_name} completada.")

    def _speaker_worker(self):
        """
        Bucle infinito del hilo demonio que procesa los mensajes de texto.
        PiperVoice y PyAudio se inicializan aquí dentro para ser thread-safe.
        """
        if not self.onnx_path.exists() or PiperVoice is None:
            logger.error("Motor de voz no disponible.")
            return

        # Cargar la voz en memoria
        logger.info("Cargando modelo neuronal en memoria...")
        voice = PiperVoice.load(str(self.onnx_path))
        sample_rate = voice.config.sample_rate
        
        # Iniciar el gestor de audio silenciando advertencias de ALSA/JACK
        with _silence_stderr():
            audio = pyaudio.PyAudio()
            try:
                stream = audio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=sample_rate,
                    output=True
                )
            except Exception:
                stream = None
        
        while self._running:
            try:
                # get() bloquea hasta que haya un elemento o pase el timeout
                text = self._queue.get(timeout=0.2)
                self.is_speaking = True
                logger.info(f"Viernes diciendo: '{text}'")
                
                # Usar stream persistente o reintentar abrir uno si falló
                local_stream = stream
                if local_stream is None:
                    with _silence_stderr():
                        local_stream = audio.open(format=pyaudio.paInt16,
                                                  channels=1,
                                                  rate=sample_rate,
                                                  output=True)
                
                # Piper sintetiza el audio y PyAudio lo reproduce
                config = None
                try:
                    from piper.config import SynthesisConfig
                    config = SynthesisConfig(length_scale=1.1, noise_scale=0.667, noise_w_scale=0.8)
                except ImportError:
                    pass

                for chunk in voice.synthesize(text, syn_config=config):
                    if not self._running:
                        break
                    local_stream.write(chunk.audio_int16_bytes)
                
                if stream is None and local_stream is not None:
                    local_stream.stop_stream()
                    local_stream.close()
                
                self._queue.task_done()
                
            except queue.Empty:
                self.is_speaking = False
                continue
            except Exception as e:
                logger.error(f"Error reproduciendo audio TTS: {e}")
            finally:
                self.is_speaking = False

        # Limpiar PyAudio al apagar
        with _silence_stderr():
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            audio.terminate()

    def _start_thread(self):
        """Inicia el hilo demonio."""
        self._running = True
        self._thread = threading.Thread(target=self._speaker_worker, daemon=True)
        self._thread.start()

    def speak(self, text: str):
        """
        Añade un texto a la cola de reproducción.
        Retorna instantáneamente sin bloquear el hilo principal.
        """
        if text and text.strip():
            self._queue.put(text.strip())

    def wait_until_done(self):
        """Bloquea hasta que todos los audios encolados hayan terminado de reproducirse."""
        self._queue.join()
        while self.is_speaking and self._running:
            time.sleep(0.05)

    def stop(self):
        """Detiene el hilo secundario limpiamente."""
        if not self._running:
            return
            
        self._running = False
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("VoiceSpeaker detenido.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    print("=========================================================")
    print(" Iniciando Prueba de VoiceSpeaker (Piper TTS Offline)")
    print("=========================================================\n")
    
    speaker = VoiceSpeaker()
    
    # Damos un breve instante para inicializar
    time.sleep(1)
    
    print("\n>> Enviando frases a la cola (no bloqueante)...")
    speaker.speak("Hola, soy Viernes. Estoy utilizando la voz neuronal Daniela de Argentina.")
    speaker.speak("Como podés escuchar, sueno mucho más natural y fluido.")
    speaker.speak("Además, este proceso es completamente asíncrono y offline.")
    
    print(">> Frases encoladas. Reproduciendo...\n")
    
    try:
        speaker.wait_until_done()
    except KeyboardInterrupt:
        print("\nInterrupción manual.")
    finally:
        speaker.stop()
        print("\nPrueba finalizada.")
