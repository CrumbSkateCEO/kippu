#!/usr/bin/env sh
# Diagnóstico completo de Kippu (cámara, IA, carnet e impresora sin tinta).
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

exec .venv/bin/python scripts/debug_system.py "$@"
