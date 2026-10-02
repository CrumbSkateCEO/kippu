"""Geometría centralizada del carnet de Kippu (misma pieza que la vista previa)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from el_bienvenidor.domain.errors import CompositionError
from el_bienvenidor.ui.theme import resolve_ui_font_path


@dataclass(frozen=True)
class CardLayout:
    canvas_size: tuple[int, int] = (1181, 1772)
    dpi: tuple[int, int] = (300, 300)
    header_height: int = 118
    footer_height: int = 96
    photo_box: tuple[int, int, int, int] = (92, 160, 1089, 980)
    headline_y: int = 1035
    name_y: int = 1135
    organization_y: int = 1225
    role_y: int = 1305
    detail_y: int = 1400
    font_path: Path | None = None
    bold_font_path: Path | None = None
    template_path: Path | None = None
    background_color: tuple[int, int, int] = (246, 241, 232)
    accent_color: tuple[int, int, int] = (32, 78, 94)
    text_color: tuple[int, int, int] = (28, 34, 38)
    muted_color: tuple[int, int, int] = (61, 74, 82)
    photo_matte: tuple[int, int, int] = (220, 227, 232)

    def validate(self) -> None:
        width, height = self.canvas_size
        if self.canvas_size != (1181, 1772) or self.dpi != (300, 300):
            raise CompositionError("El layout debe producir exactamente 1181x1772 px a 300 DPI.")
        left, top, right, bottom = self.photo_box
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise CompositionError("La zona de foto está fuera del lienzo.")
        if not (self.header_height < top and bottom < self.headline_y < self.name_y < self.organization_y < self.role_y < self.detail_y < height - 24):
            raise CompositionError("Las zonas de texto no son válidas.")


def default_layout(project_root: Path) -> CardLayout:
    template = project_root / "assets" / "templates" / "carnet_base.png"
    bundled = project_root / "assets" / "fonts" / "Inter-SemiBold.ttf"
    regular = bundled if bundled.is_file() else resolve_ui_font_path(bold=False)
    bold = resolve_ui_font_path(bold=True) or regular
    return CardLayout(
        template_path=template if template.is_file() else None,
        font_path=regular,
        bold_font_path=bold,
    )
