# Kippu — Recepcionista Digital

Recepcionista digital interactivo para la presentación de **CrumbSkate**.
Detecta la presencia y saludo de los visitantes, solicita sus datos (o los acredita), captura su fotografía, compone su credencial oficial 10×15 cm y la imprime en tiempo real.

---

## Estructura del Proyecto

```
kippu/
├── src/
│   ├── el_bienvenidor/       # Núcleo del recepcionista
│   │   ├── app.py            # Orquestador del recepcionista y ciclo de estados
│   │   ├── config.py         # Carga y validación de configuración TOML
│   │   ├── camera/           # Captura de video con OpenCV / V4L2
│   │   ├── vision/           # Detección de rostros y pose/saludo (MediaPipe / OpenCV)
│   │   ├── composition/      # Diseño y renderizado del carnet 10x15 @ 300 DPI
│   │   ├── printer/          # Impresión silenciosa (CUPS en Linux, Win32 en Windows)
│   │   ├── ui/               # Interfaz fullscreen y formulario de visita
│   │   ├── services/         # Worker de procesamiento de fotos y retención
│   │   └── domain/           # Modelos de datos y estados
│   │
│   └── kippu/                # Wrapper público del paquete
│
├── assets/
│   ├── models/               # Modelos de visión por computadora
│   └── templates/            # Plantilla base del carnet (carnet_base.png)
│
├── config/
│   ├── config.example.toml   # Configuración de referencia
│   └── config.toml           # Configuración local activa
│
├── data/
│   └── jobs/                 # Registro y almacenamiento de carnets emitidos
│
└── scripts/
    ├── debug_system.py       # Diagnóstico integral de cada parte
    ├── diagnostic_linux.sh   # Lanzador rápido de diagnóstico
    ├── run_kippu.sh          # Lanzador directo del recepcionista
    ├── bootstrap_linux.sh    # Instalación de dependencias en Linux
    └── bootstrap_windows.ps1 # Instalación de dependencias en Windows
```

---

## Requisitos Previos

| Software                              | Versión mínima | Propósito                        |
| ------------------------------------- | -------------- | -------------------------------- |
| Python                                | 3.10+          | Runtime principal                |
| [uv](https://github.com/astral-sh/uv) | Recomendado    | Gestor rápido de paquetes y venv |
| CUPS (Linux) / Win32                  | —              | Impresión física o virtual       |

---

## Instalación

```bash
<<<<<<< HEAD
git clone https://github.com/CrumbSkateCEO/kippu.git
cd kippu
```

### 2. Crear el entorno virtual e instalar dependencias

**Linux:**

```bash
bash scripts/bootstrap_linux.sh
```

**Windows (PowerShell como administrador):**

```powershell
.\scripts\bootstrap_windows.ps1
```

Este script crea `.venv/`, instala todas las dependencias de `requirements.txt` y valida el entorno.

### 3. Configurar

```bash
cp config/config.example.toml config/config.toml
```

Edita `config/config.toml` según tu hardware. Los parámetros más importantes:

```toml
[camera]
source_type = "webcam" # "webcam" o "ip"
index = 0              # Índice para webcam local

# O para cámara IP / RTSP con PyAV (sin latencia):
# source_type = "ip"
# ip_url = "rtsp://frww:nc6dd3@192.168.1.10:554/live/ch0"
# rtsp_transport = "tcp"
# low_delay = true

[ptz]
enabled = false         # Activar seguimiento facial motorizado ONVIF PTZ
# Si se deja vacío, host y credenciales se extraen de camera.ip_url automáticamente
port = 8899             # Puerto ONVIF (8899, 80 o según la cámara)
pan_speed = 0.30        # Velocidad de giro horizontal
tilt_speed = 0.25       # Velocidad de giro vertical

[print]
dry_run = true      # Cambiar a false para imprimir de verdad
printer_name = ""   # Nombre exacto de la impresora en CUPS/Windows

[ui]
fullscreen = true
card_headline = "¡Bienvenido!"
=======
# Crear entorno virtual e instalar dependencias
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
>>>>>>> 35b724cc2cf70de78c503b02421cd6968d352e1b
```

---

## Diagnóstico y Pruebas del Sistema

<<<<<<< HEAD

### Modo normal

**Linux:**

```bash
bash scripts/run.sh
```

**Windows:**

```powershell
.\scripts\run.ps1
```

### Opciones disponibles

| Flag              | Descripción                                            |
| ----------------- | ------------------------------------------------------ |
| `--simulate`      | Simula cámara, saludo y rostro sin hardware real       |
| `--real-printer`  | Activa impresión real (requiere impresora configurada) |
| `--headless`      | Sin ventana gráfica (útil para tests)                  |
| `--diagnostic`    | Verifica cámara e impresora sin capturar               |
| `--ip-camera URL` | Conecta a cámara IP / RTSP con PyAV y latencia cero    |
| `--webcam INDEX`  | Selecciona el índice de la webcam local                |
| `--ptz-track`     | Activa seguimiento motorizado de rostro (ONVIF PTZ)    |

**Ejemplos:**

```bash
bash scripts/run.sh --simulate
bash scripts/run.sh --real-printer
bash scripts/run.sh --diagnostic
```

### Flujo del fotomatón

1. La cámara se activa y el sistema espera en `IDLE`.
2. Cuando detecta un **saludo con la mano** sostenido (~1 segundo), inicia el countdown.
3. Al terminar el countdown, captura el frame, recorta el rostro y genera el carnet.
4. El carnet se envía a la impresora (o se guarda en `data/jobs/` en modo dry-run).
5. La app regresa a `IDLE` lista para el siguiente visitante.

---

## Ejecución — Viernes (Asistente IA)

### Prerrequisito: tener Ollama corriendo

```bash
# Instalar Ollama desde https://ollama.com y luego:
ollama pull llama3.1
ollama serve
```

### Lanzar Viernes

```bash
.venv/bin/python -m src.viernes.core.main
```

> La primera vez descargará el modelo de voz Piper (~60-114MB según la voz) automáticamente desde HuggingFace.

### Flujo de Viernes

1. Se abre el **HUD** (pantalla fullscreen estilo J.A.R.V.I.S.) con el feed de la cámara.
2. Viernes dice "Sistemas en línea. Te escucho." al arrancar.
3. El **micrófono** escucha continuamente usando Whisper (offline).
4. Cuando detectas el fin de tu frase, el texto va al **LLM** (Ollama) para generar respuesta.
5. La respuesta se muestra en el HUD y se reproduce por el **altavoz** (Piper TTS).

### Cambiar la voz de Viernes

Editar el parámetro `model_name` al instanciar `VoiceSpeaker` en `core/main.py`:

```python
# Voces disponibles en assets/voices/:
VoiceSpeaker(model_name="es_MX-claude-high")   # Voz masculina
VoiceSpeaker(model_name="es_MX-ald-medium")    # Más ligera
VoiceSpeaker(model_name="es_AR-daniela-high")  # Por defecto (Argentina)
```

### Cambiar el modelo LLM

En `src/viernes/llm/brain.py`, modificar el parámetro `model_name`:

```python
ViernesBrain(model_name="phi3")      # Más rápido en CPU
ViernesBrain(model_name="llama3.1")  # Por defecto
```

---

## Diagnóstico y Solución de Problemas

### Verificar dispositivos

=======
Antes de iniciar el evento, podés verificar que cada parte del recepcionista funcione correctamente (cámara, IA, composición e impresora):

> > > > > > > 35b724cc2cf70de78c503b02421cd6968d352e1b

```bash
# Diagnóstico completo de todos los subsistemas:
bash scripts/diagnostic_linux.sh

# O con Python directamente:
.venv/bin/python scripts/debug_system.py
```

### Probar la impresora (incluso sin tinta)

Para verificar que el mecanismo de la impresora tome papel y funcione la orden sin errores de consumibles:

```bash
.venv/bin/python scripts/debug_system.py --print-test
```

---

## Ejecución del Recepcionista

### 1. Modo Simulación / Desarrollo (sin cámara ni impresora real)

```bash
./run_kippu.sh --simulate
```

### 2. Modo Recepcionista con Impresión Virtual (`dry_run`)

Genera los carnets en `data/jobs/` y muestra la experiencia completa en pantalla sin gastar papel:

```bash
./run_kippu.sh
```

### 3. Modo Recepcionista con Impresora Real

Envía las credenciales a la impresora física configurada en CUPS o Windows:

```bash
./run_kippu.sh --real-printer
```

> **Nota para pruebas sin tinta:** Si tu impresora no tiene tinta, podés agregar `--allow-inkless` (o dejarlo activo en `config.toml`) para que el recepcionista no se detenga por advertencias de consumibles.

---

## Flujo del Recepcionista

1. **Bienvenida / IDLE:** El recepcionista vigila el acceso en espera de un visitante.
2. **Registro de Invitado:** Si está habilitado el formulario (`guest_form_enabled = true`), solicita nombre, organización y cargo.
3. **Detección de Saludo:** Al detectar un saludo con la mano sostenido (~1 segundo), inicia la cuenta regresiva.
4. **Captura y Acreditación:** Captura el frame, recorta el rostro de forma inteligente y compone la credencial 10×15 cm a 300 DPI.
5. **Emisión:** Envía la credencial a imprimir y guarda el registro en `data/jobs/`.
6. **Retorno:** El recepcionista agradece y vuelve a `IDLE` para el siguiente visitante.

---

## Licencia

Proyecto educativo — CrumbSkate Team.
