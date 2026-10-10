# Kippu

Bienvenidor para la presentación escolar de **CrumbSkate**. Combina dos módulos independientes:

- **`el_bienvenidor`** — Fotomatón que detecta saludos con la mano, captura una foto y genera un carnet impreso.
- **`viernes`** — Asistente de IA con voz, capaz de escuchar preguntas y responder con síntesis de voz neuronal offline.

---

## Estructura del Proyecto

```
kippu/
├── src/
│   ├── el_bienvenidor/       # Fotomatón (módulo principal)
│   │   ├── app.py            # Núcleo de la aplicación y loop principal
│   │   ├── config.py         # Carga de configuración TOML
│   │   ├── camera/           # Captura de video con OpenCV
│   │   ├── vision/           # Detección de poses y rostros (MediaPipe)
│   │   ├── printer/          # Impresión (CUPS en Linux, Win32 en Windows)
│   │   ├── ui/               # Vista fullscreen con OpenCV
│   │   ├── services/         # Worker de jobs y retención de datos
│   │   └── domain/           # Modelos de datos y errores
│   │
│   ├── viernes/              # Asistente IA con voz
│   │   ├── core/main.py      # Orquestador principal (PyQt6)
│   │   ├── voice/
│   │   │   ├── listener.py   # Micrófono → texto (Whisper offline)
│   │   │   └── speaker.py    # Texto → voz (Piper TTS offline)
│   │   ├── llm/brain.py      # Respuestas con Ollama (LLM local)
│   │   ├── ipcam/            # Stream RTSP/webcam con latencia cero
│   │   └── dashboard/        
│   │
│   └── kippu/                # Entry point del comando `kippu`
│
├── assets/
│   ├── voices/               # Modelos de voz Piper TTS (se descargan solos)
│   ├── models/               # Modelos MediaPipe (.task, .tflite)
│   └── templates/            # Plantilla del carnet (carnet_base.png)
│
├── config/
│   ├── config.example.toml   # Configuración de referencia
│   └── config.toml           # Tu configuración local (ignorada por git)
│
└── scripts/
    ├── bootstrap_linux.sh    # Instalación automática en Linux
    ├── bootstrap_windows.ps1 # Instalación automática en Windows
    ├── run.sh                # Lanzar en Linux
    └── run.ps1               # Lanzar en Windows
```

---

## Requisitos Previos

| Software | Versión mínima | Propósito |
|---|---|---|
| Python | 3.10+ | Runtime principal |
| [uv](https://github.com/astral-sh/uv) | Cualquiera | Gestor de entornos/paquetes |
| [Ollama](https://ollama.com) | Cualquiera | LLM local para Viernes |
| CUPS (Linux) / Win32 | — | Impresión en el fotomatón |

---

## Instalación

### 1. Clonar el repositorio(si ya tenes el repo en la compu no lo hagas claramente, solo entra al folder)

```bash
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
index = 0           # Índice de cámara (0 = webcam por defecto)

[print]
dry_run = true      # Cambiar a false para imprimir de verdad
printer_name = ""   # Nombre exacto de la impresora en CUPS/Windows

[ui]
fullscreen = true
card_headline = "¡Bienvenido!"
```

---

## Ejecución — El Bienvenidor (Fotomatón)

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

| Flag | Descripción |
|---|---|
| `--simulate` | Simula cámara, saludo y rostro sin hardware real |
| `--real-printer` | Activa impresión real (requiere impresora configurada) |
| `--headless` | Sin ventana gráfica (útil para tests) |
| `--diagnostic` | Verifica cámara e impresora sin capturar |

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

```bash
bash scripts/diagnostic_linux.sh
# o:
bash scripts/run.sh --diagnostic
```

### Errores comunes

**`No se pudo abrir el micrófono (ALSA locked)`**
```bash
fuser /dev/snd/*
pulseaudio --kill && pulseaudio --start
```

**`Error conectando con Ollama`**
```bash
ollama serve
ollama list
```

**Cámara no detectada**
- Verificar el índice en `config.toml` (`index = 0` para la primera webcam).
- En Linux: `sudo usermod -aG video $USER` y reiniciar sesión.

---

## Tecnologías del Proyecto CrumbSkate

Viernes está configurada para responder preguntas sobre el e-commerce **CrumbSkate**:

| Capa | Tecnología |
|---|---|
| Frontend | React |
| Backend | Node.js + Express |
| Base de Datos | MySQL |

---

## Licencia

Proyecto educativo — CrumbSkate Team.
