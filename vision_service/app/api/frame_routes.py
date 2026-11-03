"""Rutas protegidas de inicialización y procesamiento de fotogramas."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_service_token
from app.pipeline.color_classifier import ColorModelUnavailable
from app.pipeline.frame_pipeline import frame_pipeline
from app.session.session_registry import session_registry

router = APIRouter(prefix="/v1", dependencies=[Depends(require_service_token)])


class SessionStart(BaseModel):
    """Configuración de la sesión recibida desde Django."""

    analysis_id: str
    attempt: int = Field(ge=1)
    calibration_version: int = Field(ge=1)
    source: str = "imagen"
    reference_length_cm: float | None = Field(default=None, gt=0)
    reference_pixels: int | None = Field(default=None, gt=0)
    size_ranges: dict = Field(default_factory=dict)
    detection_confidence: float = Field(ge=0, le=1)
    visual_condition_confidence: float = Field(ge=0, le=1)


class FrameInput(BaseModel):
    """Fotograma en base64 enviado exclusivamente por Django."""

    analysis_id: str
    attempt: int = Field(ge=1)
    frame_id: str
    captured_at: datetime
    image_base64: str = Field(min_length=1)
    calibration_version: int = Field(ge=1)


@router.post("/sessions")
def start_session(payload: SessionStart):
    """Abre de forma idempotente el estado efímero de un intento."""
    session = session_registry.start(payload.model_dump())
    return {"analysis_id": session.analysis_id, "attempt": session.attempt, "status": "en_curso"}


@router.post("/frames")
def process_frame(payload: FrameInput):
    """Procesa un fotograma y responde al servidor Django."""
    try:
        session = session_registry.get(payload.analysis_id, payload.attempt)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if session.calibration_version != payload.calibration_version:
        raise HTTPException(status_code=409, detail="La versión de calibración no coincide con la sesión.")
    try:
        return frame_pipeline.process(session, payload.frame_id, payload.image_base64)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ColorModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
