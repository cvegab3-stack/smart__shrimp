"""Reenvío de fotogramas desde Django al servicio privado de visión."""

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.services import record_event
from apps.analysis.errors import INPUT, get_error
from apps.analysis.models import AnalysisSession, ProcessingAttempt
from apps.analysis.services.session_service import mark_error
from integrations import vision_client


class AnalysisNotInProgress(ValueError):
    """El análisis ya no admite fotogramas (finalizado, con error o reintentado en otra pestaña)."""


def relay_frame(*, analysis_id, attempt_number: int, frame_id: str, captured_at: str, image_base64: str, operator,
                ip_address: str | None = None):
    """Valida propiedad y estado antes de reenviar el fotograma a M3.

    Si el servicio rechaza la imagen (error de entrada), el análisis sigue en curso y se relanza el error para que
    el operador elija otra. Si el servicio falla (transitorio o configuración), el intento queda con error.
    """
    try:
        with transaction.atomic():
            analysis = AnalysisSession.objects.select_for_update().select_related("calibration").get(
                pk=analysis_id, operator=operator,
            )
            if analysis.status != AnalysisSession.Status.IN_PROGRESS or analysis.current_attempt != attempt_number:
                raise AnalysisNotInProgress("Este análisis ya no está en curso para este intento.")
            attempt = ProcessingAttempt.objects.get(
                analysis=analysis, attempt_number=attempt_number, status=AnalysisSession.Status.IN_PROGRESS,
            )
            timeout = (settings.VISION_IMAGE_TIMEOUT_SECONDS if analysis.source == AnalysisSession.Source.IMAGE
                       else settings.VISION_TIMEOUT_SECONDS)
            result = vision_client.process_frame({
                "analysis_id": str(analysis.pk), "attempt": attempt_number, "frame_id": frame_id,
                "captured_at": captured_at.isoformat() if hasattr(captured_at, "isoformat") else captured_at,
                "image_base64": image_base64,
                "calibration_version": analysis.calibration.version,
            }, timeout=timeout)
            ProcessingAttempt.objects.filter(pk=attempt.pk).update(frames_processed=F("frames_processed") + 1)
            AnalysisSession.objects.filter(pk=analysis.pk).update(last_activity_at=timezone.now())
            return result
    except vision_client.VisionServiceError as exc:
        details = {"analysis_id": str(analysis.pk), "attempt": attempt_number, "reason": exc.code,
                   "detail": str(exc)[:300]}
        if get_error(exc.code).kind == INPUT:
            AnalysisSession.objects.filter(pk=analysis.pk).update(last_activity_at=timezone.now())
            record_event("analysis.frame_rejected", operator, details, ip_address)
            raise
        # Fuera de la transacción: si se marcara dentro, la excepción desharía el estado de error.
        mark_error(analysis, attempt, exc.code)
        record_event("analysis.frame_failed", operator, details, ip_address)
        raise
