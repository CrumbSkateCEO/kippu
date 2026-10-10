#!/usr/bin/env sh
# Orquesta El Bienvenidor y Viernes en secuencia.
# Cuando se cierra una ventana, arranca la siguiente.
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

loop=1
kippu_args="--config config/config.toml"

for option in "$@"; do
    case "$option" in
        --once)
            loop=0
            ;;
        --real-printer|--simulate|--headless|--diagnostic)
            kippu_args="$kippu_args $option"
            ;;
        -h|--help)
            cat <<'EOF'
Uso: bash scripts/show.sh [--once] [--real-printer] [--simulate] [--headless] [--diagnostic]

Abre cada app de a una. Al cerrar la ventana (o Ctrl+C en esa app),
arranca la siguiente:

  1. El Bienvenidor  (fotomatón)
  2. Viernes         (asistente HUD)

Por defecto el ciclo se repite. --once hace una sola pasada.
Ctrl+C en esta terminal detiene todo el show.
EOF
            exit 0
            ;;
        *)
            echo "Opción no reconocida: $option" >&2
            echo "Uso: $0 [--once] [--real-printer] [--simulate] [--headless] [--diagnostic]" >&2
            exit 2
            ;;
    esac
done

export PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}"

stop=0
on_stop() {
    stop=1
    echo
    echo "Show detenido."
    exit 0
}
trap 'on_stop' INT TERM

run_stage() {
    name=$1
    shift
    if [ "$stop" -ne 0 ]; then
        return 0
    fi
    echo
    echo "======== $name ========"
    echo "Cerrá la ventana para pasar a la siguiente etapa."
    echo
    # No usamos 'exec': hay que recuperar el control al cerrar la app.
    # Un fallo de la app no debe abortar el show.
    set +e
    .venv/bin/python "$@"
    status=$?
    set -e
    echo
    echo "← $name cerrado (código $status). Siguiente etapa en 1s…"
    sleep 1
}

while [ "$stop" -eq 0 ]; do
    # Los valores anteriores son opciones fijas, por lo que la expansión es segura.
    # shellcheck disable=SC2086
    run_stage "El Bienvenidor" -m kippu $kippu_args
    run_stage "Viernes" -m viernes.core.main
    if [ "$loop" -eq 0 ]; then
        echo "Pasada única terminada."
        break
    fi
    echo "Reiniciando ciclo…"
done
