"""Construye el carnet 10×15 con el mismo diseño que la vista previa del kiosco."""

from __future__ import annotations

from pathlib import Path

from el_bienvenidor.composition.layout import CardLayout
from el_bienvenidor.domain.errors import CompositionError
from el_bienvenidor.domain.models import CardArtifact, CardData, FaceCrop, JobId
from el_bienvenidor.infra.storage import atomic_save_png, sha256_file
from el_bienvenidor.ui.theme import rounded_fill, ui_font


def _load_pillow() -> tuple[object, object, object, object]:
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
    except ModuleNotFoundError as error:
        raise CompositionError("Pillow no está instalado en este entorno.") from error
    return Image, ImageDraw, ImageFont, ImageOps


def _truetype(image_font: object, path: Path | None, size: int, *, bold: bool = False) -> object:
    if path is not None and path.is_file():
        return image_font.truetype(str(path), size=size)  # type: ignore[attr-defined]
    return ui_font(size, bold=bold)


def _centered(draw: object, text: str, y: int, font: object, width: int, color: tuple[int, int, int]) -> None:
    text = text.strip()
    if not text:
        return
    bounds = draw.textbbox((0, 0), text, font=font)  # type: ignore[attr-defined]
    x = (width - (bounds[2] - bounds[0])) // 2
    draw.text((x, y), text, fill=color, font=font)  # type: ignore[attr-defined]


def _fit_face(face: object, target_size: tuple[int, int]) -> object:
    Image, _, _, ImageOps = _load_pillow()
    resampling = getattr(Image, "Resampling", Image)
    return ImageOps.fit(face.convert("RGB"), target_size, method=resampling.LANCZOS, centering=(0.5, 0.42))  # type: ignore[attr-defined]


def compose_card(face: FaceCrop, data: CardData, layout: CardLayout, output_path: Path, job_id: JobId) -> CardArtifact:
    """Compone el PNG final; no conoce cámara, UI ni impresora."""
    layout.validate()
    Image, ImageDraw, ImageFont, _ = _load_pillow()
    width, height = layout.canvas_size
    if layout.template_path is not None and layout.template_path.is_file():
        with Image.open(layout.template_path) as template:  # type: ignore[attr-defined]
            canvas = template.convert("RGB")
        if canvas.size != layout.canvas_size:
            raise CompositionError("La plantilla debe medir exactamente 1181x1772 px.")
    else:
        canvas = Image.new("RGB", layout.canvas_size, layout.background_color)  # type: ignore[attr-defined]
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, width, layout.header_height), fill=layout.accent_color)
        draw.rectangle((0, height - layout.footer_height, width, height), fill=layout.accent_color)

    draw = ImageDraw.Draw(canvas)
    brand = _truetype(ImageFont, layout.bold_font_path or layout.font_path, 46, bold=True)
    headline_font = _truetype(ImageFont, layout.bold_font_path or layout.font_path, 54, bold=True)
    name_font = _truetype(ImageFont, layout.bold_font_path or layout.font_path, 48, bold=True)
    value_font = _truetype(ImageFont, layout.font_path, 36)
    detail_font = _truetype(ImageFont, layout.font_path, 28)
    footer_font = _truetype(ImageFont, layout.font_path, 26)

    left, top, right, bottom = layout.photo_box
    pad = 10
    rounded_fill(draw, (left - pad, top - pad, right + pad, bottom + pad), 28, layout.photo_matte, outline=layout.accent_color, width=6)
    portrait = _fit_face(face.image_rgb, (right - left, bottom - top))
    canvas.paste(portrait, (left, top))

    _centered(draw, "KIPPU", 36, brand, width, (252, 250, 247))
    _centered(draw, data.headline[:45], layout.headline_y, headline_font, width, layout.accent_color)
    _centered(draw, (data.guest_name or "VISITANTE")[:40], layout.name_y, name_font, width, layout.text_color)
    _centered(draw, (data.organization or "Organización")[:40], layout.organization_y, value_font, width, layout.muted_color)
    _centered(draw, (data.role or "Invitado")[:40], layout.role_y, value_font, width, layout.muted_color)
    issued = data.issued_at.strftime("Emitido %d/%m/%Y %H:%M")
    _centered(draw, issued, layout.detail_y, detail_font, width, layout.text_color)
    footer_y = height - 62
    _centered(draw, f"Carnet 10 × 15 cm  ·  {data.serial[:8]}", footer_y, footer_font, width, (252, 250, 247))

    atomic_save_png(canvas, output_path, layout.dpi)
    artifact = CardArtifact(job_id=job_id, png_path=output_path, pixel_size=layout.canvas_size, dpi=layout.dpi, sha256=sha256_file(output_path))
    validate_card_artifact(artifact)
    return artifact


def validate_card_artifact(artifact: CardArtifact) -> None:
    Image, _, _, _ = _load_pillow()
    if not artifact.png_path.is_file():
        raise CompositionError("No se creó el artefacto de impresión.")
    try:
        with Image.open(artifact.png_path) as image:  # type: ignore[attr-defined]
            if image.size != (1181, 1772):
                raise CompositionError(f"Dimensiones inválidas: {image.size}.")
            if image.mode not in {"RGB", "RGBA"}:
                raise CompositionError(f"Modo de imagen inválido: {image.mode}.")
            dpi = image.info.get("dpi")
    except OSError as error:
        raise CompositionError("El artefacto PNG no es legible.") from error
    if dpi is None or any(abs(float(value) - 300.0) > 1.0 for value in dpi):
        raise CompositionError(f"DPI inválido: {dpi!r}.")
    if sha256_file(artifact.png_path) != artifact.sha256:
        raise CompositionError("El hash del artefacto cambió después de componerlo.")
