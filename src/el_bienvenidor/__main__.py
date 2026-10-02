"""Entrada de consola de Kippu."""

from __future__ import annotations

import argparse
from pathlib import Path

from el_bienvenidor.app import build_application, run_diagnostic
from el_bienvenidor.config import load_settings
from el_bienvenidor.domain.errors import KippuError
from el_bienvenidor.infra.logging import configure_logging
from el_bienvenidor.services.retention import purge_now


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kippu — kiosco de bienvenida e impresión local")
    parser.add_argument("--config", type=Path, default=Path("config/config.toml"), help="Ruta al TOML local.")
    parser.add_argument("--real-printer", action="store_true", help="Habilita impresión real (Windows o CUPS en Linux); sin este flag siempre se usa dry_run.")
    parser.add_argument("--simulate", action="store_true", help="Simula cámara, saludo, rostro e impresión.")
    parser.add_argument("--headless", action="store_true", help="No abre ventana; útil para diagnósticos y automatización.")
    parser.add_argument("--diagnostic", action="store_true", help="Sondea cámara e impresora sin crear un trabajo.")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        settings = load_settings(arguments.config)
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
