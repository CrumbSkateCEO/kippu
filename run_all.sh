#!/usr/bin/env bash
# =============================================================================
# run_all.sh — Lanza Kippu (fotomatón) y Viernes (asistente de voz) juntos
# =============================================================================
# Uso:
#   ./run_all.sh                     → modo normal
#   ./run_all.sh --simulate          → kippu en modo simulado (sin cámara web)
#   ./run_all.sh --no-viernes        → solo kippu
#   ./run_all.sh --no-kippu          → solo viernes
#   ./run_all.sh --real-printer      → kippu con impresora real (CUPS)
#
# Ctrl+C detiene ambos procesos limpiamente.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PYTHON="$VENV/bin/python"

# --- Colores ---------------------------------------------------------------
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[run_all]${NC} $*"; }
warn()  { echo -e "${YELLOW}[run_all]${NC} $*"; }
error() { echo -e "${RED}[run_all]${NC} $*" >&2; }
header() {
    echo ""
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${CYAN}  KIPPU + VIERNES — Lanzador unificado${NC}"
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════${NC}"
    echo ""
}

# --- Argumentos ------------------------------------------------------------
RUN_KIPPU=true
RUN_VIERNES=true
KIPPU_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --no-viernes)  RUN_VIERNES=false ;;
        --no-kippu)    RUN_KIPPU=false ;;
        *)             KIPPU_ARGS+=("$arg") ;;
    esac
done

# --- Validaciones ----------------------------------------------------------

header

if [[ ! -f "$PYTHON" ]]; then
    error "Entorno virtual no encontrado en $VENV"
    error "Ejecuta primero: ./setup_linux.sh"
    exit 1
fi

cd "$SCRIPT_DIR"

# Verificar que el módulo src esté en el path
PYTHONPATH="$SCRIPT_DIR/src"
export PYTHONPATH

# --- PIDs de los subprocesos -----------------------------------------------
KIPPU_PID=""
VIERNES_PID=""

# --- Función de limpieza (Ctrl+C o fin de cualquier proceso) ---------------
cleanup() {
    echo ""
    warn "Cerrando todos los procesos..."

    if [[ -n "$KIPPU_PID" ]] && kill -0 "$KIPPU_PID" 2>/dev/null; then
        info "Deteniendo Kippu (PID $KIPPU_PID)..."
        kill -SIGTERM "$KIPPU_PID" 2>/dev/null || true
    fi

    if [[ -n "$VIERNES_PID" ]] && kill -0 "$VIERNES_PID" 2>/dev/null; then
        info "Deteniendo Viernes (PID $VIERNES_PID)..."
        kill -SIGTERM "$VIERNES_PID" 2>/dev/null || true
    fi

    # Esperar hasta 4 segundos a que terminen limpiamente
    local timeout=40
    while ((timeout-- > 0)); do
        local alive=false
        [[ -n "$KIPPU_PID" ]]   && kill -0 "$KIPPU_PID"   2>/dev/null && alive=true
        [[ -n "$VIERNES_PID" ]] && kill -0 "$VIERNES_PID" 2>/dev/null && alive=true
        $alive || break
        sleep 0.1
    done

    # Forzar si no terminaron
    [[ -n "$KIPPU_PID" ]]   && kill -0 "$KIPPU_PID"   2>/dev/null && kill -SIGKILL "$KIPPU_PID"   2>/dev/null || true
    [[ -n "$VIERNES_PID" ]] && kill -0 "$VIERNES_PID" 2>/dev/null && kill -SIGKILL "$VIERNES_PID" 2>/dev/null || true

    info "Apagado completo."
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# --- Monitor: si algún proceso muere, mata al otro y sale ------------------
monitor() {
    local name="$1"
    local pid="$2"

    wait "$pid" 2>/dev/null
    local exit_code=$?

    # Solo actuar si seguimos corriendo (no fue un shutdown manual)
    if [[ -n "$KIPPU_PID" || -n "$VIERNES_PID" ]]; then
        warn "$name terminó (exit $exit_code). Cerrando el sistema..."
        cleanup
    fi
}

# --- Lanzar Kippu ----------------------------------------------------------
if $RUN_KIPPU; then
    info "Iniciando ${BOLD}Kippu${NC} (fotomatón)..."
    if [[ ${#KIPPU_ARGS[@]} -gt 0 ]]; then
        info "  Argumentos: ${KIPPU_ARGS[*]}"
    fi

    "$PYTHON" -m el_bienvenidor "${KIPPU_ARGS[@]}" \
        2>&1 | sed "s/^/${CYAN}[KIPPU]${NC} /" &
    KIPPU_PID=$!
    info "Kippu PID: $KIPPU_PID"

    # Monitor en background
    monitor "Kippu" "$KIPPU_PID" &
fi

# --- Pausa breve para no solapar inicialización ----------------------------
if $RUN_KIPPU && $RUN_VIERNES; then
    sleep 0.8
fi

# --- Lanzar Viernes --------------------------------------------------------
if $RUN_VIERNES; then
    info "Iniciando ${BOLD}Viernes${NC} (asistente de voz)..."

    "$PYTHON" -m viernes.core.main \
        2>&1 | sed "s/^/${GREEN}[VIERNES]${NC} /" &
    VIERNES_PID=$!
    info "Viernes PID: $VIERNES_PID"

    monitor "Viernes" "$VIERNES_PID" &
fi

# --- Resumen ---------------------------------------------------------------
echo ""
echo -e "${BOLD}  Procesos activos:${NC}"
$RUN_KIPPU   && echo -e "  ${CYAN}▶ Kippu${NC}   (PID $KIPPU_PID)   — fotomatón"
$RUN_VIERNES && echo -e "  ${GREEN}▶ Viernes${NC} (PID $VIERNES_PID)  — asistente de voz"
echo ""
echo -e "  Presioná ${BOLD}Ctrl+C${NC} para detener ambos."
echo ""

# --- Esperar a que alguno termine ------------------------------------------
wait
