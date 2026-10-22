"""Módulo de Texto-a-Voz neuronal offline optimizado para latencia mínima (Piper TTS)."""

import logging
import threading
import queue
import time
import os
import contextlib
import urllib.request
import json
import re
from pathlib import Path
from typing import Optional

try:
    from piper.voice import PiperVoice
    import pyaudio
except ImportError:
    PiperVoice = None
    pyaudio = None

logger = logging.getLogger(__name__)


def cargar_diccionario_fonetico() -> dict[str, str]:
    """Carga dinámicamente el diccionario fonético JSON desde la misma carpeta que este archivo.
    Si el archivo no existe o falla la lectura, devuelve un diccionario vacío sin crashear.
    """
    ruta_json = Path(__file__).resolve().parent / "diccionario_fonetico.json"
    if not ruta_json.is_file():
        ruta_alt = Path(__file__).parent / "diccionario_fonetico.json"
        if ruta_alt.is_file():
            ruta_json = ruta_alt
        else:
            return {}
    try:
        with open(ruta_json, "r", encoding="utf-8") as f:
            datos = json.load(f)
            return datos if isinstance(datos, dict) else {}
    except Exception as e:
        logger.warning(f"No se pudo cargar el diccionario fonético ({ruta_json}): {e}")
        return {}


def limpiar_texto_para_tts(texto: str) -> str:
    """Limpia y optimiza el texto para síntesis TTS antes de pasarlo al motor de voz.

    Pasos en orden:
    1. Carga el JSON fonético (rutas absolutas).
    2. Aplica Pasada A del diccionario: términos con puntos o guiones, ANTES de que
       la limpieza de prosodia destruya esos caracteres (ej. F.R.I.D.A.Y., Node.js).
    3. Limpieza de Markdown: Elimina *, _, #, comillas y ~.
    4. Optimiza Prosodia (Puntuación):
       - Saltos de línea → espacio.
       - Puntos suspensivos (…/...) → coma.
       - Puntos normales intermedios → coma (sin tocar números decimales).
    5. Aplica Pasada B del diccionario: el resto de los términos (sin puntos/guiones).
    """
    if not texto or not isinstance(texto, str):
        return ""

    # 1. Cargar el JSON dinámicamente
    diccionario = cargar_diccionario_fonetico()

    # Separar entradas con puntos/guiones (Pasada A, pre-prosodia) del resto (Pasada B)
    if isinstance(diccionario, dict):
        diccionario = {k: v for k, v in diccionario.items() if not k.startswith("_")}
        terminos_con_simbolo = {k: v for k, v in diccionario.items() if "." in k or "-" in k}
        terminos_normales    = {k: v for k, v in diccionario.items() if "." not in k and "-" not in k}
    else:
        terminos_con_simbolo = {}
        terminos_normales    = {}

    def _aplicar_diccionario(txt: str, entradas: dict) -> str:
        for termino, pronunciacion in sorted(entradas.items(), key=lambda i: len(i[0]), reverse=True):
            if not termino:
                continue
            # Para términos con puntos o guiones, usamos coincidencia literal sin \b
            # porque los puntos/guiones no son word boundaries en regex
            if "." in termino or "-" in termino:
                txt = re.sub(re.escape(termino), pronunciacion, txt, flags=re.IGNORECASE)
            else:
                patron = rf"\b{re.escape(termino)}\b"
                txt = re.sub(patron, pronunciacion, txt, flags=re.IGNORECASE)
        return txt

    # 2. Pasada A: términos con puntos o guiones (antes de prosodia)
    texto = _aplicar_diccionario(texto, terminos_con_simbolo)

    # 3. Limpiar Markdown (* _ # " ' ~ ` “”‘’)
    texto = re.sub(r"[*_#\"~`\x27“”‘’]", "", texto)

    # 4. Optimizar Prosodia (Puntuación)
    # 4.1. Saltos de línea → espacio
    texto = re.sub(r"[\r\n]+", " ", texto)

    # 4.2. Puntos suspensivos → coma
    texto = re.sub(r"\.{3,}|…", ",", texto)

    # 4.3. Puntos normales intermedios → coma (proteger números decimales)
    texto = re.sub(r"\.(?=\s*\S)(?!\d)", ",", texto)

    # 5. Pasada B: términos sin puntos/guiones
    texto = _aplicar_diccionario(texto, terminos_normales)

    return texto.strip()



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

    def __init__(
        self,
        models_dir: Optional[Path] = None,
        model_name: str = "es_AR-daniela-high",
        length_scale: float = 1.18,
    ):
        """
        :param models_dir:   Directorio donde se guardan los modelos Piper.
        :param model_name:   Nombre del modelo de voz.
        :param length_scale: Escala de duración de fonemas (>1.0 más pausado y explicativo, <1.0 más rápido).
        """
        if PiperVoice is None or pyaudio is None:
            logger.error("Faltan dependencias. Ejecuta: uv pip install piper-tts PyAudio")

        if models_dir is None:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            models_dir = project_root / "assets" / "voices"

        models_dir.mkdir(parents=True, exist_ok=True)

        self.model_name = model_name
        self.length_scale = length_scale
        self.onnx_path = models_dir / f"{self.model_name}.onnx"
        self.json_path = models_dir / f"{self.model_name}.onnx.json"

        # Cola de oraciones pendientes para TTS.
        # Un maxsize generoso permite que el LLM envíe varias oraciones sin
        # descartar las intermedias; interrupt() vacía la cola al detectar
        # nueva intervención del usuario.
        self._queue: queue.Queue[Optional[str]] = queue.Queue(maxsize=30)
        self._running = False
        self.is_speaking = False
        self._last_spoken_time = 0.0
        self._interrupted = threading.Event()  # Flag para cortar síntesis mid-chunk

        # SynthesisConfig pre-instanciado (fuera del loop)
        self._syn_config = self._build_syn_config(length_scale=self.length_scale)

        self._start_thread()
        logger.info(f"VoiceSpeaker ({self.model_name}, length_scale={self.length_scale}) iniciado.")

    # -----------------------------------------------------------------------
    # Config de síntesis (creada una sola vez)
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_syn_config(length_scale: float = 1.18):
        """Crea la configuración de síntesis. Devuelve None si no está disponible."""
        try:
            from piper.config import SynthesisConfig
            # length_scale > 1.0 → habla más pausada, articulada y didáctica
            # noise_scale 0.667 → más natural | noise_w_scale 0.8 → fonemas estables
            return SynthesisConfig(length_scale=length_scale, noise_scale=0.667, noise_w_scale=0.8)
        except ImportError:
            return None

    def set_speed(self, length_scale: float) -> None:
        """Ajusta la velocidad de habla dinámicamente (>1.0 más pausado/explicativo, <1.0 más rápido)."""
        self.length_scale = length_scale
        self._syn_config = self._build_syn_config(length_scale=length_scale)
        logger.info(f"Velocidad de habla actualizada a length_scale={length_scale}")


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

                if not text.strip():
                    self._queue.task_done()
                    continue

                self._interrupted.clear()
                self.is_speaking = True
                logger.info(f"TTS sintetizando: '{text[:60]}{'...' if len(text)>60 else ''}'")

                if stream is not None:
                    try:
                        for chunk in voice.synthesize(text, syn_config=self._syn_config):
                            if not self._running or self._interrupted.is_set():
                                logger.info("[TTS] Síntesis interrumpida mid-chunk.")
                                break
                            stream.write(chunk.audio_int16_bytes)
                    except Exception as e:
                        logger.error(f"Error sintetizando: {e}")

                self._queue.task_done()
                self._last_spoken_time = time.time()
                self.is_speaking = False

            except queue.Empty:
                self.is_speaking = False
            except Exception as e:
                logger.error(f"Error en speaker worker: {e}")
                self._last_spoken_time = time.time()
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
        text = limpiar_texto_para_tts(text)
        if not text:
            return
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
        """Interrumpe la síntesis en curso (mid-chunk) y vacía la cola de audio pendiente."""
        self._interrupted.set()  # Corta el chunk que se está reproduciendo
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break

    def is_active(self, cooldown_seconds: float = 0.8) -> bool:
        """
        Retorna True si el altavoz está reproduciendo audio o si terminó hace menos
        de cooldown_seconds (evita que el micrófono capture el eco ambiental).
        """
        if self.is_speaking or not self._queue.empty():
            return True
        if (time.time() - self._last_spoken_time) < cooldown_seconds:
            return True
        return False

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
