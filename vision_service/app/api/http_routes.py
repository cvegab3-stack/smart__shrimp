"""Rutas de salud y resumen final del pipeline."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from collections import Counter

from app.api.auth import require_service_token
from app.session.session_registry import session_registry

router = APIRouter(prefix="/v1", dependencies=[Depends(require_service_token)])


class SummaryRequest(BaseModel):
    """Identifica el análisis y el intento solicitados por Django."""

    analysis_id: str
    attempt: int = Field(ge=1)


@router.get("/health")
def health():
    """Indica disponibilidad básica sin exponer datos del modelo."""
    return {"status": "ok", "model_mode": "inference"}


@router.post("/sessions/summary")
def session_summary(payload: SummaryRequest):
    """Devuelve resumen de registros observados sin inventar ejemplares."""
    try:
        session = session_registry.get(payload.analysis_id, payload.attempt)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    shrimp = list(session.detections.values())
    def distribution(field: str) -> dict[str, int]:
        return dict(Counter(row[field] for row in shrimp if row.get(field) is not None))

    return {
        "analysis_id": session.analysis_id, "attempt": session.attempt,
        "shrimp": shrimp, "shrimp_count": len(shrimp), "rejected_count": session.rejected_count,
        "totals": {
            "integrity": distribution("integrity"),
            "presentation": distribution("presentation"),
            "visual_condition": distribution("visual_condition"),
            "size_category": distribution("size_category"),
            "rejected": session.rejected_count,
        },
        "model_mode": "inference",
        "model_status": "configured",
    }
