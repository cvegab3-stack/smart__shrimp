"""Acumula decisiones por separado para cada dimensión de clasificación."""

from collections import Counter, defaultdict


class FrameVoting:
    """Guarda votos independientes y devuelve el valor más frecuente."""

    def __init__(self) -> None:
        self._votes: dict[str, dict[str, list[tuple[str, float | None]]]] = defaultdict(lambda: defaultdict(list))

    def add(self, track_id: str, field: str, label: str | None, confidence: float | None = None) -> None:
        """Añade un voto para una dimensión específica."""
        if label is not None:
            self._votes[track_id][field].append((label, confidence))

    def result(self, track_id: str, field: str, minimum_confidence: float) -> tuple[str | None, float | None]:
        """Devuelve moda y confianza media; condición visual débil es no concluyente."""
        votes = self._votes[track_id].get(field, [])
        if not votes:
            return ("no_concluyente", None) if field == "visual_condition" else (None, None)
        label = Counter(value for value, _ in votes).most_common(1)[0][0]
        confidences = [score for value, score in votes if value == label and score is not None]
        mean_confidence = sum(confidences) / len(confidences) if confidences else None
        if field == "visual_condition" and (mean_confidence is None or mean_confidence < minimum_confidence):
            return "no_concluyente", mean_confidence
        return label, mean_confidence
