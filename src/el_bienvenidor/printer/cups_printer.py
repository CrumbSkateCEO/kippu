"""Impresión silenciosa mediante CUPS, disponible en Debian y Linux en general."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import re
import shutil
import subprocess
from typing import Callable

from el_bienvenidor.config import PrintSettings
from el_bienvenidor.domain.errors import PrinterError, PrinterUnavailableError, UnknownSubmissionError
from el_bienvenidor.domain.models import CardArtifact, PrinterDisposition, PrinterHealth, PrinterProbe, PrintReceipt
from el_bienvenidor.printer.win_printer import PrintBackend

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _run_command(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "LC_ALL": "C"},
    )


def _cups_health(detail: str) -> PrinterHealth:
    value = detail.lower()
    if "offline" in value or "unreachable" in value:
        return PrinterHealth.OFFLINE
    if "paper out" in value or "out of paper" in value:
        return PrinterHealth.PAPER_OUT
    if "paused" in value or "not accepting" in value:
        return PrinterHealth.PAUSED
    if "disabled" in value or "error" in value or "stopped" in value:
        return PrinterHealth.ERROR
    return PrinterHealth.READY


def _job_id(output: str, printer_name: str) -> int | None:
    """Extrae el número de ``lp`` sin depender de cómo se llame la impresora."""
    match = re.search(r"request id is\s+" + re.escape(printer_name) + r"-(\d+)", output, re.IGNORECASE)
    if match is None:
        match = re.search(r"-(\d+)(?:\s|$)", output)
    return int(match.group(1)) if match else None


class CupsPrinter:
    """Backend CUPS sin diálogo gráfico; requiere los comandos ``lp`` y ``lpstat``."""

    def __init__(
        self,
        settings: PrintSettings,
        *,
        runner: CommandRunner = _run_command,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._settings = settings
        self._run = runner
        self._which = which

    def _commands(self) -> tuple[str, str]:
        lp = self._which("lp")
        lpstat = self._which("lpstat")
        if not lp or not lpstat:
            raise PrinterUnavailableError("No se encontró CUPS. Instale cups-client y configure una impresora.")
        return lp, lpstat

    def _name(self) -> str:
        if self._settings.printer_name:
            return self._settings.printer_name
        _, lpstat = self._commands()
        result = self._run([lpstat, "-d"])
        match = re.search(r"system default destination:\s*(\S+)", result.stdout, re.IGNORECASE)
        if result.returncode != 0 or match is None:
            detail = (result.stderr or result.stdout).strip()
            raise PrinterUnavailableError(f"CUPS no tiene una impresora predeterminada disponible. {detail}".strip())
        return match.group(1)

    def probe(self) -> PrinterProbe:
        _, lpstat = self._commands()
        name = self._name()
        result = self._run([lpstat, "-p", name])
        detail = (result.stdout or result.stderr).strip()
        if result.returncode != 0:
            raise PrinterUnavailableError(f"No se pudo sondear la impresora CUPS '{name}': {detail}")
        health = _cups_health(detail)
        return PrinterProbe(name, health, None, None, detail or "CUPS no informó detalles de estado.")

    def submit(self, artifact: CardArtifact) -> PrintReceipt:
        if artifact.pixel_size != (1181, 1772) or artifact.dpi != (300, 300):
            raise PrinterError("La impresora recibió un artefacto fuera del contrato 10x15.")
        lp, _ = self._commands()
        name = self._name()
        document_name = f"Kippu-{artifact.job_id}"
        try:
            result = self._run([lp, "-d", name, "-t", document_name, str(artifact.png_path)])
        except OSError as error:
            raise PrinterUnavailableError(f"No se pudo ejecutar CUPS: {error}") from error
        detail = (result.stdout or result.stderr).strip()
        if result.returncode != 0:
            raise PrinterError(f"CUPS no pudo iniciar el trabajo: {detail}")
        spooler_job_id = _job_id(result.stdout, name)
        if spooler_job_id is None:
            raise UnknownSubmissionError(
                f"CUPS aceptó una respuesta no correlacionable para {document_name}; no se reintentó: {detail}"
            )
        return PrintReceipt(
            job_id=artifact.job_id,
            printer_name=name,
            spooler_job_id=spooler_job_id,
            submitted_at=datetime.now(timezone.utc),
            disposition=PrinterDisposition.ACCEPTED,
            detail=f"Trabajo entregado al spooler CUPS: {detail}",
        )
