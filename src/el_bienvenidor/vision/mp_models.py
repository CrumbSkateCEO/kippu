"""Descarga y caché de bundles MediaPipe Tasks (API 1.x, sin mp.solutions)."""

from __future__ import annotations

from pathlib import Path
import urllib.request

from el_bienvenidor.domain.errors import VisionError

_MODELS = {
    "holistic": (
        "holistic_landmarker.task",
        "https://storage.googleapis.com/mediapipe-models/holistic_landmarker/holistic_landmarker/float16/latest/holistic_landmarker.task",
    ),
    "pose": (
        "pose_landmarker_lite.task",
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    ),
    "hands": (
        "hand_landmarker.task",
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
    ),
    "face_mesh": (
        "face_landmarker.task",
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
    ),
    "face_detect": (
        "blaze_face_short_range.tflite",
        "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
    ),
    "yunet": (
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
    "haarcascade": (
        "haarcascade_frontalface_default.xml",
        "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/haarcascade_frontalface_default.xml",
    ),
}


def default_models_dir(project_root: Path) -> Path:
    return project_root / "assets" / "models"


def ensure_model(kind: str, models_dir: Path) -> Path:
    if kind not in _MODELS:
        raise VisionError(f"Modelo MediaPipe desconocido: {kind}")
    filename, url = _MODELS[kind]
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / filename
    if target.is_file() and target.stat().st_size > 1024:
        return target
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        urllib.request.urlretrieve(url, temporary)
        temporary.replace(target)
    except Exception as error:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
        raise VisionError(f"No se pudo descargar el modelo {kind}: {error}") from error
    if not target.is_file() or target.stat().st_size < 1024:
        raise VisionError(f"El modelo {kind} quedó incompleto.")
    return target
