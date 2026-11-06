"""Guarda la imagen analizada de cada intento para mostrarla en el detalle del lote."""

import base64
import binascii
import time
from pathlib import Path

from django.conf import settings

from apps.analysis.models import AnalysisSession, ProcessingAttempt

# Video: como máximo una escritura por segundo, para no frenar la transmisión de 15 fotogramas por segundo.
VIDEO_MIN_SECONDS_BETWEEN_SAVES = 1.0
# Solo se guardan imágenes reales (las genera el navegador en JPEG; se acepta también PNG).
IMAGE_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")
DETECTION_FIELDS = ("track_id", "bbox", "length_cm", "size_category", "close_up")


def snapshot_file(analysis: AnalysisSession, attempt_number: int) -> Path:
    return Path(settings.MEDIA_ROOT) / "analyses" / str(analysis.pk) / f"attempt-{attempt_number}.jpg"


def save_snapshot(analysis: AnalysisSession, attempt_number: int, image_base64: str, detections: list[dict]) -> bool:
    """Guarda el fotograma y sus recuadros. Devuelve False si se omitió (video sin camarones o guardado hace < 1 s).

    No lanza errores: si la imagen no se puede guardar, el análisis sigue (la imagen es solo de consulta).
    """
    is_video = analysis.source == AnalysisSession.Source.VIDEO
    if is_video and not detections:
        return False  # en video se conserva el último fotograma CON camarones
    path = snapshot_file(analysis, attempt_number)
    if is_video and path.exists() and time.time() - path.stat().st_mtime < VIDEO_MIN_SECONDS_BETWEEN_SAVES:
        return False
    try:
        data = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError):
        return False
    if not data.startswith(IMAGE_SIGNATURES):
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)  # nunca queda una imagen a medio escribir
    except OSError:
        return False
    boxes = [{field: item.get(field) for field in DETECTION_FIELDS} for item in detections]
    ProcessingAttempt.objects.filter(analysis=analysis, attempt_number=attempt_number).update(
        snapshot_path=path.relative_to(settings.MEDIA_ROOT).as_posix(), snapshot_detections=boxes,
    )
    return True
