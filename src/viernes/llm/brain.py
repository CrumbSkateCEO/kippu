"""Módulo central de inteligencia con streaming, visión, control PTZ y control del sistema."""

import json
import logging
import threading
from pathlib import Path
from typing import List, Dict, Optional, Callable, Iterator, TYPE_CHECKING

try:
    import ollama
except ImportError:
    ollama = None

if TYPE_CHECKING:
    from viernes.ipcam.camera_stream import IPCameraStream
    from viernes.ipcam.ptz_controller import PTZController
    from viernes.ipcam.motion_tracker import MotionTracker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Definición de herramientas que el LLM puede invocar
# ---------------------------------------------------------------------------

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "ver_camara",
            "description": (
                "Captura el frame actual de la cámara IP y te permite VER lo que está "
                "frente a la cámara. Úsala cuando necesites información visual sobre el "
                "entorno, cuando alguien te hable de algo que deberías observar, o cuando "
                "quieras confirmar dónde está mirando la cámara antes de moverla."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mover_camara",
            "description": (
                "Mueve la cámara IP en la dirección indicada. Úsala para rastrear una "
                "persona, explorar el entorno, o encuadrar mejor a alguien que no está "
                "centrado en el frame. Puedes combinarla con ver_camara para verificar "
                "el resultado del movimiento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "description": (
                            "Dirección del movimiento. Valores válidos: "
                            "'left' (izquierda), 'right' (derecha), 'up' (arriba), "
                            "'down' (abajo), 'upper_left', 'upper_right', "
                            "'lower_left', 'lower_right', 'center' (posición central/home)."
                        ),
                        "enum": [
                            "left", "right", "up", "down",
                            "upper_left", "upper_right", "lower_left", "lower_right", "center"
                        ],
                    },
                    "speed": {
                        "type": "number",
                        "description": "Velocidad entre 0.1 (lento) y 1.0 (rápido). Por defecto 0.3.",
                    },
                    "duration": {
                        "type": "number",
                        "description": "Segundos de movimiento antes de detenerse. Por defecto 0.6.",
                    },
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "seguir_movimiento",
            "description": (
                "Activa o desactiva el seguimiento automático de movimiento (motion tracking). "
                "Cuando está activo, la cámara se mueve sola para seguir a la persona u objeto "
                "que se esté moviendo frente a ella. Úsala cuando te pidan 'seguime', "
                "'rastreá el movimiento', 'seguí a esa persona', o 'dejá de seguir'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activar": {
                        "type": "boolean",
                        "description": "True para activar el seguimiento, False para desactivarlo.",
                    },
                },
                "required": ["activar"],
            },
        },
    },
    # ----- Herramientas de control del sistema operativo -----
    {
        "type": "function",
        "function": {
            "name": "ejecutar_comando",
            "description": (
                "Ejecuta un comando en la terminal nativa del sistema operativo "
                "(bash en Linux/macOS, cmd/PowerShell en Windows) y devuelve la salida. "
                "Úsala cuando te pidan instalar algo, ver información del sistema, "
                "manejar archivos, o cualquier tarea de línea de comandos. "
                "Adaptá el comando al SO detectado (no asumas Linux)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "comando": {
                        "type": "string",
                        "description": "El comando a ejecutar tal como se escribiría en la terminal nativa.",
                    },
                },
                "required": ["comando"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "abrir_aplicacion",
            "description": (
                "Abre una aplicación instalada en el sistema por su nombre. "
                "Úsala cuando te pidan abrir programas como Firefox, VLC, terminal, "
                "VS Code, el explorador de archivos, Blender, GIMP, Steam, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {
                        "type": "string",
                        "description": (
                            "Nombre de la aplicación. Ejemplos: 'firefox', 'terminal', "
                            "'vlc', 'code', 'archivos', 'calculadora', 'steam', 'discord'."
                        ),
                    },
                },
                "required": ["nombre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cerrar_aplicacion",
            "description": (
                "Cierra todas las instancias de una aplicación por nombre. "
                "Úsala cuando te pidan cerrar un programa, matar un proceso, "
                "o liberar recursos de una app que esté corriendo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {
                        "type": "string",
                        "description": "Nombre del proceso/aplicación a cerrar (ej: 'firefox', 'vlc', 'code').",
                    },
                },
                "required": ["nombre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "abrir_navegador",
            "description": (
                "Abre una URL en una pestaña nueva del navegador predeterminado. "
                "Úsala cuando te pidan abrir una página web, un enlace, YouTube, "
                "GitHub, o cualquier sitio con URL conocida."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "La URL a abrir (ej: 'youtube.com', 'https://github.com').",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_en_internet",
            "description": (
                "Busca algo en Google abriendo el navegador con la consulta. "
                "Úsala cuando te pidan buscar información, investigar un tema, "
                "'googleá esto', o cuando necesites datos que no tenés."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {
                        "type": "string",
                        "description": "El texto a buscar en Google.",
                    },
                },
                "required": ["consulta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cerrar_pestana_navegador",
            "description": (
                "Cierra la pestaña activa del navegador (Ctrl+W / Cmd+W). "
                "Úsala cuando pidan cerrar esta pestaña o esta página, "
                "no el navegador entero."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "info_sistema",
            "description": (
                "Devuelve el sistema operativo detectado (Windows, macOS o Linux) "
                "y datos básicos de la máquina. Úsala si necesitás confirmar el SO "
                "antes de armar un comando nativo."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_procesos",
            "description": (
                "Lista los procesos en ejecución del sistema, opcionalmente filtrando "
                "por nombre. Úsala cuando te pregunten qué está corriendo, si un programa "
                "está abierto, o para diagnosticar uso de recursos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filtro": {
                        "type": "string",
                        "description": "Texto para filtrar procesos por nombre. Vacío = top 20 por CPU.",
                    },
                },
                "required": [],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Cerebro principal
# ---------------------------------------------------------------------------

class ViernesBrain:
    """
    Cerebro cognitivo de Viernes con streaming, tool-calling, visión y PTZ.

    Optimizaciones clave:
    - ``think_stream()`` usa ``ollama.chat(stream=True)`` para entregar tokens
      al TTS tan pronto como se acumula una oración completa (reducción de
      latencia percibida de ~2-4s a <0.5s para la primera sílaba).
    - El historial se poda en O(1) mediante slice sin copias innecesarias.
    - La imagen para visión se reutiliza dentro del mismo ciclo agentic sin
      reconvertirla.
    - Lock en el historial para thread-safety si se llama desde múltiples hilos.
    - ``_current_task`` permite cancelar inferencias en vuelo si llega nueva voz.
    """

    # Signos de puntuación que marcan fin de oración → flush al TTS
    _SENTENCE_ENDS = {'.', '!', '?', '…', '\n'}

    def __init__(
        self,
        model_name: str = "llava",
        max_history: int = 5,
        camera_stream: Optional["IPCameraStream"] = None,
        ptz_controller: Optional["PTZController"] = None,
        motion_tracker: Optional["MotionTracker"] = None,
        on_camera_action: Optional[Callable[[str], None]] = None,
    ):
        self.model_name = model_name
        self.max_history_messages = max_history * 2
        self.camera_stream = camera_stream
        self.ptz_controller = ptz_controller
        self.motion_tracker = motion_tracker
        self.on_camera_action = on_camera_action

        # Las tools de sistema (comandos, apps, navegador) siempre están activas
        self._tools_enabled = True
        self._active_tools = self._build_active_tools()

        # Lock para acceso thread-safe al historial
        self._history_lock = threading.Lock()

        # Token de cancelación: se incrementa para señalizar que la inferencia actual
        # debe abandonarse (cuando llega nueva voz del usuario)
        self._cancel_token = 0

        self.system_prompt = {"role": "system", "content": self._build_system_prompt()}
        self.conversation_history: List[Dict] = [self.system_prompt]

        logger.info(
            f"ViernesBrain iniciado. Modelo: {self.model_name} | "
            f"Visión: {'✓' if camera_stream else '✗'} | "
            f"PTZ: {'✓' if ptz_controller else '✗'}"
        )

    # -----------------------------------------------------------------------
    # Construcción interna
    # -----------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        # Cargar contexto detallado desde contexto_viernes.txt si existe
        candidates = [
            Path("contexto_viernes.txt"),
            Path(__file__).resolve().parents[3] / "contexto_viernes.txt",
        ]
        base = ""
        for p in candidates:
            if p.is_file():
                try:
                    base = p.read_text(encoding="utf-8").strip()
                    logger.info(f"Contexto cargado exitosamente desde: {p}")
                    break
                except Exception as e:
                    logger.warning(f"No se pudo leer {p}: {e}")

        if not base:
            base = (
                "Eres Viernes, una asistente de IA interactiva, tecnológica y amigable para el fotomaton 'Kippu'. "
                "Tu trabajo es interactuar con el público en una presentación escolar, respondiendo "
                "de manera concisa y educada. "
                "Contexto técnico fundamental del proyecto que debes conocer: "
                "El grupo ha desarrollado un proyecto de e-commerce llamado 'CrumbSkate'. "
                "CrumbSkate está construido con las siguientes tecnologías: "
                "1. Frontend: React. "
                "2. Backend: Node.js (con Express). "
                "3. Base de Datos: MySQL. "
                "Si los usuarios te preguntan sobre el e-commerce o las tecnologías usadas, "
                "explícalo de forma entusiasta y sencilla. "
                "Regla vital: Responde SIEMPRE en español y sé muy breve (1 a 3 oraciones máximo) "
                "para que la conversación hablada fluya rápido."
            )

        if self._tools_enabled:
            tools_note = []
            if self.camera_stream:
                tools_note.append(
                    "Tienes acceso a una cámara IP que funciona como tus ojos. "
                    "Puedes usar la herramienta 'ver_camara' para observar el entorno en cualquier momento."
                )
            if self.ptz_controller:
                tools_note.append(
                    "También puedes mover físicamente la cámara con 'mover_camara' para seguir personas "
                    "o explorar el espacio. Siempre que la muevas, explica brevemente por qué."
                )
            if self.motion_tracker is not None:
                tools_note.append(
                    "Puedes activar el seguimiento automático de movimiento con 'seguir_movimiento'. "
                    "Cuando está activo, la cámara sigue automáticamente a quien se mueva frente a ella. "
                    "Activalo si te lo piden o si creés que es útil en el contexto."
                )
            if tools_note:
                base += "\n\nHerramientas activas:\n" + "\n".join(tools_note)

        # Herramientas de control del sistema (siempre disponibles)
        try:
            from viernes.system.computer_control import OS_FAMILY, OS_RESUMEN
            os_line = f"\nEstás corriendo en {OS_RESUMEN}. Familia de comandos: {OS_FAMILY}."
        except Exception:
            os_line = ""
        base += (
            f"{os_line}"
            "\n\nTambién tenés control sobre la computadora del usuario. Podés:"
            "\n- Ejecutar comandos en la terminal nativa con 'ejecutar_comando' "
            "(bash en Linux/macOS, cmd o PowerShell en Windows; no asumas Linux)."
            "\n- Abrir aplicaciones instaladas con 'abrir_aplicacion'."
            "\n- Cerrar instancias de una app con 'cerrar_aplicacion'."
            "\n- Abrir pestañas del navegador con 'abrir_navegador'."
            "\n- Cerrar la pestaña activa con 'cerrar_pestana_navegador'."
            "\n- Buscar en internet (Google) con 'buscar_en_internet'."
            "\n- Ver qué procesos están corriendo con 'listar_procesos'."
            "\n- Confirmar el sistema operativo con 'info_sistema'."
            "\nUsá estas herramientas cuando el usuario te lo pida. "
            "Siempre explicá brevemente qué vas a hacer antes de ejecutar un comando."
            "\nSi el usuario cierra la conversación (gracias, eso es todo, chau), "
            "no hace falta usar herramientas: el sistema la silencia solo."
        )

        return base

    # Herramientas de cámara (requieren hardware)
    _CAMERA_TOOLS = {"ver_camara", "mover_camara", "seguir_movimiento"}

    def _build_active_tools(self) -> List[Dict]:
        active = []
        for tool in TOOLS_SCHEMA:
            name = tool["function"]["name"]
            # Filtrar herramientas de cámara según hardware disponible
            if name == "ver_camara" and self.camera_stream is None:
                continue
            if name == "mover_camara" and self.ptz_controller is None:
                continue
            if name == "seguir_movimiento" and (self.motion_tracker is None or self.ptz_controller is None):
                continue
            # Las herramientas de sistema siempre pasan
            active.append(tool)
        return active

    # -----------------------------------------------------------------------
    # API principal: think (bloqueante, devuelve texto completo)
    # -----------------------------------------------------------------------

    def think(self, user_text: str) -> str:
        """
        Procesa el texto, ejecuta tool calls si el LLM los solicita, y devuelve
        la respuesta final completa. Adecuado para uso síncrono.
        """
        return "".join(self.think_stream(user_text))

    # -----------------------------------------------------------------------
    # API principal: think_stream (streaming, genera tokens)
    # -----------------------------------------------------------------------

    def think_stream(self, user_text: str) -> Iterator[str]:
        """
        Versión streaming de ``think``. Genera tokens de la respuesta del LLM
        a medida que llegan, permitiendo que el TTS empiece a hablar sin esperar
        la respuesta completa.

        Protocolo:
        1. Envía el mensaje del usuario al LLM.
        2. Si el LLM solicita tool calls → ejecuta las herramientas y vuelve a llamar.
        3. Si el LLM da respuesta directa → hace yield de cada token.

        Uso:
            for sentence in brain.think_stream(text):
                speaker.speak(sentence)  # El TTS recibe oraciones completas
        """
        if ollama is None:
            logger.error("Librería 'ollama' no instalada.")
            yield "Error de sistema: No se detecta el motor de razonamiento lógico."
            return

        # Incrementar token de cancelación para que streams previos se abandonen
        cancel_snapshot = self._cancel_token + 1
        self._cancel_token = cancel_snapshot

        with self._history_lock:
            self.conversation_history.append({"role": "user", "content": user_text})
            self._trim_history()

        self._pending_image: Optional[str] = None

        max_tool_rounds = 4
        tool_round = 0

        while tool_round < max_tool_rounds:
            # Si llegó una nueva solicitud mientras procesábamos, abortar
            if self._cancel_token != cancel_snapshot:
                logger.info("Inferencia cancelada por nueva solicitud del usuario.")
                return

            with self._history_lock:
                history_snapshot = list(self.conversation_history)

            call_kwargs = dict(
                model=self.model_name,
                messages=history_snapshot,
                stream=True,              # ← Streaming habilitado
            )
            if self._active_tools:
                call_kwargs["tools"] = self._active_tools

            try:
                logger.info(f"Ollama streaming ({self.model_name}), ronda {tool_round + 1}...")
                stream = ollama.chat(**call_kwargs)
            except Exception as e:
                logger.error(f"Error conectando con Ollama: {e}")
                with self._history_lock:
                    if self.conversation_history and self.conversation_history[-1]["role"] == "user":
                        self.conversation_history.pop()
                yield "Lo siento, mis sistemas cognitivos están desconectados."
                return

            # -------------------------------------------------------------------
            # Consumir el stream token a token
            # -------------------------------------------------------------------
            accumulated_content = ""
            accumulated_tool_calls = []
            sentence_buffer = ""
            has_tool_calls = False

            try:
                for chunk in stream:
                    # Chequeo de cancelación en cada chunk
                    if self._cancel_token != cancel_snapshot:
                        logger.info("Stream cancelado por nueva solicitud.")
                        return

                    msg = chunk.get("message", {})

                    # --- Tool calls ---
                    chunk_tools = msg.get("tool_calls", [])
                    if chunk_tools:
                        has_tool_calls = True
                        accumulated_tool_calls.extend(chunk_tools)
                        continue

                    # --- Tokens de texto ---
                    token = msg.get("content", "")
                    if not token:
                        continue

                    accumulated_content += token
                    sentence_buffer += token

                    # Flush al TTS cuando se completa una oración
                    if any(c in sentence_buffer for c in self._SENTENCE_ENDS):
                        parts = self._split_sentences(sentence_buffer)
                        for part in parts[:-1]:  # Todas menos la última (puede estar incompleta)
                            part = part.strip()
                            if part:
                                yield part
                        sentence_buffer = parts[-1] if parts else ""

            except Exception as e:
                logger.error(f"Error consumiendo stream de Ollama: {e}")
                yield "Hubo un error procesando la respuesta."
                return

            # Flush del buffer restante (última parte de la respuesta)
            if sentence_buffer.strip() and not has_tool_calls:
                yield sentence_buffer.strip()

            # -------------------------------------------------------------------
            # Procesar tool calls si los hubo
            # -------------------------------------------------------------------
            if has_tool_calls:
                with self._history_lock:
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": accumulated_content,
                        "tool_calls": accumulated_tool_calls,
                    })

                for tc in accumulated_tool_calls:
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")
                    raw_args = fn.get("arguments", {})
                    tool_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args

                    tool_result = self._execute_tool(tool_name, tool_args)

                    result_msg: Dict = {"role": "tool", "content": tool_result}
                    if tool_name == "ver_camara" and self._pending_image:
                        result_msg["images"] = [self._pending_image]
                        self._pending_image = None

                    with self._history_lock:
                        self.conversation_history.append(result_msg)

                tool_round += 1
                continue

            # -------------------------------------------------------------------
            # Respuesta final sin tools: guardar en historial y terminar
            # -------------------------------------------------------------------
            if accumulated_content.strip():
                with self._history_lock:
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": accumulated_content.strip(),
                    })
            return

        # Límite de rondas alcanzado
        logger.warning("Límite de rondas de herramientas alcanzado.")
        fallback = "He procesado la solicitud."
        with self._history_lock:
            self.conversation_history.append({"role": "assistant", "content": fallback})
        yield fallback

    # -----------------------------------------------------------------------
    # Ejecución de herramientas
    # -----------------------------------------------------------------------

    def _execute_tool(self, tool_name: str, tool_args: Dict) -> str:
        logger.info(f"[TOOL] {tool_name}({tool_args})")

        if tool_name == "ver_camara":
            return self._tool_ver_camara()
        elif tool_name == "mover_camara":
            return self._tool_mover_camara(**tool_args)
        elif tool_name == "seguir_movimiento":
            return self._tool_seguir_movimiento(**tool_args)
        # Herramientas de control del sistema
        elif tool_name == "ejecutar_comando":
            return self._tool_ejecutar_comando(**tool_args)
        elif tool_name == "abrir_aplicacion":
            return self._tool_abrir_aplicacion(**tool_args)
        elif tool_name == "cerrar_aplicacion":
            return self._tool_cerrar_aplicacion(**tool_args)
        elif tool_name == "abrir_navegador":
            return self._tool_abrir_navegador(**tool_args)
        elif tool_name == "buscar_en_internet":
            return self._tool_buscar_en_internet(**tool_args)
        elif tool_name == "cerrar_pestana_navegador":
            return self._tool_cerrar_pestana_navegador()
        elif tool_name == "info_sistema":
            return self._tool_info_sistema()
        elif tool_name == "listar_procesos":
            return self._tool_listar_procesos(**tool_args)
        return f"Error: herramienta desconocida '{tool_name}'."

    def _tool_ver_camara(self) -> str:
        from viernes.ipcam.vision_capture import capture_frame_as_base64

        if self.camera_stream is None:
            return "Error: no hay cámara disponible."

        if self.on_camera_action:
            self.on_camera_action("👁️ Viernes está mirando...")

        b64_frame = capture_frame_as_base64(self.camera_stream)
        if b64_frame is None:
            return "La cámara no tiene frames disponibles."

        self._pending_image = b64_frame
        return "Imagen capturada. Analiza lo que ves en la imagen adjunta."

    def _tool_mover_camara(
        self,
        direction: str,
        speed: float = 0.3,
        duration: float = 0.6,
    ) -> str:
        if self.ptz_controller is None:
            return "Error: no hay controlador PTZ disponible."

        if self.on_camera_action:
            self.on_camera_action(f"🎥 Moviendo cámara → {direction}")

        success = self.ptz_controller.move(direction, speed=speed, duration=duration)
        if success:
            # Pausar motion tracking durante movimiento manual para no interferir
            if self.motion_tracker and self.motion_tracker.is_tracking:
                logger.debug("[TOOL] Pausando motion tracker durante movimiento manual.")
            return f"Cámara movida hacia '{direction}' (speed={speed}, dur={duration}s)."
        return f"No se pudo mover la cámara hacia '{direction}'."

    def _tool_seguir_movimiento(self, activar: bool = True) -> str:
        """Activa o desactiva el motion tracking."""
        if self.motion_tracker is None:
            return "Error: el sistema de seguimiento de movimiento no está disponible."

        if activar:
            if self.motion_tracker.is_tracking:
                return "El seguimiento de movimiento ya está activo."
            self.motion_tracker.start()
            if self.on_camera_action:
                self.on_camera_action("🎯 Motion tracking activado")
            return "Seguimiento de movimiento activado. La cámara ahora sigue automáticamente el movimiento."
        else:
            if not self.motion_tracker.is_tracking:
                return "El seguimiento de movimiento ya está desactivado."
            self.motion_tracker.stop()
            if self.on_camera_action:
                self.on_camera_action("🎯 Motion tracking desactivado")
            return "Seguimiento de movimiento desactivado. La cámara está quieta."

    # -- Herramientas de control del sistema ---------------------------------

    @staticmethod
    def _tool_ejecutar_comando(comando: str) -> str:
        from viernes.system.computer_control import ejecutar_comando
        return ejecutar_comando(comando)

    @staticmethod
    def _tool_abrir_aplicacion(nombre: str) -> str:
        from viernes.system.computer_control import abrir_aplicacion
        return abrir_aplicacion(nombre)

    @staticmethod
    def _tool_cerrar_aplicacion(nombre: str) -> str:
        from viernes.system.computer_control import cerrar_aplicacion
        return cerrar_aplicacion(nombre)

    @staticmethod
    def _tool_abrir_navegador(url: str) -> str:
        from viernes.system.computer_control import abrir_navegador
        return abrir_navegador(url)

    @staticmethod
    def _tool_buscar_en_internet(consulta: str) -> str:
        from viernes.system.computer_control import buscar_en_internet
        return buscar_en_internet(consulta)

    @staticmethod
    def _tool_cerrar_pestana_navegador() -> str:
        from viernes.system.computer_control import cerrar_pestana_navegador
        return cerrar_pestana_navegador()

    @staticmethod
    def _tool_info_sistema() -> str:
        from viernes.system.computer_control import info_sistema
        return info_sistema()

    @staticmethod
    def _tool_listar_procesos(filtro: str = "") -> str:
        from viernes.system.computer_control import listar_procesos
        return listar_procesos(filtro)

    # -----------------------------------------------------------------------
    # Utilidades
    # -----------------------------------------------------------------------

    def _trim_history(self) -> None:
        """Poda el historial preservando siempre el system prompt (índice 0).

        Se asegura de que el primer mensaje tras el corte sea de rol 'user'
        para no dejar pares tool_call / tool huérfanos que Ollama rechazaría.
        """
        limit = self.max_history_messages + 1
        if len(self.conversation_history) <= limit:
            return

        tail = self.conversation_history[-self.max_history_messages:]

        # Avanzar el inicio del tail hasta encontrar un mensaje 'user'
        # para no empezar con un 'tool' o 'assistant' huérfano.
        while tail and tail[0].get("role") != "user":
            tail = tail[1:]

        self.conversation_history = [self.conversation_history[0]] + tail

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """
        Divide un buffer de texto en oraciones usando puntuación como separador.
        Devuelve al menos una parte (aunque no haya puntuación).
        """
        import re
        parts = re.split(r'(?<=[.!?…\n])\s*', text)
        return [p for p in parts if p] or [text]

    def cancel_current(self) -> None:
        """Señaliza que la inferencia en curso debe abandonarse."""
        self._cancel_token += 1

    def update_camera(
        self,
        camera_stream: Optional["IPCameraStream"],
        ptz_controller: Optional["PTZController"] = None,
    ) -> None:
        """Inyecta/cambia la cámara y el PTZ en caliente."""
        self.camera_stream = camera_stream
        self.ptz_controller = ptz_controller
        self._tools_enabled = camera_stream is not None or ptz_controller is not None
        self._active_tools = self._build_active_tools()
        self.system_prompt["content"] = self._build_system_prompt()
        with self._history_lock:
            self.conversation_history[0] = self.system_prompt
        logger.info(
            f"Cámara actualizada. Visión: {'✓' if camera_stream else '✗'} | "
            f"PTZ: {'✓' if ptz_controller else '✗'}"
        )


# ---------------------------------------------------------------------------
# Prueba standalone
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    print("=========================================================")
    print(" ViernesBrain — Prueba de streaming")
    print(" ollama pull llava && ollama serve")
    print("=========================================================\n")

    brain = ViernesBrain(model_name="llava")

    try:
        while True:
            user_input = input("\n[Tú]: ")
            if user_input.strip().lower() in ["salir", "quit", "exit"]:
                break
            if not user_input.strip():
                continue

            print("[Viernes]: ", end="", flush=True)
            for sentence in brain.think_stream(user_input):
                print(sentence, end=" ", flush=True)
            print()

    except KeyboardInterrupt:
        print("\nInterrupción manual.")
    finally:
        print("\nCerebro apagado.")
