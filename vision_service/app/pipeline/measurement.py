"""Estimación de longitud calibrada, categoría y peso sin modelo ficticio."""

from pathlib import Path

from app.pipeline.calibration import pixels_to_cm


class WeightEstimator:
    """Cargador preparado para el regresor de peso cuando exista un artefacto."""

    def __init__(self, model_path: str = "") -> None:
        self.model_path = Path(model_path) if model_path else None
        self._model = None

    @property
    def available(self) -> bool:
        return bool(self.model_path and self.model_path.is_file())

    def estimate(self, features: list[float]) -> float | None:
        """Estima el peso o devuelve None mientras no haya modelo validado."""
        if not self.available:
            return None
        if self._model is None:
            import joblib

            self._model = joblib.load(self.model_path)
        return float(self._model.predict([features])[0])


def measure_detection(detection: dict, session) -> dict:
    """Calcula longitud por caja y categoría usando los rangos versionados."""
    if session.reference_length_cm is None or session.reference_pixels is None:
        return {"length_cm": None, "size_category": None}
    x1, y1, x2, y2 = detection["bbox"]
    length_px = max(abs(x2 - x1), abs(y2 - y1))
    length_cm = pixels_to_cm(length_px, session.reference_length_cm, session.reference_pixels)
    category = None
    # De menor a mayor: si dos rangos comparten el límite (pequeño hasta 8, mediano desde 8), esa medida cuenta en
    # la categoría menor, sin depender del orden en que se guardaron las claves.
    ordered = sorted(session.size_ranges.items(),
                     key=lambda item: float("-inf") if item[1].get("min_cm") is None else item[1]["min_cm"])
    for label, bounds in ordered:
        lower = bounds.get("min_cm")
        upper = bounds.get("max_cm")
        if (lower is None or length_cm >= lower) and (upper is None or length_cm <= upper):
            category = label
            break
    return {"length_cm": length_cm, "size_category": category}
