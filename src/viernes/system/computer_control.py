"""Control del sistema operativo para Viernes.

Proporciona funciones que el LLM invoca mediante tool-calling para
interactuar con la computadora: comandos, apps, pestañas y búsqueda web.

Detecta el SO al importar (Windows, macOS o Linux) y adapta ejecutables,
cierre de procesos y listados. La API pública se mantiene igual en todos
los sistemas.

Cada función devuelve un string que se inyecta como ``role: "tool"``.

Seguridad:
- Timeout global para que ningún proceso quede colgado.
- Se bloquean comandos destructivos obvios.
- ``shell=True`` solo donde el SO lo requiere (p. ej. builtins de cmd).
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import urllib.parse
import webbrowser
from typing import Optional

logger = logging.getLogger(__name__)

_CMD_TIMEOUT = 15

_BLOCKED_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    ":(){",
    "fork bomb",
    "chmod -r 777 /",
    "shutdown",
    "reboot",
    "poweroff",
    "halt",
    "init 0",
    "init 6",
    "format c:",
    "del /s /q c:",
    "rd /s /q c:",
    "remove-item -recurse",
]


# ---------------------------------------------------------------------------
# Detección de sistema operativo
# ---------------------------------------------------------------------------

def detectar_os() -> dict:
    """Describe el sistema anfitrión para que Viernes sepa cómo moverse."""
    family_raw = platform.system().lower()
    if family_raw.startswith("win"):
        family = "windows"
        pretty = "Windows"
    elif family_raw == "darwin":
        family = "macos"
        pretty = "macOS"
    else:
        family = "linux"
        pretty = "Linux"

    distro = ""
    if family == "linux":
        distro = _linux_pretty_name()

    return {
        "family": family,
        "pretty": pretty,
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "distro": distro,
        "resumen": _resumen_os(pretty, distro),
    }


def _linux_pretty_name() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def _resumen_os(pretty: str, distro: str) -> str:
    extra = f" ({distro})" if distro else ""
    return (
        f"{pretty}{extra} {platform.release()} "
        f"{platform.machine()}".strip()
    )


_OS = detectar_os()
OS_FAMILY: str = _OS["family"]
OS_RESUMEN: str = _OS["resumen"]


def info_sistema() -> str:
    """Texto listo para el LLM / system prompt."""
    return (
        f"Sistema: {OS_RESUMEN}. "
        f"Familia de comandos: {OS_FAMILY}."
    )


# ---------------------------------------------------------------------------
# Aliases de aplicaciones por familia
# ---------------------------------------------------------------------------

_ALIASES_LINUX = {
    "firefox": ["firefox", "firefox-esr"],
    "chrome": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    "navegador": ["xdg-open"],
    "terminal": ["gnome-terminal", "konsole", "xfce4-terminal", "xterm", "kitty", "alacritty"],
    "archivos": ["nautilus", "dolphin", "thunar", "nemo", "pcmanfm"],
    "explorador": ["nautilus", "dolphin", "thunar", "nemo", "pcmanfm"],
    "editor": ["gedit", "kate", "mousepad", "xed", "nano"],
    "calculadora": ["gnome-calculator", "kcalc", "galculator"],
    "musica": ["rhythmbox", "audacious", "clementine", "spotify"],
    "video": ["vlc", "mpv", "totem", "celluloid"],
    "vlc": ["vlc"],
    "code": ["code", "codium"],
    "vscode": ["code", "codium"],
    "cursor": ["cursor"],
    "gimp": ["gimp"],
    "blender": ["blender"],
    "steam": ["steam"],
    "discord": ["discord"],
    "telegram": ["telegram-desktop"],
    "obs": ["obs", "obs-studio"],
    "libreoffice": ["libreoffice"],
}

_ALIASES_WINDOWS = {
    "firefox": ["firefox.exe", "firefox"],
    "chrome": ["chrome.exe", "chrome"],
    "edge": ["msedge.exe", "msedge"],
    "navegador": ["msedge.exe", "chrome.exe", "firefox.exe"],
    "terminal": ["wt.exe", "cmd.exe", "powershell.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe", "pwsh.exe"],
    "archivos": ["explorer.exe"],
    "explorador": ["explorer.exe"],
    "bloc de notas": ["notepad.exe"],
    "notepad": ["notepad.exe"],
    "calculadora": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "code": ["code.exe", "code"],
    "vscode": ["code.exe", "code"],
    "cursor": ["cursor.exe", "cursor"],
    "vlc": ["vlc.exe", "vlc"],
    "spotify": ["spotify.exe"],
    "discord": ["discord.exe"],
    "steam": ["steam.exe"],
    "telegram": ["telegram.exe"],
}

_ALIASES_MACOS = {
    "firefox": ["Firefox"],
    "chrome": ["Google Chrome"],
    "safari": ["Safari"],
    "navegador": ["Safari"],
    "terminal": ["Terminal"],
    "archivos": ["Finder"],
    "explorador": ["Finder"],
    "editor": ["TextEdit"],
    "calculadora": ["Calculator"],
    "code": ["Visual Studio Code"],
    "vscode": ["Visual Studio Code"],
    "cursor": ["Cursor"],
    "vlc": ["VLC"],
    "spotify": ["Spotify"],
    "discord": ["Discord"],
    "steam": ["Steam"],
    "telegram": ["Telegram"],
    "obs": ["OBS"],
}

_PROCESS_WINDOWS = {
    "firefox": "firefox.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "code": "code.exe",
    "vscode": "code.exe",
    "cursor": "cursor.exe",
    "vlc": "vlc.exe",
    "notepad": "notepad.exe",
    "spotify": "spotify.exe",
    "discord": "discord.exe",
    "steam": "steam.exe",
    "telegram": "telegram.exe",
    "explorer": "explorer.exe",
}


def _aliases() -> dict:
    if OS_FAMILY == "windows":
        return _ALIASES_WINDOWS
    if OS_FAMILY == "macos":
        return _ALIASES_MACOS
    return _ALIASES_LINUX


def _is_command_safe(command: str) -> bool:
    cmd_lower = command.lower().strip()
    return not any(pattern in cmd_lower for pattern in _BLOCKED_PATTERNS)


def _find_executable(app_name: str) -> Optional[str]:
    name_lower = app_name.lower().strip()
    candidates = _aliases().get(name_lower, [app_name])
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return shutil.which(app_name)


def _popen_detached(args: list[str], *, shell: bool = False) -> None:
    kwargs: dict = dict(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=shell,
    )
    if OS_FAMILY == "windows":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def ejecutar_comando(comando: str) -> str:
    """Ejecuta un comando en la terminal nativa y devuelve la salida."""
    if not _is_command_safe(comando):
        logger.warning("[SYSTEM] Comando bloqueado por seguridad: %s", comando)
        return (
            "Error: ese comando está bloqueado por seguridad. "
            "No puedo ejecutar comandos destructivos."
        )

    logger.info("[SYSTEM] Ejecutando (%s): %s", OS_FAMILY, comando)
    try:
        result = subprocess.run(
            comando,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_CMD_TIMEOUT,
            cwd=None,
        )
        output = ""
        if result.stdout and result.stdout.strip():
            output += result.stdout.strip()
        if result.stderr and result.stderr.strip():
            if output:
                output += "\n"
            output += f"[stderr] {result.stderr.strip()}"

        if not output:
            if result.returncode == 0:
                output = "Comando ejecutado correctamente (sin salida)."
            else:
                output = f"El comando terminó con código de error {result.returncode}."

        if len(output) > 2000:
            output = output[:2000] + "\n... (salida truncada)"

        logger.info("[SYSTEM] Resultado (código %s): %s", result.returncode, output[:200])
        return output
    except subprocess.TimeoutExpired:
        logger.warning("[SYSTEM] Timeout (%ss) al ejecutar: %s", _CMD_TIMEOUT, comando)
        return f"El comando tardó más de {_CMD_TIMEOUT} segundos y fue cancelado."
    except Exception as exc:
        logger.error("[SYSTEM] Error al ejecutar comando: %s", exc)
        return f"Error al ejecutar el comando: {exc}"


def abrir_aplicacion(nombre: str) -> str:
    """Abre una aplicación del sistema por nombre amigable o ejecutable."""
    nombre = nombre.strip()
    logger.info("[SYSTEM] Abriendo aplicación '%s' en %s", nombre, OS_FAMILY)

    try:
        if OS_FAMILY == "macos":
            alias = _aliases().get(nombre.lower(), [nombre])[0]
            _popen_detached(["open", "-a", alias])
            return f"Aplicación '{nombre}' abierta correctamente."

        if OS_FAMILY == "windows":
            exe = _find_executable(nombre)
            if exe:
                _popen_detached([exe])
                return f"Aplicación '{nombre}' abierta correctamente."
            _popen_detached(["cmd", "/c", "start", "", nombre])
            return f"Intenté abrir '{nombre}' con el lanzador de Windows."

        exe = _find_executable(nombre)
        if not exe:
            logger.warning("[SYSTEM] Aplicación no encontrada: %s", nombre)
            return f"No encontré la aplicación '{nombre}' instalada en el sistema."
        _popen_detached([exe])
        return f"Aplicación '{nombre}' abierta correctamente."
    except Exception as exc:
        logger.error("[SYSTEM] Error al abrir %s: %s", nombre, exc)
        return f"Error al abrir '{nombre}': {exc}"


def cerrar_aplicacion(nombre: str) -> str:
    """Cierra instancias de una aplicación por nombre."""
    nombre_limpio = nombre.strip()
    logger.info("[SYSTEM] Cerrando aplicación: %s", nombre_limpio)

    try:
        if OS_FAMILY == "windows":
            imagen = _PROCESS_WINDOWS.get(nombre_limpio.lower(), nombre_limpio)
            if not imagen.lower().endswith(".exe"):
                imagen = imagen + ".exe"
            result = subprocess.run(
                ["taskkill", "/IM", imagen, "/T"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            combined = (result.stdout or "") + (result.stderr or "")
            if result.returncode == 0:
                return f"Se enviaron señales de cierre a '{nombre_limpio}'."
            if "not found" in combined.lower() or result.returncode == 128:
                return f"No se encontró ningún proceso ejecutando '{nombre_limpio}'."
            return combined.strip() or f"No se pudo cerrar '{nombre_limpio}'."

        if OS_FAMILY == "macos":
            alias = _aliases().get(nombre_limpio.lower(), [nombre_limpio])[0]
            result = subprocess.run(
                ["osascript", "-e", f'quit app "{alias}"'],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if result.returncode == 0:
                return f"Se envió cierre a '{nombre_limpio}'."
            result = subprocess.run(
                ["pkill", "-f", nombre_limpio],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return f"Se enviaron señales de cierre a '{nombre_limpio}'."
            return f"No se encontró ningún proceso ejecutando '{nombre_limpio}'."

        result = subprocess.run(
            ["pkill", "-f", nombre_limpio],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return f"Se enviaron señales de cierre a '{nombre_limpio}'."
        if result.returncode == 1:
            return f"No se encontró ningún proceso ejecutando '{nombre_limpio}'."
        return f"Error al intentar cerrar '{nombre_limpio}': {(result.stderr or '').strip()}"
    except Exception as exc:
        logger.error("[SYSTEM] Error al cerrar %s: %s", nombre_limpio, exc)
        return f"Error al cerrar '{nombre_limpio}': {exc}"


def _normalizar_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def abrir_navegador(url: str) -> str:
    """Abre una URL en una pestaña del navegador predeterminado."""
    url = _normalizar_url(url)
    logger.info("[SYSTEM] Abriendo pestaña: %s", url)
    try:
        webbrowser.open_new_tab(url)
        return f"Pestaña abierta en el navegador: {url}"
    except Exception as exc:
        logger.error("[SYSTEM] Error al abrir URL: %s", exc)
        return f"Error al abrir la URL: {exc}"


def buscar_en_internet(consulta: str) -> str:
    """Abre una búsqueda web (Google) en una pestaña nueva."""
    query_encoded = urllib.parse.quote_plus(consulta.strip())
    search_url = f"https://www.google.com/search?q={query_encoded}"
    logger.info("[SYSTEM] Búsqueda web: '%s'", consulta)
    try:
        webbrowser.open_new_tab(search_url)
        return f"Búsqueda abierta en el navegador: '{consulta}'"
    except Exception as exc:
        logger.error("[SYSTEM] Error al buscar: %s", exc)
        return f"Error al realizar la búsqueda: {exc}"


def cerrar_pestana_navegador() -> str:
    """Cierra la pestaña activa enviando Ctrl+W (Cmd+W en macOS) al escritorio."""
    logger.info("[SYSTEM] Cerrando pestaña activa del navegador")
    try:
        if OS_FAMILY == "macos":
            script = 'tell application "System Events" to keystroke "w" using command down'
            subprocess.run(["osascript", "-e", script], check=False, timeout=5)
            return "Envié el atajo para cerrar la pestaña activa."
        if OS_FAMILY == "windows":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.SendKeys]::SendWait('^w')"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                check=False,
                timeout=8,
            )
            return "Envié el atajo para cerrar la pestaña activa."
        if shutil.which("xdotool"):
            subprocess.run(["xdotool", "key", "ctrl+w"], check=False, timeout=5)
            return "Envié Ctrl+W para cerrar la pestaña activa."
        return (
            "No pude cerrar solo la pestaña: en este Linux no está xdotool. "
            "Puedo cerrar el navegador entero con cerrar_aplicacion."
        )
    except Exception as exc:
        logger.error("[SYSTEM] Error al cerrar pestaña: %s", exc)
        return f"Error al cerrar la pestaña: {exc}"


def listar_procesos(filtro: str = "") -> str:
    """Lista procesos en ejecución, opcionalmente filtrados por nombre."""
    logger.info("[SYSTEM] Listando procesos (filtro=%r, os=%s)", filtro, OS_FAMILY)
    try:
        if OS_FAMILY == "windows":
            args = ["tasklist"]
            if filtro.strip():
                imagen = filtro.strip()
                if not imagen.lower().endswith(".exe"):
                    imagen += ".exe"
                args = ["tasklist", "/FI", f"IMAGENAME eq {imagen}"]
            result = subprocess.run(args, capture_output=True, text=True, timeout=8)
            text = (result.stdout or "").strip()
            if not text or "No tasks" in text:
                return f"No se encontraron procesos que coincidan con '{filtro}'." if filtro else "No se pudo listar procesos."
            lines = text.splitlines()[:22]
            return "Procesos:\n" + "\n".join(lines)

        if filtro.strip():
            result = subprocess.run(
                ["pgrep", "-a", "-i", filtro.strip()],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                if len(lines) > 30:
                    lines = lines[:30] + ["... (más resultados omitidos)"]
                return f"Procesos con '{filtro}':\n" + "\n".join(lines)
            return f"No se encontraron procesos que coincidan con '{filtro}'."

        ps_cmd = ["ps", "aux", "-r"] if OS_FAMILY == "macos" else ["ps", "aux", "--sort=-pcpu"]
        result = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=5)
        if result.stdout and result.stdout.strip():
            lines = result.stdout.strip().split("\n")[:21]
            return "Procesos (top 20 por CPU):\n" + "\n".join(lines)
        return "No se pudo obtener la lista de procesos."
    except Exception as exc:
        logger.error("[SYSTEM] Error al listar procesos: %s", exc)
        return f"Error al listar procesos: {exc}"


__all__ = [
    "OS_FAMILY",
    "OS_RESUMEN",
    "detectar_os",
    "info_sistema",
    "ejecutar_comando",
    "abrir_aplicacion",
    "cerrar_aplicacion",
    "abrir_navegador",
    "buscar_en_internet",
    "cerrar_pestana_navegador",
    "listar_procesos",
]
