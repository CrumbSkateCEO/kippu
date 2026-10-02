# Kippu — El Bienvenidor

Kippu es un kiosco local que:

1. Pide los datos del visitante en un formulario con vista previa **tipo carnet**.
2. Muestra la cámara a pantalla completa con el **mapeo de landmarks** (esqueleto, malla facial + iris y vectores de ambas manos).
3. Detecta el saludo (mano sobre el hombro), cuenta atrás, captura, compone el carnet 10×15 e imprime en seco (`dry_run`) o con impresora real.

El mapa de landmarks vive sólo en memoria sobre el frame actual; no se guardan vídeo ni vectores.

MediaPipe 1.x usa la API Tasks (ya no existe `mp.solutions`). En el primer arranque Kippu descarga los modelos a `assets/models/` (hace falta red una vez).

Levante una mano **por encima del hombro** y manténgala ~1 s: arranca la cuenta atrás y se toma la foto.

## Debian / Ubuntu

```sh
sudo apt update
sudo apt install python3 python3-venv libgl1 libglib2.0-0 v4l-utils
# Sólo impresión física:
sudo apt install cups cups-client

bash scripts/bootstrap_linux.sh
cp config/config.example.toml config/config.toml
bash scripts/diagnostic_linux.sh
bash scripts/run.sh
```

Opciones:

| Comando | Efecto |
| --- | --- |
| `bash scripts/run.sh` | Cámara + landmarks + formulario + dry_run |
| `bash scripts/run.sh --simulate` | Recorrido completo sin hardware |
| `bash scripts/run.sh --real-printer` | Impresión vía CUPS |
| `bash scripts/run.sh --headless` | Sin ventana (automatización) |
| `bash scripts/diagnostic_linux.sh` | Sondea cámara/impresora |

`camera.backend = "auto"` prueba V4L2 → GStreamer → fallback OpenCV. El usuario debe tener acceso a `/dev/video*` (grupo `video`).

## Windows

En PowerShell nativo (sin WSL):

```powershell
.\scripts\bootstrap_windows.ps1
Copy-Item config\config.example.toml config\config.toml
.\scripts\diagnostic_windows.ps1
.\scripts\run.ps1
```

| Comando | Efecto |
| --- | --- |
| `.\scripts\run.ps1` | Cámara + landmarks + formulario + dry_run |
| `.\scripts\run.ps1 -Simulate` | Sin hardware |
| `.\scripts\run.ps1 -RealPrinter` | Impresión Win32/GDI |
| `.\scripts\run.ps1 -Headless` | Sin ventana |
| `.\scripts\diagnostic_windows.ps1` | Sondeo de dispositivos |

## Formulario tipo carnet

Al llegar a `IDLE`, Kippu abre una pantalla con un carnet vertical editable:

- **Nombre** (obligatorio; Esc deja `VISITANTE`)
- **Organización**
- **Rol / cargo**

`Tab` / `Enter` cambia de campo; en el último campo `Enter` (o `F1`) confirma. Con `ask_guest_each_job = true` se vuelve a pedir tras cada impresión. Los campos se imprimen etiquetados en el PNG 1181×1772 @ 300 DPI.

## Landmarks

Con `ui.show_landmarks = true` (por defecto) se dibujan:

- Pose (esqueleto)
- Cara (teselado + contornos + iris)
- Mano izquierda y derecha (21 puntos + conexiones)

## Pruebas

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

PowerShell:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

La especificación histórica está en [docs/EL_BIENVENIDOR_MASTER.md](docs/EL_BIENVENIDOR_MASTER.md). Para operación diaria use este README y `config/config.example.toml`.
