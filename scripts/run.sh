#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

if [ ! -x .venv/bin/python ]; then
    echo "No existe .venv. Ejecute primero: bash scripts/bootstrap_linux.sh" >&2
    exit 1
fi

if [ ! -f config/config.toml ]; then
    echo "Falta config/config.toml. Copie config/config.example.toml." >&2
    exit 1
fi

arguments="--config config/config.toml"
for option in "$@"; do
    case "$option" in
        --real-printer|--simulate|--headless|--diagnostic)
            arguments="$arguments $option"
            ;;
        *)
            echo "Opción no reconocida: $option" >&2
            echo "Uso: $0 [--real-printer] [--simulate] [--headless] [--diagnostic]" >&2
            exit 2
            ;;
    esac
done

# Los valores anteriores son opciones fijas, por lo que la expansión es segura.
# shellcheck disable=SC2086
exec .venv/bin/python -m kippu $arguments
