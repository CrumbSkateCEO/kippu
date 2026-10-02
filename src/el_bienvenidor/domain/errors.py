"""Errores tipados que pueden mostrarse al operador sin exponer internals."""

from __future__ import annotations


class KippuError(Exception):
    """Error base con un mensaje apropiado para diagnóstico técnico."""


class ConfigurationError(KippuError):
    pass


class CameraError(KippuError):
    pass


class CameraUnavailableError(CameraError):
    pass


class VisionError(KippuError):
    pass


class FaceValidationError(VisionError):
    pass


class CompositionError(KippuError):
    pass


class PrinterError(KippuError):
    pass


class PrinterUnavailableError(PrinterError):
    pass


class QueueBlockedError(PrinterError):
    pass


class UnknownSubmissionError(PrinterError):
    """El spooler puede haber recibido el documento; no se debe reintentar solo."""

