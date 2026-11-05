"""Resumen de un análisis en lenguaje de planta, compartido por la página de detalle y el resultado inmediato.

Numera los camarones (Camarón 1, 2…) en orden de detección, traduce las categorías, cuenta por tamaño y prepara
los recuadros que se dibujan sobre la imagen analizada. Oculta columnas que hoy nunca tienen datos (condición
visual y peso, mientras no haya modelos entrenados).
"""

import re

from django.urls import reverse

from apps.analysis.models import AnalysisSession, ProcessingAttempt
from apps.results.models import ShrimpRecord

SIZE_NAMES = {"pequeno": "Pequeño", "mediano": "Mediano", "grande": "Grande"}
CONDITION_NAMES = {"fresco": "Fresco", "intermedio": "Intermedio", "deteriorado": "Deteriorado"}
OUT_OF_RANGE = "Fuera de rango"
NO_LENGTH = "Sin medida"


def _cm(value) -> str:
    return f"{value:.1f}".replace(".", ",") + " cm"


def _track_order(track_id: str):
    """track-2 antes que track-10 (el orden alfabético los mezclaba)."""
    match = re.search(r"(\d+)$", track_id or "")
    return (0, int(match.group(1))) if match else (1, track_id)


def _size_name(size_category, length_cm) -> str:
    if size_category in SIZE_NAMES:
        return SIZE_NAMES[size_category]
    return OUT_OF_RANGE if length_cm is not None else NO_LENGTH


def _rejected_text(count: int, source: str) -> str:
    if not count:
        return ""
    noun = "detección descartada" if count == 1 else "detecciones descartadas"
    if source == AnalysisSession.Source.VIDEO:
        return (f"{count} {noun} por ocupar más del 45 % de la imagen: suelen ser manos u objetos cerca de la "
                "cámara. Si era un camarón, aleja la cámara.")
    # Imágenes analizadas antes de que el primer plano dejara de descartarse en modo imagen.
    return (f"{count} {noun} por ocupar más del 45 % de la imagen (foto demasiado cercana). "
            "Vuelve a analizar la imagen: ahora los primeros planos se cuentan con un aviso.")


def build_summary(analysis: AnalysisSession) -> dict:
    records = sorted(ShrimpRecord.objects.of_current_attempt(analysis), key=lambda r: _track_order(r.track_id))
    numbers = {record.track_id: index for index, record in enumerate(records, start=1)}
    rows = [{
        "number": numbers[record.track_id],
        "length": _cm(record.length_cm) if record.length_cm is not None else NO_LENGTH,
        "size": _size_name(record.size_category, record.length_cm),
        "size_key": record.size_category if record.size_category in SIZE_NAMES else "otro",
        "condition": CONDITION_NAMES.get(record.visual_condition, "No concluyente"),
        "weight": (f"{record.estimated_weight_g:.1f} g (estimado)".replace(".", ",")
                   if record.estimated_weight_g is not None else "—"),
    } for record in records]

    counts = [{"key": key, "name": name, "count": sum(1 for row in rows if row["size"] == name)}
              for key, name in SIZE_NAMES.items()]
    for key, name in (("fuera", OUT_OF_RANGE), ("sin_medida", NO_LENGTH)):
        count = sum(1 for row in rows if row["size"] == name)
        if count:
            counts.append({"key": key, "name": name, "count": count})
    lengths = [record.length_cm for record in records if record.length_cm is not None]

    attempt = ProcessingAttempt.objects.filter(analysis=analysis, attempt_number=analysis.current_attempt).first()
    rows_by_track = {record.track_id: row for record, row in zip(records, rows)}
    detections = (attempt.snapshot_detections if attempt else []) or []
    close_up_tracks = {d.get("track_id") for d in detections if d.get("close_up")}
    for record, row in zip(records, rows):
        row["close_up"] = record.track_id in close_up_tracks
    boxes = []
    for detection in detections:
        row = rows_by_track.get(detection.get("track_id"))
        if row is not None:  # valores finales del camarón (en video pueden afinarse después del fotograma guardado)
            label, size_key = f"{row['number']} · {row['size']} · {row['length']}", row["size_key"]
        else:
            length = detection.get("length_cm")
            size = _size_name(detection.get("size_category"), length)
            label = f"{size} · {_cm(length)}" if length is not None else size
            size_key = detection.get("size_category") if detection.get("size_category") in SIZE_NAMES else "otro"
        boxes.append({"bbox": detection.get("bbox"), "label": label, "size_key": size_key})

    return {
        "total": len(rows),
        "rows": rows,
        "counts": counts,
        "length_avg": _cm(sum(lengths) / len(lengths)) if lengths else None,
        "length_min": _cm(min(lengths)) if lengths else None,
        "length_max": _cm(max(lengths)) if lengths else None,
        "rejected": analysis.rejected_count,
        "rejected_text": _rejected_text(analysis.rejected_count, analysis.source),
        "close_up": sum(1 for row in rows if row["close_up"]),
        # Resolución en la que se midió la calibración: si la imagen analizada no coincide, las longitudes no valen.
        "calibration_resolution": ([analysis.calibration.image_width, analysis.calibration.image_height]
                                   if analysis.calibration.image_width else None),
        "show_condition": any(row["condition"] != "No concluyente" for row in rows),
        "show_weight": any(row["weight"] != "—" for row in rows),
        "snapshot_url": (reverse("results-snapshot", args=[analysis.pk])
                         if attempt and attempt.snapshot_path else None),
        "boxes": boxes,
        "source": analysis.source,  # "imagen" o "video"
    }
