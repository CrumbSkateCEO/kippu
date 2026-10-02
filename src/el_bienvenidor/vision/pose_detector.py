"""Conversión de pose MediaPipe Tasks a la regla de saludo de Kippu."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from el_bienvenidor.config import VisionSettings
from el_bienvenidor.domain.errors import VisionError
from el_bienvenidor.domain.models import FramePacket, GestureObservation, LandmarkLayer, LandmarkMap, LandmarkPoint
from el_bienvenidor.vision.mp_models import default_models_dir, ensure_model

LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_WRIST, RIGHT_WRIST = 15, 16
LEFT_PINKY, RIGHT_PINKY = 17, 18
LEFT_INDEX, RIGHT_INDEX = 19, 20


@dataclass(frozen=True)
class Landmark:
    x: float
    y: float
    visibility: float
    presence: float


@dataclass(frozen=True)
class PoseLandmarks:
    left_wrist: Landmark | None
    left_shoulder: Landmark | None
    right_wrist: Landmark | None
    right_shoulder: Landmark | None
    left_tips: tuple[Landmark, ...] = field(default_factory=tuple)
    right_tips: tuple[Landmark, ...] = field(default_factory=tuple)


class PoseDetector(Protocol):
    def observe(self, frame: FramePacket) -> GestureObservation: ...
    def landmark_map(self) -> LandmarkMap | None: ...
    def close(self) -> None: ...


def _confidence(point: Landmark) -> float:
    visibility = point.visibility if point.visibility > 0 else 1.0
    presence = point.presence if point.presence > 0 else 1.0
    return min(visibility, presence)


def _candidate(points: tuple[Landmark | None, ...], shoulder: Landmark | None, settings: VisionSettings) -> tuple[bool, float, Landmark | None]:
    if shoulder is None:
        return False, 0.0, None
    shoulder_conf = _confidence(shoulder)
    usable: list[tuple[float, Landmark]] = []
    for point in points:
        if point is None:
            continue
        conf = min(_confidence(point), shoulder_conf)
        if conf >= settings.landmark_confidence:
            usable.append((conf, point))
    if not usable:
        confidences = [_confidence(point) for point in points if point is not None]
        return False, min(confidences, default=0.0) if confidences else 0.0, None
    conf, best = min(usable, key=lambda item: item[1].y)
    return best.y < shoulder.y - settings.vertical_margin, conf, best


def is_salute(landmarks: PoseLandmarks, settings: VisionSettings) -> GestureObservation:
    left_points = (landmarks.left_wrist, *landmarks.left_tips)
    right_points = (landmarks.right_wrist, *landmarks.right_tips)
    left_ok, left_conf, left_point = _candidate(left_points, landmarks.left_shoulder, settings)
    right_ok, right_conf, right_point = _candidate(right_points, landmarks.right_shoulder, settings)
    if left_ok and (not right_ok or left_conf >= right_conf) and left_point is not None and landmarks.left_shoulder is not None:
        return GestureObservation(True, (left_point.x, left_point.y), (landmarks.left_shoulder.x, landmarks.left_shoulder.y), left_conf, "Mano izquierda sobre hombro")
    if right_ok and right_point is not None and landmarks.right_shoulder is not None:
        return GestureObservation(True, (right_point.x, right_point.y), (landmarks.right_shoulder.x, landmarks.right_shoulder.y), right_conf, "Mano derecha sobre hombro")
    return GestureObservation(False, None, None, max(left_conf, right_conf), "No hay saludo válido")


def _as_landmark(point: Any) -> Landmark | None:
    if point is None:
        return None
    x = getattr(point, "x", None)
    y = getattr(point, "y", None)
    if x is None or y is None:
        return None
    visibility = float(getattr(point, "visibility", None) or 1.0)
    presence = float(getattr(point, "presence", None) or 1.0)
    return Landmark(float(x), float(y), visibility, presence)


def _layer_from_points(name: str, points: Any, connections: Any) -> LandmarkLayer | None:
    if not points:
        return None
    mapped = tuple(
        LandmarkPoint(
            x=float(point.x or 0.0),
            y=float(point.y or 0.0),
            z=float(getattr(point, "z", 0.0) or 0.0),
            visibility=float(getattr(point, "visibility", 1.0) or 1.0),
            presence=float(getattr(point, "presence", 1.0) or 1.0),
        )
        for point in points
    )
    edges = tuple(sorted((int(item.start), int(item.end)) for item in connections))
    return LandmarkLayer(name=name, points=mapped, connections=edges)


def _first_person(value: Any) -> list[Any]:
    if not value:
        return []
    first = value[0]
    if hasattr(first, "x"):
        return list(value)
    return list(first) if first else []


def _to_mp_image(frame: FramePacket, mp: Any) -> Any:
    import numpy as np

    rgb = np.ascontiguousarray(frame.image_bgr[:, :, ::-1])
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)


def _close(task: Any) -> None:
    closer = getattr(task, "close", None)
    if callable(closer):
        closer()


class MediaPipePoseDetector:
    """Pose, manos y cara con Tasks separados. Evita HolisticLandmarker, que aborta el proceso."""

    def __init__(self, settings: VisionSettings, models_dir: Path | None = None) -> None:
        try:
            import mediapipe as mp
            from mediapipe.tasks.python.core.base_options import BaseOptions
            from mediapipe.tasks.python.vision import (
                FaceLandmarker,
                FaceLandmarkerOptions,
                FaceLandmarksConnections,
                HandLandmarker,
                HandLandmarkerOptions,
                HandLandmarksConnections,
                PoseLandmarker,
                PoseLandmarkerOptions,
                PoseLandmarksConnections,
                RunningMode,
            )
        except ModuleNotFoundError as error:
            raise VisionError("MediaPipe no está instalado en este entorno.") from error
        directory = models_dir or default_models_dir(Path.cwd())
        self._mp = mp
        self._settings = settings
        self._landmark_map: LandmarkMap | None = None
        self._pose_connections = PoseLandmarksConnections.POSE_LANDMARKS
        self._hand_connections = HandLandmarksConnections.HAND_CONNECTIONS
        self._face_connections = tuple(FaceLandmarksConnections.FACE_LANDMARKS_CONTOURS) + tuple(
            FaceLandmarksConnections.FACE_LANDMARKS_LEFT_IRIS
        ) + tuple(FaceLandmarksConnections.FACE_LANDMARKS_RIGHT_IRIS)
        min_pose = max(0.3, settings.landmark_confidence - 0.2)
        self._pose = PoseLandmarker.create_from_options(
            PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(ensure_model("pose", directory))),
                running_mode=RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=settings.pose_detection_confidence,
                min_pose_presence_confidence=min_pose,
                min_tracking_confidence=min_pose,
            )
        )
        self._hands = HandLandmarker.create_from_options(
            HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(ensure_model("hands", directory))),
                running_mode=RunningMode.IMAGE,
                num_hands=2,
                min_hand_detection_confidence=0.4,
                min_hand_presence_confidence=0.4,
                min_tracking_confidence=0.4,
            )
        )
        self._face = FaceLandmarker.create_from_options(
            FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(ensure_model("face_mesh", directory))),
                running_mode=RunningMode.IMAGE,
                num_faces=1,
                min_face_detection_confidence=0.4,
                min_face_presence_confidence=0.4,
                min_tracking_confidence=0.4,
            )
        )

    def observe(self, frame: FramePacket) -> GestureObservation:
        if frame.image_bgr is None:
            self._landmark_map = None
            return GestureObservation(False, None, None, 0.0, "Sin imagen")
        try:
            image = _to_mp_image(frame, self._mp)
            pose_result = self._pose.detect(image)
            hands_result = self._hands.detect(image)
            face_result = self._face.detect(image)
        except Exception as error:
            self._landmark_map = None
            return GestureObservation(False, None, None, 0.0, f"Error de pose: {error}")
        pose = _first_person(getattr(pose_result, "pose_landmarks", None))
        faces = getattr(face_result, "face_landmarks", None) or []
        face = _first_person(faces)
        left_hand: list[Any] = []
        right_hand: list[Any] = []
        hand_sets = getattr(hands_result, "hand_landmarks", None) or []
        handedness = getattr(hands_result, "handedness", None) or []
        for index, points in enumerate(hand_sets):
            label = ""
            if index < len(handedness) and handedness[index]:
                label = (getattr(handedness[index][0], "category_name", "") or "").lower()
            if "left" in label:
                left_hand = list(points)
            else:
                right_hand = list(points)
        self._landmark_map = LandmarkMap(
            pose=_layer_from_points("pose", pose, self._pose_connections),
            face=_layer_from_points("face", face, self._face_connections),
            left_hand=_layer_from_points("left_hand", left_hand, self._hand_connections),
            right_hand=_layer_from_points("right_hand", right_hand, self._hand_connections),
        )
        if len(pose) <= RIGHT_INDEX:
            return GestureObservation(False, None, None, 0.0, "No se detectó pose")

        def at(index: int) -> Landmark | None:
            return _as_landmark(pose[index]) if index < len(pose) else None

        left_tips = tuple(item for item in (at(LEFT_INDEX), at(LEFT_PINKY)) if item is not None)
        right_tips = tuple(item for item in (at(RIGHT_INDEX), at(RIGHT_PINKY)) if item is not None)
        if left_hand:
            converted = _as_landmark(min(left_hand, key=lambda item: float(item.y or 1.0)))
            if converted is not None:
                left_tips = (*left_tips, converted)
        if right_hand:
            converted = _as_landmark(min(right_hand, key=lambda item: float(item.y or 1.0)))
            if converted is not None:
                right_tips = (*right_tips, converted)
        return is_salute(
            PoseLandmarks(
                left_wrist=at(LEFT_WRIST),
                left_shoulder=at(LEFT_SHOULDER),
                right_wrist=at(RIGHT_WRIST),
                right_shoulder=at(RIGHT_SHOULDER),
                left_tips=left_tips,
                right_tips=right_tips,
            ),
            self._settings,
        )

    def landmark_map(self) -> LandmarkMap | None:
        return self._landmark_map

    def close(self) -> None:
        _close(self._pose)
        _close(self._hands)
        _close(self._face)
