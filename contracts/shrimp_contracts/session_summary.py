"""Resumen final producido por visión y persistido por Django."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ShrimpResult:
    """Mediciones y clasificaciones de un ejemplar seguido en la sesión."""

    track_id: str
    integrity: str | None
    presentation: str | None
    visual_condition: str
    visual_condition_confidence: float | None
    length_cm: float | None
    size_category: str | None
    estimated_weight_g: float | None


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """Resumen completo de una ejecución de análisis."""

    analysis_id: str
    attempt: int
    shrimp: tuple[ShrimpResult, ...]
    rejected_count: int

    @property
    def shrimp_count(self) -> int:
        """Cantidad de ejemplares aceptados en el resumen."""
        return len(self.shrimp)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el resumen a un diccionario JSON."""
        return asdict(self) | {
            "shrimp_count": self.shrimp_count,
            "totals": {
                "integrity": _count_by(self.shrimp, "integrity"),
                "presentation": _count_by(self.shrimp, "presentation"),
                "visual_condition": _count_by(self.shrimp, "visual_condition"),
                "size_category": _count_by(self.shrimp, "size_category"),
                "rejected": self.rejected_count,
            },
        }


def _count_by(results: tuple[ShrimpResult, ...], field: str) -> dict[str, int]:
    """Agrupa un campo categórico sin mezclar clasificaciones distintas."""
    counts: dict[str, int] = {}
    for result in results:
        value = getattr(result, field)
        if value is None:
            continue
        counts[value] = counts.get(value, 0) + 1
    return counts
