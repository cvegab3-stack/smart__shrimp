"""Estado efímero de una sesión de visión dentro del proceso M3."""

from dataclasses import dataclass, field
from typing import Any

from app.pipeline.counting_line import CountingLine
from app.pipeline.tracker import IoUTracker
from app.pipeline.voting import FrameVoting


@dataclass(slots=True)
class VisionSession:
    """Configuración y datos transitorios de un intento de análisis."""

    analysis_id: str
    attempt: int
    calibration_version: int
    reference_length_cm: float | None = None
    reference_pixels: int | None = None
    size_ranges: dict[str, dict[str, float | None]] = field(default_factory=dict)
    detection_confidence: float = 0.0
    visual_condition_confidence: float = 0.0
    min_track_hits: int = 1
    # Video: se descartan cajas mayores que MAX_BOX_AREA_RATIO (suelen ser manos u objetos cerca de la cámara).
    # Imagen: el operador eligió la foto, así que se cuentan pero se marcan como primer plano (close_up).
    discard_oversized: bool = True
    detections: dict[str, dict[str, Any]] = field(default_factory=dict)
    rejected_count: int = 0
    # Seguimiento entre fotogramas; el pipeline los crea con el primer fotograma (la línea depende de su ancho).
    tracker: IoUTracker | None = None
    counting_line: CountingLine | None = None
    voting: FrameVoting = field(default_factory=FrameVoting)
