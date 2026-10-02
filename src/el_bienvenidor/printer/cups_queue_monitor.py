"""Supervisión acotada de la cola CUPS."""

from __future__ import annotations

from dataclasses import replace
import time
from typing import Callable

from el_bienvenidor.config import PrintSettings
from el_bienvenidor.domain.errors import PrinterUnavailableError
from el_bienvenidor.domain.models import PrinterDisposition, PrinterHealth, PrintReceipt
from el_bienvenidor.printer.cups_printer import CommandRunner, _cups_health, _run_command
from el_bienvenidor.printer.queue_monitor import PrintMonitor


class CupsQueueMonitor:
    def __init__(self, settings: PrintSettings, *, runner: CommandRunner = _run_command, which: Callable[[str], str | None] | None = None) -> None:
        self._window_seconds = settings.monitor_window_seconds
        self._run = runner
        self._which = which

    def _lpstat(self) -> str:
        import shutil

        lpstat = self._which("lpstat") if self._which is not None else shutil.which("lpstat")
        if not lpstat:
            raise PrinterUnavailableError("No se encontró el comando lpstat de CUPS.")
        return lpstat

    def monitor_submission(self, receipt: PrintReceipt) -> PrintReceipt:
        if receipt.disposition is not PrinterDisposition.ACCEPTED:
            return receipt
        lpstat = self._lpstat()
        job_token = f"{receipt.printer_name}-{receipt.spooler_job_id}"
        deadline = time.monotonic() + self._window_seconds
        while time.monotonic() < deadline:
            printer = self._run([lpstat, "-p", receipt.printer_name])
            detail = (printer.stdout or printer.stderr).strip()
            if printer.returncode != 0:
                return replace(receipt, disposition=PrinterDisposition.QUEUE_ERROR, detail=f"CUPS: {detail}")
            health = _cups_health(detail)
            if health is not PrinterHealth.READY:
                return replace(receipt, disposition=PrinterDisposition.QUEUE_ERROR, detail=f"Impresora CUPS: {detail}")
            queue = self._run([lpstat, "-W", "not-completed", "-o", receipt.printer_name])
            if queue.returncode != 0:
                return replace(receipt, disposition=PrinterDisposition.QUEUE_ERROR, detail=f"CUPS: {(queue.stderr or queue.stdout).strip()}")
            if job_token not in queue.stdout:
                return replace(receipt, detail="El spooler CUPS finalizó el trabajo.")
            time.sleep(1.0)
        return replace(receipt, detail="Ventana de supervisión CUPS agotada sin un error reportado por el driver.")
