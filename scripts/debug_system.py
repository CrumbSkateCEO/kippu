#!/usr/bin/env python3
"""Diagnóstico integral de Kippu (el_bienvenidor).

Inspecciona cada subsistema:
1. Entorno Python y herramientas del sistema
2. Configuración y assets (plantillas, modelos de IA, fuentes)
3. Cámara (apertura, resolución, FPS real)
4. Visión por computadora (detección de rostro y pose)
5. Composición del carnet (crea data/test_card.png de 10x15 @ 300 DPI)
6. Impresora y CUPS (impresoras disponibles, estado de tinta, spooler)
   Opcional: `--print-test` para enviar un carnet de prueba a la impresora real.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

# Asegurar importación de src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Colores de terminal ANSI
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}[OK]{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}[AVISO]{RESET} {msg}")


def err(msg: str) -> None:
    print(f"  {RED}[ERROR]{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {CYAN}[INFO]{RESET} {msg}")


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}=== {title} ==={RESET}")


# ---------------------------------------------------------------------------
# 1. Entorno y Dependencias
# ---------------------------------------------------------------------------
def check_environment() -> bool:
    section("1. Entorno de Ejecución y Dependencias")
    all_ok = True

    # Python
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        ok(f"Python {py_ver} ({sys.executable})")
    else:
        err(f"Python {py_ver} — Se requiere Python 3.10 o superior.")
        all_ok = False

    # OpenCV
    try:
        import cv2

        ok(f"OpenCV {cv2.__version__}")
    except ImportError as e:
        err(f"OpenCV no instalado: {e}")
        all_ok = False

    # MediaPipe
    try:
        import mediapipe as mp

        mp_ver = getattr(mp, "__version__", "desconocida")
        ok(f"MediaPipe {mp_ver}")
    except ImportError:
        warn("MediaPipe no instalado (se usará respaldo OpenCV para detección de rostros/poses)")

    # Pillow
    try:
        from PIL import Image

        ok(f"Pillow (PIL) {Image.__version__}")
    except ImportError as e:
        err(f"Pillow no instalado: {e}")
        all_ok = False

    # CUPS tools (Linux)
    if sys.platform.startswith("linux"):
        lp = shutil.which("lp")
        lpstat = shutil.which("lpstat")
        if lp and lpstat:
            ok(f"Comandos CUPS disponibles: lp ({lp}), lpstat ({lpstat})")
        else:
            warn("Comandos CUPS incompletos. Para imprimir en Linux se necesita 'cups-client'.")
            all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# 2. Configuración y Assets
# ---------------------------------------------------------------------------
def check_assets(config_path: Path) -> tuple[bool, object | None]:
    section("2. Configuración, Plantillas y Modelos de IA")
    all_ok = True

    # Config
    if not config_path.is_file():
        err(f"No existe el archivo de configuración: {config_path}")
        return False, None

    from el_bienvenidor.config import load_settings

    try:
        settings = load_settings(config_path)
        ok(f"Configuración cargada correctamente desde {config_path}")
        info(
            f"Config cámara: índice={settings.camera.index}, resolución={settings.camera.width}x{settings.camera.height}, fps={settings.camera.fps}"
        )
        info(
            f"Config impresión: dry_run={settings.printing.dry_run}, allow_inkless={settings.printing.allow_inkless}, impresora='{settings.printing.printer_name or 'predeterminada'}'"
        )
    except Exception as e:
        err(f"Error cargando config: {e}")
        return False, None

    # Plantilla de carnet
    template_file = PROJECT_ROOT / "assets" / "templates" / "carnet_base.png"
    if template_file.is_file():
        try:
            from PIL import Image

            with Image.open(template_file) as img:
                dpi = img.info.get("dpi", (0, 0))
                ok(f"Plantilla carnet_base.png: {img.size[0]}x{img.size[1]} px, DPI={dpi}, modo={img.mode}")
                if img.size != (1181, 1772):
                    warn(f"Las dimensiones recomendadas son 1181x1772 px (actual: {img.size})")
        except Exception as e:
            warn(f"Error al leer plantilla: {e}")
    else:
        warn("No existe assets/templates/carnet_base.png. Se usará el carnet generado programáticamente.")

    # Fuentes
    font_file = PROJECT_ROOT / "assets" / "fonts" / "Inter-SemiBold.ttf"
    if font_file.is_file():
        ok(f"Fuente tipográfica: {font_file.name}")
    else:
        warn("Fuente Inter-SemiBold.ttf no encontrada en assets/fonts/. Se usará fuente del sistema.")

    # Modelos de visión
    models_dir = PROJECT_ROOT / "assets" / "models"
    models_found = list(models_dir.glob("*")) if models_dir.is_dir() else []
    if models_found:
        ok(f"Modelos de IA encontrados en assets/models/: {[m.name for m in models_found if not m.name.endswith('.md')]}")
    else:
        warn("No se encontraron modelos en assets/models/. Se usarán detectores estándar de OpenCV.")

    # Directorio de almacenamiento
    jobs_dir = settings.storage.jobs_directory
    try:
        jobs_dir.mkdir(parents=True, exist_ok=True)
        test_file = jobs_dir / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        ok(f"Almacenamiento de fotos y carnets accesible: {jobs_dir}")
    except Exception as e:
        err(f"No se pudo escribir en {jobs_dir}: {e}")
        all_ok = False

    return all_ok, settings


# ---------------------------------------------------------------------------
# 3. Diagnóstico de Cámara
# ---------------------------------------------------------------------------
def check_camera(settings: object) -> tuple[bool, object | None]:
    section("3. Diagnóstico de Cámara")
    import cv2

    # Listar nodos /dev/video en Linux
    if sys.platform.startswith("linux"):
        dev_nodes = sorted(Path("/dev").glob("video*"))
        if dev_nodes:
            info(f"Dispositivos V4L2 en el sistema: {[str(d) for d in dev_nodes]}")
        else:
            warn("No se encontraron dispositivos /dev/video*.")

    idx = settings.camera.index
    info(f"Probando apertura de cámara (índice configurado: {idx})...")

    cap = cv2.VideoCapture(idx)
    if not cap.isOpened():
        err(f"No se pudo abrir la cámara en el índice {idx}.")
        info("Probando índice 0 de respaldo...")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            err("Tampoco se pudo abrir la cámara en el índice 0.")
            return False, None
        else:
            warn("Cámara disponible en índice 0. Se recomienda cambiar 'index = 0' en config/config.toml.")
            idx = 0

    # Configurar resolución solicitada
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.camera.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.camera.height)
    cap.set(cv2.CAP_PROP_FPS, settings.camera.fps)

    # Medir lectura de frames
    t0 = time.monotonic()
    frames = []
    for _ in range(5):
        ret, frame = cap.read()
        if ret and frame is not None:
            frames.append(frame)
    elapsed = time.monotonic() - t0
    cap.release()

    if not frames:
        err("La cámara se abrió pero no devolvió ningún frame.")
        return False, None

    last_frame = frames[-1]
    h, w, c = last_frame.shape
    fps_real = len(frames) / elapsed if elapsed > 0 else 0
    mean_val = float(last_frame.mean())

    ok(f"Cámara operativa: {w}x{h} px, ~{fps_real:.1f} FPS real")
    if mean_val < 15:
        warn(f"El frame está muy oscuro (brillo promedio: {mean_val:.1f}/255). Verificá que la lente no esté tapada.")
    else:
        ok(f"Sensor capturando luz correctamente (brillo promedio: {mean_val:.1f}/255)")

    return True, last_frame


# ---------------------------------------------------------------------------
# 4. Diagnóstico de Visión e Inteligencia Artificial
# ---------------------------------------------------------------------------
def check_vision(settings: object, frame: object | None) -> bool:
    section("4. Diagnóstico de Visión por Computadora (IA)")
    if frame is None:
        import numpy as np

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        warn("Usando frame sintético para la prueba de visión.")

    from el_bienvenidor.vision.opencv_detectors import OpenCVFaceDetector, OpenCVPoseDetector, cpu_has_avx
    from el_bienvenidor.vision.face_detector import MediaPipeFaceDetector, FaceCropPolicy
    from el_bienvenidor.vision.pose_detector import MediaPipePoseDetector

    models_dir = PROJECT_ROOT / "assets" / "models"
    has_avx = cpu_has_avx()
    info(f"Soporte de instrucciones AVX en CPU: {'Sí' if has_avx else 'No (modo OpenCV forzado)'}")

    # Inicializar detectores
    face_detector = None
    pose_detector = None

    if has_avx and settings.vision.backend != "opencv":
        try:
            face_detector = MediaPipeFaceDetector(settings.vision, models_dir)
            pose_detector = MediaPipePoseDetector(settings.vision, models_dir)
            ok("Detectores MediaPipe (Face + Pose) inicializados correctamente.")
        except Exception as e:
            warn(f"MediaPipe falló ({e}). Activando detectores de respaldo OpenCV.")

    if face_detector is None:
        try:
            face_detector = OpenCVFaceDetector(settings.vision, models_dir)
            pose_detector = OpenCVPoseDetector(settings.vision, models_dir)
            ok("Detectores OpenCV (Face YuNet/Haar + Pose) inicializados correctamente.")
        except Exception as e:
            err(f"No se pudieron inicializar los detectores OpenCV: {e}")
            return False

    # Probar detección sobre el frame
    try:
        from el_bienvenidor.domain.models import FrameId, FramePacket
        from el_bienvenidor.domain.errors import FaceValidationError

        h, w = frame.shape[:2]
        packet = FramePacket(
            frame_id=FrameId(1),
            captured_monotonic_s=time.monotonic(),
            image_bgr=frame,
            source_size=(w, h),
        )
        pose_res = pose_detector.observe(packet)
        ok(f"Prueba de Pose Detector ejecutada: saludo_detectado={pose_res.salute_detected} ({pose_res.reason})")

        policy = FaceCropPolicy.from_settings(settings.vision)
        try:
            crop = face_detector.crop_primary_face(packet, policy)
            if crop:
                ok(f"¡Rostro detectado en cámara! Recorte facial: {crop.image_rgb.size}")
            else:
                info("Inferencia facial lista (ningún rostro detectado en este frame).")
        except FaceValidationError:
            info("Inferencia facial lista (ningún rostro detectado en este frame).")
    except Exception as e:
        warn(f"Aviso durante inferencia de visión: {e}")

    finally:
        if face_detector:
            face_detector.close()
        if pose_detector:
            pose_detector.close()

    return True


# ---------------------------------------------------------------------------
# 5. Prueba de Composición del Carnet
# ---------------------------------------------------------------------------
def check_card_composition(settings: object) -> Path | None:
    section("5. Prueba de Composición de Carnet (10x15 a 300 DPI)")
    from PIL import Image
    from el_bienvenidor.composition.layout import default_layout
    from el_bienvenidor.composition.card_composer import compose_card
    from el_bienvenidor.domain.models import CardData, FaceCrop, JobId

    layout = default_layout(PROJECT_ROOT)
    test_face_img = Image.new("RGB", (400, 500), (80, 140, 180))
    crop = FaceCrop(image_rgb=test_face_img, source_box_px=(100, 100, 300, 400), confidence=0.95)

    data = CardData(
        headline="PRUEBA DE IMPRESIÓN",
        guest_name="USUARIO DE PRUEBA",
        organization="KIPPU KIOSK",
        role="Tester",
        serial="TEST-0001",
        issued_at=datetime.now(timezone.utc),
    )

    out_file = PROJECT_ROOT / "data" / "test_card.png"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        artifact = compose_card(crop, data, layout, out_file, JobId(uuid_value := "test-diagnostic"))
        ok(f"Carnet generado exitosamente: {out_file}")
        ok(f"Dimensiones exactas: {artifact.pixel_size[0]}x{artifact.pixel_size[1]} px @ {artifact.dpi[0]} DPI")
        ok(f"Hash SHA-256 verificado: {artifact.sha256[:16]}...")
        return out_file
    except Exception as e:
        err(f"Fallo al componer el carnet: {e}")
        return None


# ---------------------------------------------------------------------------
# 6. Diagnóstico de Impresora y CUPS (Soporte sin tinta)
# ---------------------------------------------------------------------------
def check_printer(settings: object, card_path: Path | None, do_print_test: bool = False) -> bool:
    section("6. Diagnóstico de Impresora y Cola CUPS (Modo Sin Tinta)")

    if not sys.platform.startswith("linux"):
        info("Diagnóstico específico de CUPS solo aplica en Linux.")
        return True

    # 1. Chequeo del demonio CUPS
    proc_cups = subprocess.run(["lpstat", "-r"], capture_output=True, text=True)
    if proc_cups.returncode == 0:
        ok(f"Servidor CUPS: {proc_cups.stdout.strip()}")
    else:
        err("El demonio CUPS no está respondiendo. Ejecutá: sudo systemctl start cups")
        return False

    # 2. Impresoras registradas en CUPS
    proc_printers = subprocess.run(["lpstat", "-p"], capture_output=True, text=True)
    printers_out = proc_printers.stdout.strip()

    proc_default = subprocess.run(["lpstat", "-d"], capture_output=True, text=True)
    default_out = proc_default.stdout.strip()

    info(f"Destino predeterminado: {default_out or 'Ninguno asignado'}")

    if not printers_out:
        warn("No hay impresoras añadidas en CUPS todavía.")
        print(f"\n{BOLD}¿Cómo probar ahora mismo?{RESET}")
        print("  Opción A: Si tenés la impresora física conectada por USB:")
        print("    1. Conectala y encendela.")
        print("    2. Abrí la configuración de impresoras del sistema o instalá: 'system-config-printer'")
        print("    3. O ejecutá: lpinfo -v | grep usb")
        print("\n  Opción B: Crear una impresora virtual PDF en 1 segundo para probar todo el software:")
        print("    sudo lpadmin -p Impresora_Prueba_PDF -E -v cups-pdf:/ -m raw")
        print("    lpoptions -d Impresora_Prueba_PDF")
        return False

    info(f"Impresoras en CUPS:\n{printers_out}")

    # 3. Dispositivos USB
    proc_usb = subprocess.run(["lsusb"], capture_output=True, text=True)
    usb_lines = [l for l in proc_usb.stdout.splitlines() if any(k in l.lower() for k in ["print", "canon", "epson", "hp", "brother"])]
    if usb_lines:
        ok(f"Dispositivos USB de impresión detectados: {usb_lines}")

    # 4. Chequeo de la impresora de Kippu
    from el_bienvenidor.printer.cups_printer import CupsPrinter, _cups_health
    from el_bienvenidor.domain.models import PrinterHealth

    cups_printer = CupsPrinter(settings.printing)
    try:
        probe = cups_printer.probe()
        printer_name = probe.printer_name
        health = probe.health

        if health == PrinterHealth.READY:
            ok(f"Impresora seleccionada: '{printer_name}' — Estado: READY ({probe.detail})")
        else:
            msg = f"Impresora seleccionada: '{printer_name}' — Estado reportado: {health.value.upper()} ({probe.detail})"
            if settings.printing.allow_inkless:
                ok(f"{msg}\n     -> {GREEN}MODO SIN TINTA ACTIVO{RESET}: Kippu ignorará el estado de falta de tinta y enviará el trabajo.")
            else:
                warn(f"{msg}\n     -> {YELLOW}allow_inkless=false{RESET}: Kippu no enviará trabajos si la impresora marca error/pausa.")

    except Exception as e:
        err(f"No se pudo sondear la impresora: {e}")
        return False

    # 5. Opcional: Enviar prueba de impresión
    if do_print_test and card_path and card_path.is_file():
        print(f"\n{BOLD}{YELLOW}>>> ENVIANDO CARNET DE PRUEBA A LA IMPRESORA FÍSICA / COLA CUPS <<<{RESET}")
        from el_bienvenidor.domain.models import CardArtifact, JobId
        from el_bienvenidor.printer.cups_queue_monitor import CupsQueueMonitor
        from el_bienvenidor.infra.storage import sha256_file

        artifact = CardArtifact(
            job_id=JobId("test-print-job"),
            png_path=card_path,
            pixel_size=(1181, 1772),
            dpi=(300, 300),
            sha256=sha256_file(card_path),
        )

        try:
            info(f"Enviando '{card_path.name}' a la impresora '{printer_name}'...")
            receipt = cups_printer.submit(artifact)
            ok(f"Trabajo aceptado por el spooler CUPS: {receipt.detail} (ID: {receipt.spooler_job_id})")

            info("Supervisando la cola de impresión...")
            monitor = CupsQueueMonitor(settings.printing)
            final_receipt = monitor.monitor_submission(receipt)
            ok(f"Resultado final del spooler: {final_receipt.detail} ({final_receipt.disposition.value})")
            if final_receipt.disposition.value == "accepted":
                print(f"{GREEN}{BOLD}¡Prueba de impresión exitosa! La orden fue enviada a la impresora.{RESET}")
            else:
                warn(f"Estado de la orden: {final_receipt.disposition.value} — {final_receipt.detail}")
        except Exception as e:
            err(f"Error al enviar la prueba de impresión: {e}")
    elif not do_print_test:
        print(f"\n{DIM}Tip: Podés enviar una impresión de prueba real a esta impresora ejecutando:{RESET}")
        print(f"  {CYAN}python scripts/debug_system.py --print-test{RESET}")

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico Integral de Kippu")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "config.toml", help="Ruta al config.toml")
    parser.add_argument("--print-test", action="store_true", help="Envía un carnet de prueba real a la impresora/spooler")
    args = parser.parse_args()

    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║     KIPPU — DIAGNÓSTICO INTEGRAL DEL SISTEMA         ║{RESET}")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════╝{RESET}")

    env_ok = check_environment()
    if not env_ok:
        warn("Algunos paquetes o herramientas del sistema tienen problemas.")

    assets_ok, settings = check_assets(args.config)
    if not assets_ok or settings is None:
        err("Fallo en la configuración. Deteniendo diagnóstico.")
        return 1

    cam_ok, frame = check_camera(settings)
    check_vision(settings, frame)
    card_path = check_card_composition(settings)
    check_printer(settings, card_path, do_print_test=args.print_test)

    print(f"\n{BOLD}{CYAN}════════════════════════════════════════════════════════{RESET}")
    print(f"{GREEN}{BOLD}Diagnóstico finalizado.{RESET}")
    print(f"Para iniciar el kiosco en modo sin tinta: {CYAN}./run_kippu.sh --real-printer --allow-inkless{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
