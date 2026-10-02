"""Backend de impresión silencioso basado en GDI/pywin32."""

from __future__ import annotations

from datetime import datetime, timezone
import sys
from typing import Any, Protocol

from el_bienvenidor.config import PrintSettings
from el_bienvenidor.domain.errors import PrinterError, PrinterUnavailableError, UnknownSubmissionError
from el_bienvenidor.domain.models import CardArtifact, PrinterDisposition, PrinterHealth, PrinterProbe, PrintReceipt


class PrintBackend(Protocol):
    def probe(self) -> PrinterProbe: ...
    def submit(self, artifact: CardArtifact) -> PrintReceipt: ...


def _win32() -> tuple[Any, Any, Any]:
    if sys.platform != "win32":
        raise PrinterUnavailableError("La impresión real de Kippu sólo está disponible en Windows.")
    try:
        import win32con
        import win32print
        import win32ui
    except ModuleNotFoundError as error:
        raise PrinterUnavailableError("pywin32 no está instalado en este entorno Windows.") from error
    return win32con, win32print, win32ui


def _map_printer_health(status: int, win32print: Any) -> PrinterHealth:
    checks = (
        ("PRINTER_STATUS_PAPER_OUT", PrinterHealth.PAPER_OUT),
        ("PRINTER_STATUS_OFFLINE", PrinterHealth.OFFLINE),
        ("PRINTER_STATUS_PAUSED", PrinterHealth.PAUSED),
        ("PRINTER_STATUS_ERROR", PrinterHealth.ERROR),
    )
    for constant, health in checks:
        flag = getattr(win32print, constant, 0)
        if flag and status & flag:
            return health
    return PrinterHealth.READY


class DryRunPrintBackend:
    """Recibo simulado seguro para desarrollo y pruebas."""

    def __init__(self, printer_name: str = "Kippu Dry Run") -> None:
        self._printer_name = printer_name

    def probe(self) -> PrinterProbe:
        return PrinterProbe(self._printer_name, PrinterHealth.READY, (1181, 1772), (300, 300), "Modo dry_run: no se enviará papel.")

    def submit(self, artifact: CardArtifact) -> PrintReceipt:
        return PrintReceipt(
            job_id=artifact.job_id,
            printer_name=self._printer_name,
            spooler_job_id=None,
            submitted_at=datetime.now(timezone.utc),
            disposition=PrinterDisposition.ACCEPTED,
            detail="Trabajo simulado aceptado.",
        )


class WindowsPrinter:
    def __init__(self, settings: PrintSettings) -> None:
        self._settings = settings

    def _name(self) -> str:
        _, win32print, _ = _win32()
        if self._settings.printer_name:
            return self._settings.printer_name
        try:
            return str(win32print.GetDefaultPrinter())
        except Exception as error:
            raise PrinterUnavailableError("Windows no tiene una impresora predeterminada disponible.") from error

    def probe(self) -> PrinterProbe:
        win32con, win32print, win32ui = _win32()
        name = self._name()
        handle = None
        dc = None
        try:
            handle = win32print.OpenPrinter(name)
            info = win32print.GetPrinter(handle, 2)
            status = int(info.get("Status", 0))
            health = _map_printer_health(status, win32print)
            dc = win32ui.CreateDC()
            dc.CreatePrinterDC(name)
            printable = (int(dc.GetDeviceCaps(win32con.HORZRES)), int(dc.GetDeviceCaps(win32con.VERTRES)))
            dpi = (int(dc.GetDeviceCaps(win32con.LOGPIXELSX)), int(dc.GetDeviceCaps(win32con.LOGPIXELSY)))
            return PrinterProbe(name, health, printable, dpi, f"Estado Win32: {status}")
        except Exception as error:
            raise PrinterUnavailableError(f"No se pudo sondear la impresora '{name}': {error}") from error
        finally:
            if dc is not None:
                dc.DeleteDC()
            if handle is not None:
                win32print.ClosePrinter(handle)

    def submit(self, artifact: CardArtifact) -> PrintReceipt:
        """No reintenta tras StartDoc: un fallo posterior puede haber impreso."""
        if artifact.pixel_size != (1181, 1772) or artifact.dpi != (300, 300):
            raise PrinterError("La impresora recibió un artefacto fuera del contrato 10x15.")
        win32con, _, win32ui = _win32()
        name = self._name()
        dc = None
        start_doc_succeeded = False
        try:
            from PIL import Image, ImageWin
            dc = win32ui.CreateDC()
            dc.CreatePrinterDC(name)
            document_name = f"Kippu-{artifact.job_id}"
            raw_spooler_job_id = dc.StartDoc(document_name)
            start_doc_succeeded = True
            spooler_job_id = int(raw_spooler_job_id) if raw_spooler_job_id is not None else None
            dc.StartPage()
            with Image.open(artifact.png_path) as card:
                bitmap = ImageWin.Dib(card.convert("RGB"))
                target = (0, 0, int(dc.GetDeviceCaps(win32con.HORZRES)), int(dc.GetDeviceCaps(win32con.VERTRES)))
                bitmap.draw(dc.GetHandleOutput(), target)
            dc.EndPage()
            dc.EndDoc()
            return PrintReceipt(
                job_id=artifact.job_id,
                printer_name=name,
                spooler_job_id=spooler_job_id if spooler_job_id is not None and spooler_job_id > 0 else None,
                submitted_at=datetime.now(timezone.utc),
                disposition=PrinterDisposition.ACCEPTED,
                detail="Trabajo entregado al spooler de Windows.",
            )
        except Exception as error:
            if start_doc_succeeded:
                try:
                    dc.AbortDoc()
                except Exception:
                    pass
                raise UnknownSubmissionError(
                    f"El spooler pudo haber recibido Kippu-{artifact.job_id}; no se reintentó: {error}"
                ) from error
            raise PrinterError(f"No se pudo iniciar el trabajo de impresión: {error}") from error
        finally:
            if dc is not None:
                dc.DeleteDC()
