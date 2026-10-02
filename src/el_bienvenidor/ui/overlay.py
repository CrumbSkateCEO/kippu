"""HUD de kiosco y mapa de landmarks, sin decisiones de flujo."""

from __future__ import annotations

from typing import Any

from el_bienvenidor.domain.models import AppSnapshot, AppState, LandmarkLayer, LandmarkMap
from el_bienvenidor.ui.theme import NAVY, rounded_fill, ui_font


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


def _draw_hud_text(image_bgr: Any, snapshot: AppSnapshot) -> Any:
    Image, ImageDraw = _pil()
    rgb = image_bgr[:, :, ::-1]
    canvas = Image.fromarray(rgb).convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    width, height = canvas.size
    title_font = ui_font(max(22, width // 42))
    message_font = ui_font(max(20, width // 48))
    hint_font = ui_font(max(16, width // 64))
    draw.text((32, 22), "Kippu", font=title_font, fill=(252, 250, 247, 255))
    draw.text((32, 56), "Carnet de bienvenida", font=hint_font, fill=(214, 176, 140, 255))
    message = snapshot.message
    bbox = draw.textbbox((0, 0), message, font=message_font)
    text_w = bbox[2] - bbox[0]
    pill = (max(24, (width - text_w) // 2 - 28), height - 108, min(width - 24, (width + text_w) // 2 + 28), height - 48)
    rounded_fill(draw, pill, 22, (22, 42, 62, 220), outline=(214, 176, 140, 180), width=2)
    draw.text(((width - text_w) // 2, height - 94), message, font=message_font, fill=(252, 250, 247, 255))
    if snapshot.state is AppState.COUNTDOWN and snapshot.countdown_value is not None:
        count = str(snapshot.countdown_value)
        count_font = ui_font(max(96, width // 8))
        cb = draw.textbbox((0, 0), count, font=count_font)
        cx = width // 2
        cy = height // 2 - 20
        radius = max(90, width // 10)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(214, 176, 140, 230), width=8)
        draw.text((cx - (cb[2] - cb[0]) // 2, cy - (cb[3] - cb[1]) // 2 - 8), count, font=count_font, fill=(252, 250, 247, 255))
    elif snapshot.greeting_elapsed_s > 0:
        hold = min(1.0, snapshot.greeting_elapsed_s / 1.0)
        bar_w = int(width * 0.42)
        x = (width - bar_w) // 2
        y = height - 150
        rounded_fill(draw, (x, y, x + bar_w, y + 14), 7, (40, 50, 58, 200))
        rounded_fill(draw, (x, y, x + max(18, int(bar_w * hold)), y + 14), 7, (96, 196, 120, 255))
    return _numpy().asarray(canvas.convert("RGB"))[:, :, ::-1].copy()


def draw_overlay(image_bgr: Any, snapshot: AppSnapshot) -> Any:
    height, width = image_bgr.shape[:2]
    canvas = image_bgr.copy()
    _blend_rect(canvas, (0, 0, width, 92), NAVY, 0.55)
    _blend_rect(canvas, (0, height - 168, width, height), NAVY, 0.42)
    return _draw_hud_text(canvas, snapshot)


_LANDMARK_COLORS = {
    "pose": (120, 196, 96),
    "face": (160, 188, 220),
    "left_hand": (210, 140, 255),
    "right_hand": (90, 200, 255),
}


def _pixel(point: Any, width: int, height: int, mirrored: bool) -> tuple[int, int]:
    x = 1.0 - float(point.x) if mirrored else float(point.x)
    y = float(point.y)
    return (round(min(1.0, max(0.0, x)) * (width - 1)), round(min(1.0, max(0.0, y)) * (height - 1)))


def _draw_layer(canvas: Any, layer: LandmarkLayer, mirrored: bool) -> None:
    cv2 = _cv2()
    height, width = canvas.shape[:2]
    color = _LANDMARK_COLORS[layer.name]
    line_width = 1 if layer.name == "face" else 2
    point_radius = 1 if layer.name == "face" else 3
    for start, end in layer.connections:
        if start < len(layer.points) and end < len(layer.points):
            cv2.line(canvas, _pixel(layer.points[start], width, height, mirrored), _pixel(layer.points[end], width, height, mirrored), color, line_width, cv2.LINE_AA)
    if layer.name != "face":
        for point in layer.points:
            cv2.circle(canvas, _pixel(point, width, height, mirrored), point_radius, color, -1, cv2.LINE_AA)


def draw_landmark_map(image_bgr: Any, landmark_map: LandmarkMap | None, *, mirrored: bool) -> Any:
    """Dibuja vectores de pose, contorno facial e iris, y ambas manos."""
    if landmark_map is None:
        return image_bgr
    cv2 = _cv2()
    canvas = image_bgr.copy()
    for layer in landmark_map.layers():
        _draw_layer(canvas, layer, mirrored)
    return cv2.addWeighted(canvas, 0.55, image_bgr, 0.45, 0)
