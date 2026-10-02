"""Consulta acotada del spooler; sus señales no sustituyen inspección física."""

from __future__ import annotations

from dataclasses import replace
import sys
import time
from typing import Any, Protocol

from el_bienvenidor.config import PrintSettings
from el_bienvenidor.domain.errors import PrinterUnavailableError
from el_bienvenidor.domain.models import JobStatus, PrinterDisposition, PrinterHealth, PrinterStatus, PrintReceipt


def _win32print() -> Any:
    if sys.platform != "win32":
        raise PrinterUnavailableError("El monitor de cola real sólo está disponible en Windows.")
    try:
        import win32print
    except ModuleNotFoundError as error:
        raise PrinterUnavailableError("pywin32 no está instalado.") from error
    return win32print


def _health(status: int, win32print: Any) -> PrinterHealth:
    for constant, value in (
        ("PRINTER_STATUS_PAPER_OUT", PrinterHealth.PAPER_OUT),
        ("PRINTER_STATUS_OFFLINE", PrinterHealth.OFFLINE),
        ("PRINTER_STATUS_PAUSED", PrinterHealth.PAUSED),
        ("PRINTER_STATUS_ERROR", PrinterHealth.ERROR),
    ):
        flag = getattr(win32print, constant, 0)
        if flag and status & flag:
            return value
    return PrinterHealth.READY


def inspect_printer(printer_name: str) -> PrinterStatus:
    win32print = _win32print()
    handle = None
    try:
        handle = win32print.OpenPrinter(printer_name)
        raw_status = int(win32print.GetPrinter(handle, 2).get("Status", 0))
        return PrinterStatus(_health(raw_status, win32print), raw_status, f"Estado Win32: {raw_status}")
    except Exception as error:
        raise PrinterUnavailableError(f"No se pudo consultar la impresora '{printer_name}': {error}") from error
    finally:
        if handle is not None:
            win32print.ClosePrinter(handle)


def inspect_job(printer_name: str, spooler_job_id: int) -> JobStatus:
    win32print = _win32print()
    handle = None
    try:
        handle = win32print.OpenPrinter(printer_name)
        for job in win32print.EnumJobs(handle, 0, 256, 1):
            if int(job.get("JobId", -1)) == spooler_job_id:
                raw_status = int(job.get("Status", 0))
                return JobStatus(True, raw_status, f"Estado de trabajo Win32: {raw_status}")
        return JobStatus(False, 0, "El trabajo ya no está en la cola.")
    except Exception as error:
        raise PrinterUnavailableError(f"No se pudo consultar el trabajo {spooler_job_id}: {error}") from error
    finally:
        if handle is not None:
            win32print.ClosePrinter(handle)


def _inspect_job_by_document_name(printer_name: str, document_name: str) -> JobStatus:
    win32print = _win32print()
    handle = None
    try:
        handle = win32print.OpenPrinter(printer_name)
        for job in win32print.EnumJobs(handle, 0, 256, 1):
            if str(job.get("pDocument", "")) == document_name:
                raw_status = int(job.get("Status", 0))
                return JobStatus(True, raw_status, f"Estado de trabajo Win32: {raw_status}")
        return JobStatus(False, 0, "El trabajo ya no está en la cola.")
    except Exception as error:
        raise PrinterUnavailableError(f"No se pudo correlacionar el documento '{document_name}': {error}") from error
    finally:
        if handle is not None:
            win32print.ClosePrinter(handle)


class PrintMonitor(Protocol):
    def monitor_submission(self, receipt: PrintReceipt) -> PrintReceipt: ...


class NoopQueueMonitor:
    def monitor_submission(self, receipt: PrintReceipt) -> PrintReceipt:
        return receipt


class WindowsQueueMonitor:
    def __init__(self, settings: PrintSettings) -> None:
        self._window_seconds = settings.monitor_window_seconds

    def monitor_submission(self, receipt: PrintReceipt) -> PrintReceipt:
        if receipt.disposition is not PrinterDisposition.ACCEPTED:
            return receipt
        deadline = time.monotonic() + self._window_seconds
        win32print = _win32print()
        job_error_flags = (
            getattr(win32print, "JOB_STATUS_ERROR", 0)
            | getattr(win32print, "JOB_STATUS_OFFLINE", 0)
            | getattr(win32print, "JOB_STATUS_PAPEROUT", 0)
            | getattr(win32print, "JOB_STATUS_PAUSED", 0)
            | getattr(win32print, "JOB_STATUS_BLOCKED_DEVQ", 0)
        )
        while time.monotonic() < deadline:
            printer = inspect_printer(receipt.printer_name)
            if printer.health is not PrinterHealth.READY:
                return replace(receipt, disposition=PrinterDisposition.QUEUE_ERROR, detail=f"Impresora: {printer.detail}")
            job = (
                inspect_job(receipt.printer_name, receipt.spooler_job_id)
                if receipt.spooler_job_id is not None
                else _inspect_job_by_document_name(receipt.printer_name, f"Kippu-{receipt.job_id}")
            )
            if not job.found:
                return replace(receipt, detail="El spooler finalizó el trabajo.")
            if job.raw_status & job_error_flags:
                return replace(receipt, disposition=PrinterDisposition.QUEUE_ERROR, detail=job.detail)
            time.sleep(1.0)
        return replace(receipt, detail="Ventana de supervisión agotada sin un error reportado por el driver.")
