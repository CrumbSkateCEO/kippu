"""Paleta y tipografía compartidas de la UI de kiosco."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys
from typing import Any


# BGR para OpenCV
NAVY = (62, 42, 22)
CREAM = (236, 241, 246)
GOLD = (140, 176, 214)
WHITE = (252, 250, 247)
MUTED = (168, 164, 158)
ACCENT = (94, 78, 32)
TEAL = (148, 122, 42)
OK = (120, 196, 96)
HOLD = (90, 200, 255)


def _font_candidates(*, bold: bool = False) -> tuple[Path, ...]:
    if bold:
        named = (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
            Path("C:/Windows/Fonts/segoeuib.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
        )
    else:
        named = (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
            Path("C:/Windows/Fonts/segoeui.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        )
    extra: list[Path] = []
    if sys.platform.startswith("linux"):
        pattern = "**/*DejaVuSans-Bold.ttf" if bold else "**/*DejaVuSans.ttf"
        extra.extend(Path("/usr/share/fonts").glob(pattern))
    return named + tuple(extra)


def resolve_ui_font_path(*, bold: bool = False) -> Path | None:
    for path in _font_candidates(bold=bold):
        if path.is_file():
            return path
    if bold:
        return resolve_ui_font_path(bold=False)
    return None


@lru_cache(maxsize=16)
def ui_font(size: int, *, bold: bool = False) -> Any:
    from PIL import ImageFont

    path = resolve_ui_font_path(bold=bold)
    if path is not None:
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def rounded_fill(draw: Any, box: tuple[int, int, int, int], radius: int, fill: tuple[int, int, int], outline: tuple[int, int, int] | None = None, width: int = 1) -> None:
    try:
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
    except Exception:
        draw.rectangle(box, fill=fill, outline=outline, width=width)
