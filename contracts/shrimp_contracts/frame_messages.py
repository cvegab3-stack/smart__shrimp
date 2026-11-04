"""Mensajes tipados para el procesamiento de imágenes y fotogramas."""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class FrameRequest:
    """Carga útil de un fotograma que Django envía al servicio de visión."""

    analysis_id: str
    attempt: int
    frame_id: str
    captured_at: datetime
    image_base64: str
    calibration_version: int

    def to_dict(self) -> dict[str, Any]:
        """Serializa el mensaje con fecha ISO 8601."""
        payload = asdict(self)
        payload["captured_at"] = self.captured_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class Detection:
    """Resultado de un camarón detectado en un fotograma."""

    track_id: str
    confidence: float
    bbox: tuple[float, float, float, float]
    integrity: str | None = None
    presentation: str | None = None
    visual_condition: str | None = None
    visual_condition_confidence: float | None = None
    length_cm: float | None = None
    size_category: str | None = None
    estimated_weight_g: float | None = None


@dataclass(frozen=True, slots=True)
class FrameResponse:
    """Respuesta estructurada del servicio para un fotograma."""

    analysis_id: str
    attempt: int
    frame_id: str
    detections: tuple[Detection, ...]
    counters: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado a tipos JSON compatibles."""
        return asdict(self)
