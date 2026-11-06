"""Pipeline M3 para detección, seguimiento y estimaciones disponibles."""

import base64
import logging

import cv2
import numpy as np

from app.config import (
    DETECTOR_WEIGHTS, COLOR_MODEL_PATH, WEIGHT_MODEL_PATH, TRACK_IOU_THRESHOLD, COUNT_LINE_RATIO, MAX_BOX_AREA_RATIO,
)
from app.pipeline.color_classifier import ColorClassifier
from app.pipeline.counting_line import CountingLine
from app.pipeline.detector import YoloDetector
from app.pipeline.measurement import WeightEstimator, measure_detection
from app.pipeline.tracker import IoUTracker
from shrimp_contracts.catalog import classes_for


logger = logging.getLogger("uvicorn.error")


def _box_area(bbox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


class FramePipeline:
    """Procesa fotogramas con detección real y seguimiento."""

    def __init__(self) -> None:
        self.detector = YoloDetector(DETECTOR_WEIGHTS)
        self.color = ColorClassifier(COLOR_MODEL_PATH)
        self.weight = WeightEstimator(WEIGHT_MODEL_PATH)

    @staticmethod
    def decode_image(image_base64: str):
        """Decodifica JPEG/PNG base64 sin persistir el archivo."""
        try:
            raw = base64.b64decode(image_base64, validate=True)
        except ValueError as exc:
            raise ValueError("La imagen no contiene base64 válido.") from exc
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("No se pudo decodificar la imagen del fotograma.")
        return image

    def process(self, session, frame_id: str, image_base64: str) -> dict:
        """Devuelve detecciones y contadores del fotograma."""
        image = self.decode_image(image_base64)
        raw_detections = self.detector.detect(image, session.detection_confidence)
        height, width = image.shape[:2]
        if session.tracker is None:
            session.tracker = IoUTracker(TRACK_IOU_THRESHOLD)
            session.counting_line = CountingLine(width * COUNT_LINE_RATIO)
        tracker, line, voting = session.tracker, session.counting_line, session.voting
        catalog_classes = set(classes_for("deteccion"))
        max_area = MAX_BOX_AREA_RATIO * width * height
        shrimp = [item for item in raw_detections if item["class_name"] == "camaron"]
        if session.discard_oversized:  # video
            accepted = [item for item in shrimp if _box_area(item["bbox"]) <= max_area]
        else:  # imagen: se cuentan todos; los de primer plano llevan close_up=True para avisar
            accepted = shrimp
        oversized = len(shrimp) - len(accepted)
        rejected = [item for item in raw_detections if item["class_name"] == "no_camaron"]
        unknown = [item for item in raw_detections if item["class_name"] not in catalog_classes]
        frame_rejected = len(rejected) + len(unknown) + oversized
        session.rejected_count += frame_rejected
        if frame_rejected:
            logger.info(
                "Descartes de detección analysis_id=%s attempt=%s frame_id=%s "
                "recuadro_grande=%s no_camaron=%s clase_desconocida=%s",
                session.analysis_id, session.attempt, frame_id, oversized, len(rejected), len(unknown),
            )
        output = []
        for item in tracker.update(accepted):
            if item["hits"] < session.min_track_hits:
                continue
            x1, y1, x2, y2 = (int(round(value)) for value in item["bbox"])
            crop = image[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
            visual_condition, visual_confidence = ("no_concluyente", None)
            if crop.size and self.color.available:
                visual_condition, visual_confidence = self.color.predict(crop, session.visual_condition_confidence)
            track_id = item["track_id"]
            length_data = measure_detection(item, session)
            weight_g = self.weight.estimate([length_data["length_cm"]]) if length_data["length_cm"] is not None else None
            for field, label, confidence in (
                ("visual_condition", visual_condition, visual_confidence),
                ("integrity", item.get("integrity"), item.get("confidence")),
                ("presentation", item.get("presentation"), item.get("confidence")),
            ):
                voting.add(track_id, field, label, confidence)
            condition, condition_confidence = voting.result(
                track_id, "visual_condition", session.visual_condition_confidence,
            )
            integrity, _ = voting.result(track_id, "integrity", 0)
            presentation, _ = voting.result(track_id, "presentation", 0)
            previous = item["previous_center"]
            line.update(track_id, previous[0] if previous else None, item["center"][0])
            record = {
                "track_id": track_id, "confidence": item["confidence"], "bbox": item["bbox"],
                "integrity": integrity, "presentation": presentation,
                "visual_condition": condition, "visual_condition_confidence": condition_confidence,
                **length_data, "estimated_weight_g": weight_g,
                # Ocupa más que MAX_BOX_AREA_RATIO de la imagen: foto demasiado cercana, medida poco fiable.
                "close_up": _box_area(item["bbox"]) > max_area,
            }
            session.detections[track_id] = record
            output.append(record)
        return {
            "analysis_id": session.analysis_id, "attempt": session.attempt, "frame_id": frame_id,
            "detections": output,
            "counters": {"detected": len(output), "counted": line.count, "rejected": session.rejected_count},
            "model_mode": "inference",
        }


frame_pipeline = FramePipeline()
