"""Detección de un único rostro y creación de un crop estable para la tarjeta."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pathlib import Path

from el_bienvenidor.config import VisionSettings
from el_bienvenidor.domain.errors import FaceValidationError, VisionError
from el_bienvenidor.domain.models import FaceCrop, FramePacket
from el_bienvenidor.vision.mp_models import default_models_dir, ensure_model


@dataclass(frozen=True)
class FaceCropPolicy:
    min_confidence: float
    secondary_face_area_ratio: float
    minimum_face_height_px: int
    target_aspect_ratio: float = 0.75
    face_width_fraction: float = 0.46
    face_vertical_anchor: float = 0.48

    @classmethod
    def from_settings(cls, settings: VisionSettings) -> "FaceCropPolicy":
        return cls(
            min_confidence=settings.face_confidence,
            secondary_face_area_ratio=settings.secondary_face_area_ratio,
            minimum_face_height_px=settings.minimum_face_height_px,
        )


@dataclass(frozen=True)
class RelativeFace:
    x: float
    y: float
    width: float
    height: float
    confidence: float


class FaceDetector(Protocol):
    def crop_primary_face(self, frame: FramePacket, policy: FaceCropPolicy) -> FaceCrop: ...
    def close(self) -> None: ...


def _clamp_crop(box: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    crop_width = right - left
    crop_height = bottom - top
    if crop_width > width or crop_height > height:
        return (0, 0, width, height)
    left = min(max(0.0, left), width - crop_width)
    top = min(max(0.0, top), height - crop_height)
    return (round(left), round(top), round(left + crop_width), round(top + crop_height))


def _crop_box(face: RelativeFace, image_width: int, image_height: int, policy: FaceCropPolicy) -> tuple[int, int, int, int]:
    face_width = face.width * image_width
    face_height = face.height * image_height
    if face_height < policy.minimum_face_height_px:
        raise FaceValidationError("Acérquese un poco más a la cámara.")
    crop_width = face_width / policy.face_width_fraction
    crop_height = crop_width / policy.target_aspect_ratio
    center_x = (face.x + face.width / 2) * image_width
    face_center_y = (face.y + face.height / 2) * image_height
    top = face_center_y - crop_height * policy.face_vertical_anchor
    left = center_x - crop_width / 2
    return _clamp_crop((left, top, left + crop_width, top + crop_height), image_width, image_height)


class MediaPipeFaceDetector:
    def __init__(self, settings: VisionSettings, models_dir: Path | None = None) -> None:
        try:
            import mediapipe as mp
            from mediapipe.tasks.python.core.base_options import BaseOptions
            from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions, RunningMode
        except ModuleNotFoundError as error:
            raise VisionError("MediaPipe no está instalado en este entorno.") from error
        directory = models_dir or default_models_dir(Path.cwd())
        model_path = ensure_model("face_detect", directory)
        self._mp = mp
        self._detector = FaceDetector.create_from_options(
            FaceDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(model_path)),
                running_mode=RunningMode.IMAGE,
                min_detection_confidence=settings.face_confidence,
            )
        )

    def crop_primary_face(self, frame: FramePacket, policy: FaceCropPolicy) -> FaceCrop:
        try:
            from PIL import Image
        except ModuleNotFoundError as error:
            raise VisionError("Pillow no está instalado en este entorno.") from error
        height, width = frame.image_bgr.shape[:2]
        try:
            rgb = frame.image_bgr[:, :, ::-1].copy()
            result = self._detector.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        except Exception as error:
            raise FaceValidationError(f"No se pudo analizar el rostro: {error}") from error
        detections = getattr(result, "detections", None) or []
        if not detections:
            raise FaceValidationError("No se detectó un rostro. Mire a la cámara e inténtelo de nuevo.")
        faces: list[RelativeFace] = []
        for detection in detections:
            categories = getattr(detection, "categories", None) or []
            confidence = float(categories[0].score) if categories else 0.0
            box = detection.bounding_box
            if confidence >= policy.min_confidence and box.width > 0 and box.height > 0:
                faces.append(
                    RelativeFace(
                        box.origin_x / width,
                        box.origin_y / height,
                        box.width / width,
                        box.height / height,
                        confidence,
                    )
                )
        if not faces:
            raise FaceValidationError("El rostro no alcanzó la confianza mínima.")
        faces.sort(key=lambda item: item.width * item.height, reverse=True)
        primary = faces[0]
        primary_area = primary.width * primary.height
        if len(faces) > 1 and (faces[1].width * faces[1].height) >= primary_area * policy.secondary_face_area_ratio:
            raise FaceValidationError("Debe haber una sola persona frente a la cámara.")
        image_height, image_width = frame.image_bgr.shape[:2]
        box = _crop_box(primary, image_width, image_height, policy)
        rgb = frame.image_bgr[:, :, ::-1]
        image = Image.fromarray(rgb).crop(box)
        return FaceCrop(image_rgb=image, source_box_px=box, confidence=primary.confidence)

    def close(self) -> None:
        close = getattr(self._detector, "close", None)
        if callable(close):
            close()

