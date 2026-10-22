"""Escuchador de micrófono optimizado con Whisper local precargado y filtrado anti-alucinaciones."""

import io
import logging
import re
import subprocess
import threading
from typing import Callable, Optional

import numpy as np
import soundfile as sf
import speech_recognition as sr
import torch
import whisper

logger = logging.getLogger(__name__)


# Frases comunes que Whisper alucina cuando recibe ruido ambiental o silencio
HALLUCINATION_PATTERNS = [
    re.compile(r"subt[ií]tulos\s+por", re.IGNORECASE),
    re.compile(r"subt[ií]tulos\s+realizados", re.IGNORECASE),
    re.compile(r"amara\.org", re.IGNORECASE),
    re.compile(r"comunidad\s+de\s+amara", re.IGNORECASE),
    re.compile(r"suscr[ií]bete", re.IGNORECASE),
    re.compile(r"gracias\s+por\s+ver", re.IGNORECASE),
    re.compile(r"transcripci[oó]n\s+por", re.IGNORECASE),
    re.compile(r"hasta\s+la\s+pr[oó]xima", re.IGNORECASE),
    re.compile(r"chau\s+chau", re.IGNORECASE),
]


def _find_pipewire_source(name_fragment: str) -> Optional[str]:
    """
    Busca en las fuentes de PipeWire/PulseAudio una que contenga ``name_fragment``.
    Incluye tanto fuentes directas como monitores de sinks (.monitor).
    Prefiere fuentes sin '.monitor' si las hay (ej: micrófono ALSA),
    pero para dispositivos como AudioRelay el '.monitor' es la entrada correcta.
    Devuelve el nombre exacto de la fuente si la encuentra, o None.
    """
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources", "short"],
            text=True, stderr=subprocess.DEVNULL
        )
        needle = name_fragment.lower()
        candidates = []
        for line in out.splitlines():
            # línea: <idx> <nombre> <driver> <formato> <estado>
            parts = line.split()
            if len(parts) >= 2 and needle in parts[1].lower():
                candidates.append(parts[1])
        if not candidates:
            return None
        # Para sink-virtuales como AudioRelay, solo existe el .monitor como fuente.
        # Si hay fuentes sin .monitor, preferirlas; sino, usar el .monitor.
        non_monitors = [c for c in candidates if not c.endswith(".monitor")]
        monitors     = [c for c in candidates if c.endswith(".monitor")]
        return non_monitors[0] if non_monitors else monitors[0]
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    return None


def _set_default_pipewire_source(source_name: str) -> bool:
    """
    Setea la fuente de audio default en PulseAudio/PipeWire.
    Si falla (ej: el nombre es un sink, no una source), reintenta con
    '<nombre>.monitor' que sí existe como fuente en PipeWire.
    Devuelve True si alguno de los intentos tuvo éxito.
    """
    for candidate in [source_name, source_name + ".monitor"]:
        try:
            subprocess.run(
                ["pactl", "set-default-source", candidate],
                check=True, stderr=subprocess.DEVNULL
            )
            logger.info(f"Fuente PipeWire default seteada: {candidate}")
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    logger.warning(f"No se pudo setear fuente default en PipeWire para '{source_name}'")
    return False


def _safe_get_audio_devices() -> List[tuple[int, str]]:
    """
    Obtiene la lista de dispositivos de entrada (micrófonos) de forma segura.
    Evita llamar a sr.Microphone.list_microphone_names() que causa SIGSEGV
    en Linux/ALSA al inspeccionar salidas de audio sin canales de entrada.
    """
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        devices = []
        try:
            count = p.get_device_count()
            for i in range(count):
                try:
                    info = p.get_device_info_by_index(i)
                    if info and info.get("maxInputChannels", 0) > 0:
                        name = info.get("name", "")
                        if name:
                            devices.append((i, name))
                except Exception:
                    continue
            return devices
        finally:
            try:
                p.terminate()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Error accediendo a PyAudio: {e}")
        return []


def find_microphone_index(name_fragment: str) -> Optional[int]:
    """
    Busca el micrófono por nombre de forma segura y robusta:
    1. Si es un dispositivo PipeWire/PulseAudio (como AudioRelay), lo configura como
       fuente default del sistema y retorna el índice del backend 'pulse' o None (default).
    2. Si no, busca entre los dispositivos de entrada válidos de PyAudio.
    """
    if not name_fragment:
        return None

    needle = name_fragment.lower()

    # --- Paso 1: PipeWire / PulseAudio (ej: AudioRelay, micrófonos virtuales) ---
    pw_source = _find_pipewire_source(name_fragment)
    if pw_source:
        logger.info(f"Fuente PipeWire encontrada: '{pw_source}'")
        _set_default_pipewire_source(pw_source)
        logger.info(f"Audio configurado para capturar desde '{pw_source}' vía default del sistema.")
        return None

    # --- Paso 2: buscar en dispositivos PyAudio físicos de entrada ---
    devices = _safe_get_audio_devices()
    for idx, name in devices:
        if needle in name.lower():
            logger.info(f"Micrófono '{name_fragment}' encontrado en PyAudio → índice {idx}: {name}")
            return idx

    logger.warning(
        f"No se encontró micrófono con '{name_fragment}'. Usando dispositivo por defecto del sistema."
    )
    return None


class VoiceListener:
    """
    Escucha continua del micrófono en segundo plano usando Whisper local precargado.

    Mejoras:
    - Precarga del modelo Whisper en memoria (evita 1-2s de torch.load por frase).
    - Descarte de audio mientras el altavoz TTS de Viernes está activo (anti-eco).
    - Filtrado de alucinaciones típicas de Whisper en silencio/ruido.
    - initial_prompt orientado a contexto de Viernes / CrumbSkate / Kippu.
    - Determinismo temperature=0.0 para evitar invenciones con ruido de fondo.
    """

    def __init__(
        self,
        on_speech_detected: Callable[[str], None],
        language: str = "es",
        model_size: str = "small",
        energy_threshold: int = 0,
        pause_threshold: float = 0.8,
        phrase_threshold: float = 0.25,
        calibration_duration: float = 1.0,
        device_index: Optional[int] = None,
        mute_check: Optional[Callable[[], bool]] = None,
        initial_prompt: str = (
            "Hola Viernes. Conversación en español argentino. "
            "Comandos: foto, captura, zoom, mover, izquierda, derecha, arriba, abajo, "
            "mostrar, buscar, qué ves, panés, CrumbSkate, Kippu, Viernes. "
            "Responde en español."
        ),
    ):
        """
        :param on_speech_detected:   Callback invocado con el texto transcripto.
        :param language:             Idioma para Whisper ('es' para español).
        :param model_size:           Tamaño del modelo Whisper ('tiny', 'base', 'small').
        :param energy_threshold:     Umbral mínimo de energía para detectar voz.
        :param pause_threshold:      Segundos de silencio para cerrar una frase.
        :param phrase_threshold:     Duración mínima de sonido para considerarlo frase (350ms).
        :param calibration_duration: Segundos de calibración de ruido ambiente al inicio.
        :param device_index:         Índice del dispositivo de micrófono. None = default.
        :param mute_check:           Función que devuelve True si el micrófono debe ignorarse (anti-eco).
        :param initial_prompt:       Prompt de sesgo léxico para Whisper.
        """
        self.on_speech_detected = on_speech_detected
        self.language = language
        self.model_size = model_size
        self.initial_prompt = initial_prompt
        self.mute_check = mute_check
        self.configured_energy_threshold = energy_threshold

        # Precargar modelo Whisper en memoria una sola vez
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Cargando modelo Whisper '{self.model_size}' en {self.device}...")
        self.whisper_model = whisper.load_model(self.model_size, device=self.device)
        logger.info(f"Modelo Whisper '{self.model_size}' listo.")

        self.recognizer = sr.Recognizer()
        # No forzamos sample_rate=16000 en el constructor: el backend pulse/ALSA
        # puede crashear (SIGSEGV) si no lo soporta. En cambio, resampleamos a
        # 16kHz en el callback antes de pasarlo a Whisper.
        self.microphone = sr.Microphone(device_index=device_index)
        logger.info(
            f"Micrófono: índice={device_index if device_index is not None else 'default'} (tasa nativa, resampleo a 16kHz en callback)"
        )

        # Parámetros del reconocedor
        self.recognizer.pause_threshold = pause_threshold
        self.recognizer.phrase_threshold = 0.25  # 250ms mínimos de voz
        self.recognizer.non_speaking_duration = 0.5  # 500ms previos conservados para no recortar la primera sílaba
        # Desactivar ajuste dinámico durante escucha: evita que el threshold se infle mientras hablás
        self.recognizer.dynamic_energy_threshold = False

        self._stop_listening_func = None
        self._is_listening = False

        self._calibrate(calibration_duration)

    def _calibrate(self, duration: float) -> None:
        """Calibra el ruido de fondo y establece un umbral estable por encima del piso acústico."""
        logger.info(f"Calibrando ruido de fondo ({duration}s)...")
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=duration)
            ambient = self.recognizer.energy_threshold

            if self.configured_energy_threshold > 0:
                self.recognizer.energy_threshold = float(self.configured_energy_threshold)
                logger.info(f"Calibración: piso={ambient:.0f} | Umbral manual fijado: {self.recognizer.energy_threshold:.0f}")
            else:
                # Umbral adaptado: 25% por encima del ruido ambiente + margen de seguridad
                effective = max(ambient * 1.25, ambient + 30.0)
                # Acotar entre un piso mínimo (60) y máximo sensato (500)
                self.recognizer.energy_threshold = max(60.0, min(effective, 500.0))
                logger.info(f"Calibración: piso={ambient:.0f} | Umbral automático fijado: {self.recognizer.energy_threshold:.0f}")

            self.recognizer.dynamic_energy_threshold = False
        except AttributeError:
            logger.error("No se pudo abrir el micrófono (ALSA locked/no device).")
        except Exception as e:
            logger.warning(f"Aviso durante calibración: {e}")

    @staticmethod
    def _is_valid_speech(text: str) -> bool:
        """Filtra alucinaciones conocidas de Whisper y ruidos cortos."""
        clean = text.strip()
        # Requiere al menos 2 caracteres alfanuméricos
        alphanumeric = re.sub(r"[^\w\s]", "", clean, flags=re.UNICODE).strip()
        if len(alphanumeric) < 2:
            return False

        # Rechazar alucinaciones típicas
        lower = clean.lower()
        for pat in HALLUCINATION_PATTERNS:
            if pat.search(lower):
                return False

        return True

    def _audio_callback(self, recognizer: sr.Recognizer, audio: sr.AudioData) -> None:
        """
        Callback interno ejecutado en el hilo secundario al detectar fin de frase.
        Aplica AGC (Control Automático de Ganancia) y transcribe con Whisper.
        """
        # Anti-eco previo: si el altavoz está activo, ignorar de inmediato
        if self.mute_check and self.mute_check():
            logger.debug("[STT] Audio ignorado: altavoz/sistema ocupado (anti-eco).")
            return

        logger.info("[STT] Voz detectada en el micrófono, transcribiendo con Whisper...")
        try:
            raw_bytes = audio.get_raw_data()
            audio_array = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            if audio_array.ndim > 1:
                audio_array = np.mean(audio_array, axis=1)

            # Resamplear a 16kHz si el micrófono captó a una tasa diferente
            src_rate = audio.sample_rate
            if src_rate != 16000 and src_rate > 0:
                target_len = int(len(audio_array) * 16000 / src_rate)
                audio_array = np.interp(
                    np.linspace(0, len(audio_array) - 1, target_len),
                    np.arange(len(audio_array)),
                    audio_array,
                ).astype(np.float32)
                logger.debug(f"[STT] Resampleado: {src_rate}Hz → 16000Hz ({len(audio_array)} muestras)")

            # Normalización y Control Automático de Ganancia (AGC):
            # Micrófonos como AudioRelay suelen enviar audio con volumen muy bajo.
            # Normalizamos el pico a 0.7 para que Whisper reciba una señal limpia y nítida.
            max_val = float(np.max(np.abs(audio_array)))
            if max_val > 0.003:
                gain = min(0.7 / max_val, 15.0)
                audio_array = audio_array * gain

            # Volver a chequear por si el altavoz arrancó durante la captura
            if self.mute_check and self.mute_check():
                logger.debug("[STT] Audio descartado: altavoz se activó durante captura.")
                return

            result = self.whisper_model.transcribe(
                audio_array,
                language=self.language,
                initial_prompt=self.initial_prompt,
                temperature=(0.0, 0.2),
                condition_on_previous_text=False,
                no_speech_threshold=0.5,
                compression_ratio_threshold=2.4,
                logprob_threshold=-0.5,
                fp16=False,
            )

            # Chequeo anti-eco post inferencia
            if self.mute_check and self.mute_check():
                logger.debug("[STT] Transcripción descartada: altavoz activo post-inferencia.")
                return

            text = result.get("text", "").strip()

            if text and self._is_valid_speech(text):
                logger.info(f"[STT] Transcripto: '{text}'")
                self.on_speech_detected(text)
            elif text:
                logger.debug(f"[STT] Descartado por filtro anti-alucinación: '{text}'")
            else:
                logger.debug("[STT] Audio descartado por Whisper (no_speech detectado).")

        except Exception as e:
            logger.error(f"Excepción procesando audio: {e}")

    def start(self) -> None:
        """Inicia la escucha continua en background (no bloqueante)."""
        if self._is_listening:
            logger.warning("VoiceListener ya está en ejecución.")
            return

        logger.info("Iniciando escucha continua...")
        try:
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

    listener = VoiceListener(on_speech_detected=on_speech, model_size="small")

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
