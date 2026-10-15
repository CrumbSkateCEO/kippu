#!/usr/bin/env bash
# =============================================================================
# setup_linux.sh — Instalación de Kippu en Debian/Ubuntu y Arch/CachyOS
# =============================================================================
# Uso:
#   chmod +x setup_linux.sh
#   ./setup_linux.sh
#
# El script detecta el gestor de paquetes del sistema (apt / pacman),
# instala las dependencias de sistema necesarias, crea el entorno virtual
# con uv y luego instala todos los paquetes Python.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Colores para la salida
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # Sin color

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# -----------------------------------------------------------------------------
# 1. Detectar distribución e instalar dependencias de sistema
# -----------------------------------------------------------------------------

install_system_deps() {
    if command -v apt-get &>/dev/null; then
        info "Detectado: Debian / Ubuntu"
        sudo apt-get update -qq
        sudo apt-get install -y \
            portaudio19-dev \
            python3-dev \
            python3-pip \
            ffmpeg \
            libopencv-dev \
            git \
            build-essential \
            curl
    elif command -v pacman &>/dev/null; then
        info "Detectado: Arch / CachyOS"
        sudo pacman -Sy --noconfirm \
            portaudio \
            python \
            ffmpeg \
            opencv \
            git \
            base-devel \
            curl
    else
        warn "Gestor de paquetes no reconocido. Asegurate de tener instalado:"
        warn "  - portaudio (dev headers)"
        warn "  - ffmpeg"
        warn "  - python3-dev / python headers"
    fi
}

# -----------------------------------------------------------------------------
# 2. Instalar uv (gestor de entornos Python ultrarrápido)
# -----------------------------------------------------------------------------

install_uv() {
    if command -v uv &>/dev/null; then
        info "uv ya está instalado: $(uv --version)"
    else
        info "Instalando uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # Agregar al PATH de la sesión actual
        export PATH="$HOME/.local/bin:$PATH"
    fi
}

# -----------------------------------------------------------------------------
# 3. Crear entorno virtual e instalar dependencias Python
# -----------------------------------------------------------------------------

install_python_deps() {
    info "Creando entorno virtual en: $VENV_DIR"
    uv venv "$VENV_DIR"

    info "Instalando dependencias Python..."
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    uv pip install -r "$SCRIPT_DIR/requirements.txt"

    info "Dependencias Python instaladas correctamente."
}

# -----------------------------------------------------------------------------
# 4. Crear script de lanzamiento rápido
# -----------------------------------------------------------------------------

create_launchers() {
    # Lanzador para el_bienvenidor (fotomatón)
    cat > "$SCRIPT_DIR/run_kippu.sh" << 'EOF'
#!/usr/bin/env bash
cd "$(dirname "${BASH_SOURCE[0]}")"
source .venv/bin/activate
python -m el_bienvenidor "$@"
EOF
    chmod +x "$SCRIPT_DIR/run_kippu.sh"

    # Lanzador para viernes (asistente de voz)
    cat > "$SCRIPT_DIR/run_viernes.sh" << 'EOF'
#!/usr/bin/env bash
cd "$(dirname "${BASH_SOURCE[0]}")"
source .venv/bin/activate
python -m viernes.core.main "$@"
EOF
    chmod +x "$SCRIPT_DIR/run_viernes.sh"

    info "Scripts de lanzamiento creados: run_kippu.sh / run_viernes.sh"
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main() {
    echo ""
    echo "=============================================="
    echo "  Kippu — Setup Linux (Debian / Arch / CachyOS)"
    echo "=============================================="
    echo ""

    install_system_deps
    install_uv
    install_python_deps
    create_launchers

    echo ""
    info "=== Instalación completa ==="
    echo ""
    echo "Para ejecutar el fotomatón:"
    echo "  ./run_kippu.sh --simulate          # modo de prueba sin cámara"
    echo "  ./run_kippu.sh                     # modo normal"
    echo ""
    echo "Para ejecutar Viernes (asistente de voz):"
    echo "  ./run_viernes.sh"
    echo ""
    echo "NOTA: Para que Viernes use el TTS de voz, descargá el modelo Ollama:"
    echo "  ollama pull llava"
    echo ""
}

main "$@"
