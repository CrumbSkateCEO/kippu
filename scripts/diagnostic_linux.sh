#!/usr/bin/env sh
# Diagnóstico nativo para Debian/Ubuntu (cámara + impresora, sin captura).
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

arguments="--config config/config.toml --diagnostic"
for option in "$@"; do
    case "$option" in
        --real-printer)
            arguments="$arguments $option"
            ;;
        *)
            echo "Opción no reconocida: $option" >&2
            echo "Uso: $0 [--real-printer]" >&2
            exit 2
            ;;
    esac
done

# shellcheck disable=SC2086
exec .venv/bin/python -m kippu $arguments
