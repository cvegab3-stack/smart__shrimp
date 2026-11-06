"""Detector YOLO opcional; sin pesos no fabrica detecciones."""

from pathlib import Path
from typing import Any


class DetectorUnavailable(RuntimeError):
    """No hay pesos YOLO instalados para procesar imágenes reales."""


class YoloDetector:
    """Adaptador de YOLO con carga diferida de pesos locales."""

    def __init__(self, weights_path: str = "") -> None:
        self.weights_path = Path(weights_path) if weights_path else None
        self._model = None

    @property
    def available(self) -> bool:
        return bool(self.weights_path and self.weights_path.is_file())

    def _load(self):
        if self._model is None:
            if not self.available:
                raise DetectorUnavailable("No se configuraron pesos YOLO; revise DETECTOR_WEIGHTS.")
            from ultralytics import YOLO

            self._model = YOLO(str(self.weights_path))
        return self._model

    def warmup(self) -> None:
        """Carga los pesos e inicializa la GPU antes de la primera petición real."""
        if self.available:
            import numpy as np

            self._load()(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False)

    def detect(self, image, confidence: float) -> list[dict[str, Any]]:
        """Devuelve cuadros y etiquetas del catálogo detectados por YOLO."""
        results = self._load()(image, conf=confidence, verbose=False)
        detections: list[dict[str, Any]] = []
        for result in results:
            names = result.names
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                class_id = int(box.cls[0].item())
                detections.append({
                    # Un modelo de una clase (entrenado con single_cls) guarda el nombre "item".
                    "class_name": "camaron" if len(names) == 1 else names[class_id],
                    "confidence": float(box.conf[0].item()),
                    "bbox": tuple(float(value) for value in box.xyxy[0].tolist()),
                })
        return detections
