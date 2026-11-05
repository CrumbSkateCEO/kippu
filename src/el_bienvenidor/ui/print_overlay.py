"""Pantalla post-foto: muestra el carnet compuesto y el estado de impresión.

Se activa cuando ``AppSnapshot.state`` es ``PROCESSING`` o ``PRINTING``.
Reemplaza el feed de cámara con:
  - Miniatura del carnet (cuando ya fue compuesto)
  - Indicador de estado animado (spinner de puntos o barra de progreso)
  - Nombre de impresora y detalle CUPS
  - Aviso visual si ``allow_inkless`` está activo
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from el_bienvenidor.domain.models import AppSnapshot, AppState
from el_bienvenidor.ui.theme import NAVY, rounded_fill, ui_font


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _cv2() -> Any:
    try:
        import cv2
    except ModuleNotFoundError as error:
        raise RuntimeError("OpenCV no está instalado.") from error
    return cv2


def _numpy() -> Any:
    try:
        import numpy as np
    except ModuleNotFoundError as error:
        raise RuntimeError("NumPy no está instalado.") from error
    return np


def _pil() -> tuple[Any, Any]:
    from PIL import Image, ImageDraw
    return Image, ImageDraw


def _blend_rect(image: Any, box: tuple[int, int, int, int], color: tuple[int, int, int], alpha: float) -> None:
    np = _numpy()
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(image.shape[1], x1), min(image.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        return
    region = image[y0:y1, x0:x1]
    overlay = np.full_like(region, color)
    image[y0:y1, x0:x1] = (region * (1.0 - alpha) + overlay * alpha).astype(region.dtype)


def _load_card_thumbnail(card_path: Path, target_h: int) -> Any | None:
    """Carga el PNG del carnet y lo escala para que encaje en ``target_h``."""
    try:
        Image, _ = _pil()
        img = Image.open(card_path).convert("RGB")
        ratio = target_h / img.height
        new_w = int(img.width * ratio)
        thumb = img.resize((new_w, target_h), Image.LANCZOS)
        # Convertir RGB → BGR para OpenCV
        np = _numpy()
        return np.array(thumb)[:, :, ::-1]
    except Exception:
        return None


def _spinner_text(tick: int, steps: int = 8) -> str:
    """Devuelve un carácter giratorio basado en el tick de animación."""
    chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    return chars[tick % len(chars)]


def _dots_text(elapsed_s: float) -> str:
    """Genera un texto animado de puntos suspensivos."""
    dots = int(elapsed_s * 2) % 4
    return "·" * dots


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def draw_print_screen(
    image_bgr: Any,
    snapshot: AppSnapshot,
    *,
    allow_inkless: bool = False,
    printer_name: str | None = None,
) -> Any:
    """Renderiza la pantalla post-foto sobre ``image_bgr``.

    Args:
        image_bgr: Frame base (puede ser negro si no hay cámara activa).
        snapshot: Estado actual de la aplicación. Debe tener ``state`` en
            ``{PROCESSING, PRINTING}``. Si ``card_path`` está disponible se
            muestra la miniatura.
        allow_inkless: Si True, se muestra un aviso amarillo de modo sin tinta.
        printer_name: Nombre de la impresora configurada (para mostrarlo en UI).

    Returns:
        Nuevo ``ndarray`` BGR con la pantalla post-foto renderizada.
    """
    np = _numpy()
    Image, ImageDraw = _pil()

    height, width = image_bgr.shape[:2]
    # Fondo oscuro semitransparente sobre el frame base
    canvas = image_bgr.copy()
    _blend_rect(canvas, (0, 0, width, height), NAVY, 0.82)

    # --- Área de la miniatura del carnet ---
    card_area_w = int(width * 0.38)
    card_area_h = int(height * 0.78)
    card_x0 = int(width * 0.04)
    card_y0 = (height - card_area_h) // 2

    card_thumb = None
    if snapshot.card_path is not None and snapshot.card_path.is_file():
        card_thumb = _load_card_thumbnail(snapshot.card_path, card_area_h)

    if card_thumb is not None:
        th, tw = card_thumb.shape[:2]
        cx = card_x0 + (card_area_w - tw) // 2
        cy = card_y0 + (card_area_h - th) // 2
        # Sombra
        _blend_rect(canvas, (cx - 6, cy - 6, cx + tw + 6, cy + th + 6), (0, 0, 0), 0.55)
        # Miniatura
        canvas[cy : cy + th, cx : cx + tw] = card_thumb
    else:
        # Placeholder cuando aún se está componiendo
        ph_x0, ph_y0 = card_x0, card_y0
        ph_x1, ph_y1 = card_x0 + card_area_w, card_y0 + card_area_h
        _blend_rect(canvas, (ph_x0, ph_y0, ph_x1, ph_y1), (30, 42, 55), 0.6)

    # --- Panel derecho con información ---
    info_x = card_x0 + card_area_w + int(width * 0.06)
    info_w = width - info_x - int(width * 0.04)

    # Convertir a PIL para texto
    rgb = canvas[:, :, ::-1]
    pil_canvas = Image.fromarray(rgb).convert("RGBA")
    draw = ImageDraw.Draw(pil_canvas, "RGBA")

    # Tipografías
    title_font = ui_font(max(28, width // 36), bold=True)
    body_font = ui_font(max(20, width // 52))
    small_font = ui_font(max(15, width // 70))
    badge_font = ui_font(max(13, width // 78), bold=True)

    # --- Título de estado ---
    state_label, state_color = _state_info(snapshot.state)
    rounded_fill(
        draw,
        (info_x, 60, info_x + info_w, 110),
        18,
        (*state_color, 230),
        outline=(214, 176, 140, 180),
        width=2,
    )
    sb = draw.textbbox((0, 0), state_label, font=title_font)
    sw = sb[2] - sb[0]
    draw.text((info_x + (info_w - sw) // 2, 70), state_label, font=title_font, fill=(252, 250, 247, 255))

    # --- Mensaje principal ---
    msg_y = 130
    message = snapshot.message
    draw.text((info_x, msg_y), message, font=body_font, fill=(220, 215, 205, 230), stroke_width=0)

    # --- Animación: si PROCESSING → spinner; si PRINTING → barra de progreso ---
    anim_y = msg_y + 52
    elapsed = snapshot.state_since_monotonic_s  # lo usamos como semilla de animación
    if snapshot.state is AppState.PROCESSING:
        tick = int(elapsed * 10) % 10
        spinner = _spinner_text(tick)
        dots = _dots_text(elapsed)
        anim_text = f"{spinner} Componiendo carnet{dots}"
        draw.text((info_x, anim_y), anim_text, font=body_font, fill=(120, 196, 96, 240))
    elif snapshot.state is AppState.PRINTING:
        # Barra de progreso indeterminada
        bar_w = info_w
        bar_h = 12
        bar_y = anim_y + 8
        rounded_fill(draw, (info_x, bar_y, info_x + bar_w, bar_y + bar_h), 6, (28, 40, 50, 210))
        # Bloque deslizante
        t = (elapsed * 0.4) % 1.0
        block_w = int(bar_w * 0.35)
        block_x = info_x + int((bar_w - block_w) * abs(math.sin(t * math.pi)))
        rounded_fill(draw, (block_x, bar_y, block_x + block_w, bar_y + bar_h), 6, (120, 196, 96, 240))
        dots = _dots_text(elapsed)
        draw.text((info_x, anim_y - 24), f"Enviando a impresora{dots}", font=body_font, fill=(120, 196, 96, 240))

    # --- Nombre de impresora y detalle CUPS ---
    detail_y = anim_y + 80
    if printer_name:
        draw.text((info_x, detail_y), f"🖨  {printer_name}", font=small_font, fill=(180, 195, 210, 210))
        detail_y += 30
    if snapshot.print_detail:
        # Cortar si es muy largo
        detail_text = snapshot.print_detail
        if len(detail_text) > 72:
            detail_text = detail_text[:69] + "…"
        draw.text((info_x, detail_y), detail_text, font=small_font, fill=(160, 170, 180, 185))
        detail_y += 28

    # --- Aviso allow_inkless ---
    if allow_inkless:
        warn_text = "⚠  Modo sin tinta activo (prueba)"
        rounded_fill(
            draw,
            (info_x, detail_y + 10, info_x + info_w, detail_y + 44),
            10,
            (60, 90, 10, 200),
            outline=(180, 160, 20, 200),
            width=2,
        )
        draw.text((info_x + 10, detail_y + 15), warn_text, font=small_font, fill=(240, 220, 60, 255))

    # --- Pie: nombre del job ---
    if snapshot.job_id is not None:
        job_short = str(snapshot.job_id)[:8].upper()
        draw.text(
            (info_x, height - 44),
            f"JOB #{job_short}",
            font=small_font,
            fill=(100, 115, 130, 150),
        )

    result = np.asarray(pil_canvas.convert("RGB"))[:, :, ::-1].copy()
    return result


def _state_info(state: AppState) -> tuple[str, tuple[int, int, int]]:
    """Devuelve la etiqueta y el color de fondo para el badge de estado."""
    return {
        AppState.PROCESSING: ("COMPONIENDO CARNET", (20, 48, 32)),
        AppState.PRINTING:   ("ENVIANDO A IMPRIMIR", (10, 36, 60)),
    }.get(state, (state.value.upper(), (28, 32, 42)))
