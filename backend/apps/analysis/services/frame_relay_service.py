"""Reenvío de fotogramas desde Django al servicio privado de visión."""

from django.db import transaction

from apps.accounts.services import record_event
from apps.analysis.models import AnalysisSession, ProcessingAttempt
from apps.analysis.services.session_service import mark_error
from integrations import vision_client


def relay_frame(*, analysis_id, attempt_number: int, frame_id: str, captured_at: str, image_base64: str, operator, ip_address: str | None = None):
    """Valida propiedad y estado antes de reenviar el fotograma a M3."""
    try:
        with transaction.atomic():
            analysis = AnalysisSession.objects.select_for_update().select_related("calibration").get(
                pk=analysis_id, operator=operator,
            )
            if analysis.status != AnalysisSession.Status.IN_PROGRESS or analysis.current_attempt != attempt_number:
                raise ValueError("El análisis no está en curso para este intento.")
            attempt = ProcessingAttempt.objects.get(
                analysis=analysis, attempt_number=attempt_number, status=AnalysisSession.Status.IN_PROGRESS,
            )
            return vision_client.process_frame({
                "analysis_id": str(analysis.pk), "attempt": attempt_number, "frame_id": frame_id,
                "captured_at": captured_at.isoformat() if hasattr(captured_at, "isoformat") else captured_at,
                "image_base64": image_base64,
                "calibration_version": analysis.calibration.version,
            })
    except vision_client.VisionServiceError as exc:
        # Fuera de la transacción: si se marcara dentro, la excepción desharía el estado de error.
        mark_error(analysis, attempt, "vision_unavailable", str(exc))
        record_event("analysis.frame_failed", operator, {"analysis_id": str(analysis.pk), "attempt": attempt_number}, ip_address)
        raise
