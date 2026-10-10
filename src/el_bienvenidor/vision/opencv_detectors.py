"""Detectores faciales y de pose basados exclusivamente en OpenCV.

Diseñados como alternativa robusta y de alto rendimiento que no depende
de las librerías binarias de MediaPipe (las cuales requieren instrucciones AVX).
Funciona en CPUs x86_64 sin AVX (como Intel Celeron, Atom, Pentium) y arquitecturas ARM.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys
from typing import Any

import cv2
import numpy as np
from PIL import Image

from el_bienvenidor.config import VisionSettings
from el_bienvenidor.domain.errors import FaceValidationError, VisionError
from el_bienvenidor.domain.models import (
    FaceCrop,
    FramePacket,
    GestureObservation,
    LandmarkLayer,
    LandmarkMap,
    LandmarkPoint,
)
from el_bienvenidor.vision.face_detector import FaceCropPolicy, RelativeFace, _crop_box
from el_bienvenidor.vision.mp_models import default_models_dir

LOGGER = logging.getLogger(__name__)


def cpu_has_avx() -> bool:
    """Detecta si el procesador anfitrión soporta el conjunto de instrucciones AVX."""
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("flags"):
                        flags = line.split()
                        return "avx" in flags or "avx2" in flags
        except Exception:
            pass
    return False


class OpenCVFaceDetector:
    """Detector facial basado en OpenCV YuNet (ONNX) con respaldo en Haar Cascade."""

    def __init__(self, settings: VisionSettings, models_dir: Path | None = None) -> None:
        self._settings = settings
        directory = models_dir or default_models_dir(Path.cwd())
        self._yunet: Any = None
        self._cascade: Any = None

        yunet_path = directory / "face_detection_yunet_2023mar.onnx"
        if yunet_path.exists() and yunet_path.stat().st_size > 1024:
            try:
                self._yunet = cv2.FaceDetectorYN.create(
                    str(yunet_path),
                    "",
                    (320, 320),
                    score_threshold=settings.face_confidence,
                    nms_threshold=0.3,
                    top_k=5000,
                )
                LOGGER.info("OpenCVFaceDetector: YuNet inicializado correctamente.")
            except Exception as e:
                LOGGER.warning("OpenCVFaceDetector: Error al cargar YuNet: %s", e)

        cascade_path = directory / "haarcascade_frontalface_default.xml"
        if cascade_path.exists() and cascade_path.stat().st_size > 1024:
            try:
                c = cv2.CascadeClassifier(str(cascade_path))
                if not c.empty():
                    self._cascade = c
                    LOGGER.info("OpenCVFaceDetector: Haar Cascade inicializado como respaldo.")
            except Exception as e:
                LOGGER.warning("OpenCVFaceDetector: Error al cargar Haar Cascade: %s", e)

        if self._yunet is None and self._cascade is None:
            raise VisionError(
                f"No se encontraron modelos válidos de detección facial en {directory}. "
                "Descargue face_detection_yunet_2023mar.onnx o haarcascade_frontalface_default.xml."
            )

    def detect_raw(self, image_bgr: np.ndarray) -> list[tuple[float, float, float, float, float, Any]]:
        """Devuelve lista de (x, y, w, h, score, raw_data). Coordenadas en píxeles."""
        h, w = image_bgr.shape[:2]
        faces: list[tuple[float, float, float, float, float, Any]] = []

        if self._yunet is not None:
            try:
                self._yunet.setInputSize((w, h))
                _, detections = self._yunet.detect(image_bgr)
                if detections is not None:
                    for det in detections:
                        fx, fy, fw, fh = float(det[0]), float(det[1]), float(det[2]), float(det[3])
                        score = float(det[14])
                        if fw > 0 and fh > 0 and score >= self._settings.face_confidence:
                            faces.append((fx, fy, fw, fh, score, det))
                    return faces
            except Exception as e:
                LOGGER.debug("Fallo en detección YuNet: %s", e)

        if self._cascade is not None:
            try:
                gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
                min_size = int(self._settings.minimum_face_height_px)
                detected = self._cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=4, minSize=(min_size, min_size)
                )
                for fx, fy, fw, fh in detected:
                    faces.append((float(fx), float(fy), float(fw), float(fh), 1.0, None))
            except Exception as e:
                LOGGER.debug("Fallo en detección Haar: %s", e)

        return faces

    def crop_primary_face(self, frame: FramePacket, policy: FaceCropPolicy) -> FaceCrop:
        h, w = frame.image_bgr.shape[:2]
        raw_faces = self.detect_raw(frame.image_bgr)

        if not raw_faces:
            raise FaceValidationError("No se detectó un rostro. Mire a la cámara e inténtelo de nuevo.")

        rel_faces: list[RelativeFace] = []
        for fx, fy, fw, fh, score, _ in raw_faces:
            if score >= policy.min_confidence and fw > 0 and fh > 0:
                rel_faces.append(
                    RelativeFace(
                        x=fx / w,
                        y=fy / h,
                        width=fw / w,
                        height=fh / h,
                        confidence=score,
                    )
                )

        if not rel_faces:
            raise FaceValidationError("El rostro no alcanzó la confianza mínima.")

        rel_faces.sort(key=lambda item: item.width * item.height, reverse=True)
        primary = rel_faces[0]
        primary_area = primary.width * primary.height

        if len(rel_faces) > 1 and (rel_faces[1].width * rel_faces[1].height) >= primary_area * policy.secondary_face_area_ratio:
            raise FaceValidationError("Debe haber una sola persona frente a la cámara.")

        box = _crop_box(primary, w, h, policy)
        rgb = frame.image_bgr[:, :, ::-1]
        image = Image.fromarray(rgb).crop(box)
        return FaceCrop(image_rgb=image, source_box_px=box, confidence=primary.confidence)

    def close(self) -> None:
        self._yunet = None
        self._cascade = None


class OpenCVPoseDetector:
    """Detector de pose y gestos para Kippu basado en OpenCV y movimiento.

    Detecta la presencia del usuario frente a la cámara y genera el evento de
    saludo (mano alzada / movimiento sobre el hombro). No requiere AVX.
    """

    def __init__(self, settings: VisionSettings, models_dir: Path | None = None) -> None:
        self._settings = settings
        directory = models_dir or default_models_dir(Path.cwd())
        self._face_detector = OpenCVFaceDetector(settings, directory)
        self._prev_gray: np.ndarray | None = None
        self._landmark_map: LandmarkMap | None = None

    def observe(self, frame: FramePacket) -> GestureObservation:
        h, w = frame.image_bgr.shape[:2]
        raw_faces = self._face_detector.detect_raw(frame.image_bgr)

        curr_gray = cv2.cvtColor(frame.image_bgr, cv2.COLOR_BGR2GRAY)
        motion_map = None
        if self._prev_gray is not None and self._prev_gray.shape == curr_gray.shape:
            diff = cv2.absdiff(curr_gray, self._prev_gray)
            _, motion_map = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
        self._prev_gray = curr_gray

        if not raw_faces:
            self._landmark_map = None
            return GestureObservation(
                salute_detected=False,
                wrist=None,
                shoulder=None,
                confidence=0.0,
                reason="Buscando persona frente a la cámara...",
            )

        # Seleccionar rostro principal (el más grande)
        raw_faces.sort(key=lambda item: item[2] * item[3], reverse=True)
        fx, fy, fw, fh, score, extra = raw_faces[0]

        # Construir landmark map para HUD
        face_points: list[LandmarkPoint] = []
        face_connections: list[tuple[int, int]] = []

        if extra is not None and len(extra) >= 14:
            # YuNet proporciona 5 puntos clave: ojo der, ojo izq, nariz, boca der, boca izq
            pts_idx = [(4, 5), (6, 7), (8, 9), (10, 11), (12, 13)]
            for px_i, py_i in pts_idx:
                face_points.append(
                    LandmarkPoint(
                        x=float(extra[px_i]) / w,
                        y=float(extra[py_i]) / h,
                        z=0.0,
                        visibility=1.0,
                        presence=1.0,
                    )
                )
            # Conexiones para el HUD
            face_connections = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 2)]

        # Agregar caja del rostro
        bx0, by0, bx1, by1 = fx / w, fy / h, (fx + fw) / w, (fy + fh) / h
        box_offset = len(face_points)
        face_points.extend([
            LandmarkPoint(x=bx0, y=by0),
            LandmarkPoint(x=bx1, y=by0),
            LandmarkPoint(x=bx1, y=by1),
            LandmarkPoint(x=bx0, y=by1),
        ])
        face_connections.extend([
            (box_offset, box_offset + 1),
            (box_offset + 1, box_offset + 2),
            (box_offset + 2, box_offset + 3),
            (box_offset + 3, box_offset),
        ])

        face_layer = LandmarkLayer(name="face", points=tuple(face_points), connections=tuple(face_connections))

        # Detección de saludo:
        # Estimamos hombros justo por debajo de la base del rostro
        shoulder_y = min(h, int(fy + fh * 1.15))
        shoulder_norm = ( (fx + fw * 0.5) / w, shoulder_y / h )

        # Regiones laterales superiores (a la izquierda y derecha de la cabeza, arriba del hombro)
        # Zona Izquierda (pantalla)
        z1_x0, z1_x1 = max(0, int(fx - fw * 1.6)), max(0, int(fx - fw * 0.1))
        # Zona Derecha (pantalla)
        z2_x0, z2_x1 = min(w, int(fx + fw * 1.1)), min(w, int(fx + fw * 2.6))
        z_y0 = max(0, int(fy - fh * 0.6))
        z_y1 = shoulder_y

        salute_detected = False
        hand_norm = None
        salute_conf = 0.0
        detail = "Salude con la mano o presione ESPACIO"

        # Comprobar tono de piel y movimiento en las zonas superiores
        ycrcb = cv2.cvtColor(frame.image_bgr, cv2.COLOR_BGR2YCrCb)
        cr = ycrcb[:, :, 1]
        cb = ycrcb[:, :, 2]
        skin_mask = (cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127)

        face_area_px = fw * fh
        min_hand_pixels = max(30, int(face_area_px * 0.06))

        pose_layers: list[LandmarkLayer] = [face_layer]

        for z_x0, z_x1, name in [(z1_x0, z1_x1, "left_hand"), (z2_x0, z2_x1, "right_hand")]:
            if z_x1 <= z_x0 or z_y1 <= z_y0:
                continue

            sub_skin = skin_mask[z_y0:z_y1, z_x0:z_x1]
            skin_count = int(np.sum(sub_skin))

            motion_count = 0
            if motion_map is not None:
                sub_motion = motion_map[z_y0:z_y1, z_x0:z_x1]
                motion_count = int(np.sum(sub_motion > 0))

            if skin_count >= min_hand_pixels or motion_count >= min_hand_pixels:
                # Mano detectada en la zona
                salute_detected = True
                salute_conf = min(1.0, max(skin_count, motion_count) / float(face_area_px * 0.2))
                salute_conf = max(0.7, salute_conf)

                # Centro de masa del gesto
                if skin_count >= min_hand_pixels:
                    ys, xs = np.where(sub_skin)
                    hx = z_x0 + int(np.mean(xs))
                    hy = z_y0 + int(np.mean(ys))
                else:
                    hx = (z_x0 + z_x1) // 2
                    hy = (z_y0 + z_y1) // 2

                hand_norm = (hx / w, hy / h)
                detail = f"Saludo detectado ({name})"

                # Capa visual de la mano
                hand_pt = LandmarkPoint(x=hand_norm[0], y=hand_norm[1])
                hand_layer = LandmarkLayer(name=name, points=(hand_pt,), connections=())
                pose_layers.append(hand_layer)

                # Capa de vector hombro -> mano
                shoulder_pt = LandmarkPoint(x=shoulder_norm[0], y=shoulder_norm[1])
                pose_layer = LandmarkLayer(
                    name="pose",
                    points=(shoulder_pt, hand_pt),
                    connections=((0, 1),),
                )
                pose_layers.append(pose_layer)
                break

        # Empaquetar mapa de landmarks
        pose_l = next((l for l in pose_layers if l.name == "pose"), None)
        face_l = next((l for l in pose_layers if l.name == "face"), None)
        lh_l = next((l for l in pose_layers if l.name == "left_hand"), None)
        rh_l = next((l for l in pose_layers if l.name == "right_hand"), None)
        self._landmark_map = LandmarkMap(pose=pose_l, face=face_l, left_hand=lh_l, right_hand=rh_l)

        return GestureObservation(
            salute_detected=salute_detected,
            wrist=hand_norm,
            shoulder=shoulder_norm,
            confidence=salute_conf,
            reason=detail,
        )

    def landmark_map(self) -> LandmarkMap | None:
        return self._landmark_map

    def close(self) -> None:
        self._face_detector.close()
        self._prev_gray = None
        self._landmark_map = None
