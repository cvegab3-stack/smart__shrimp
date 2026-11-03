"""Clasificador de color con salida conservadora ante ausencia de artefacto."""

from pathlib import Path

import cv2
import numpy as np

from shrimp_contracts.catalog import classes_for


class ColorModelUnavailable(RuntimeError):
    """No hay un clasificador entrenado para afirmar una condición visual."""


class ColorClassifier:
    """Predice condición visual desde características de color HSV."""

    def __init__(self, model_path: str = "") -> None:
        self.model_path = Path(model_path) if model_path else None
        self._model = None

    @property
    def available(self) -> bool:
        return bool(self.model_path and self.model_path.is_file())

    def _load(self):
        if self._model is None:
            if not self.available:
                return None
            import joblib

            self._model = joblib.load(self.model_path)
        return self._model

    def predict(self, crop, minimum_confidence: float) -> tuple[str, float | None]:
        """Devuelve clase por probabilidad o no concluyente sin modelo."""
        model = self._load()
        if model is None:
            raise ColorModelUnavailable("No hay un modelo de color; no se puede emitir condición visual.")
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        features = np.mean(hsv.reshape(-1, 3), axis=0).reshape(1, -1)
        probabilities = model.predict_proba(features)[0]
        best_index = int(np.argmax(probabilities))
        confidence = float(probabilities[best_index])
        label = str(model.classes_[best_index])
        if label not in set(classes_for("condicion_visual")) - {"no_concluyente"}:
            return "no_concluyente", confidence
        if confidence < minimum_confidence:
            return "no_concluyente", confidence
        return label, confidence
