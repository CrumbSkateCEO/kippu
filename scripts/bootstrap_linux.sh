#!/usr/bin/env sh
# Prepara un entorno nativo para Debian y distribuciones Linux compatibles.
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

if ! command -v python3 >/dev/null 2>&1; then
    echo "No se encontró python3. Instale Python 3.10 o superior y python3-venv." >&2
    exit 1
fi

if ! python3 -m venv .venv; then
    echo "No se pudo crear .venv. En Debian/Ubuntu instale: sudo apt install python3-venv" >&2
    exit 1
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .

cat <<'EOF'
Entorno listo (Debian/Linux nativo).

Dependencias del sistema recomendadas:
  sudo apt install python3 python3-venv libgl1 libglib2.0-0 v4l-utils
  # Sólo impresión física:
  sudo apt install cups cups-client

Pasos siguientes:
  1) cp config/config.example.toml config/config.toml
  2) bash scripts/diagnostic_linux.sh
  3) bash scripts/run.sh
  4) bash scripts/run.sh --simulate
  5) bash scripts/run.sh --real-printer
EOF
