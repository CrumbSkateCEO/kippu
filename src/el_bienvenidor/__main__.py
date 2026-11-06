"""Entrada de consola de Kippu."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from el_bienvenidor.app import build_application, run_diagnostic
from el_bienvenidor.config import load_settings, validate_settings
from el_bienvenidor.domain.errors import KippuError
from el_bienvenidor.infra.logging import configure_logging
from el_bienvenidor.services.retention import purge_now


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kippu — recepcionista de bienvenida e impresión local")
    parser.add_argument("--config", type=Path, default=Path("config/config.toml"), help="Ruta al TOML local.")
    parser.add_argument("--real-printer", action="store_true", help="Habilita impresión real (Windows o CUPS en Linux); sin este flag siempre se usa dry_run.")
    parser.add_argument("--simulate", action="store_true", help="Simula cámara, saludo, rostro e impresión.")
    parser.add_argument("--headless", action="store_true", help="No abre ventana; útil para diagnósticos y automatización.")
    parser.add_argument("--diagnostic", action="store_true", help="Sondea cámara e impresora sin crear un trabajo.")
    parser.add_argument("--ip-camera", type=str, default=None, help="URL de cámara IP / RTSP (usa PyAV sin latencia). Anula camera.source_type a 'ip'.")
    parser.add_argument("--webcam", type=int, default=None, help="Índice de webcam local a utilizar. Anula camera.source_type a 'webcam'.")
    parser.add_argument("--ptz-track", action="store_true", help="Habilita seguimiento de rostro motorizado ONVIF PTZ.")
    parser.add_argument("--allow-inkless", action="store_true", help="Permite operar con impresora sin tinta o que reporta advertencias/pausa en CUPS.")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        settings = load_settings(arguments.config)
        if arguments.allow_inkless:
            settings = replace(
                settings,
                printing=replace(settings.printing, allow_inkless=True),
            )
        if arguments.ip_camera:
            settings = replace(
                settings,
                camera=replace(
                    settings.camera,
                    source_type="ip",
                    ip_url=arguments.ip_camera,
                ),
            )
            validate_settings(settings)
        elif arguments.webcam is not None:
            settings = replace(
                settings,
                camera=replace(
                    settings.camera,
                    source_type="webcam",
                    index=arguments.webcam,
                ),
            )
            validate_settings(settings)
        if arguments.ptz_track:
            settings = replace(
                settings,
                ptz=replace(
                    settings.ptz,
                    enabled=True,
                ),
            )
        configure_logging(settings.logging)
        purge_now(settings.storage)
        if arguments.diagnostic:
            return run_diagnostic(settings, real_printer=arguments.real_printer)
        application = build_application(
            settings,
            real_printer=arguments.real_printer and not arguments.simulate,
            simulate=arguments.simulate,
            headless=arguments.headless,
        )
        return application.run()
    except KippuError as error:
        print(f"Kippu no pudo iniciar: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
