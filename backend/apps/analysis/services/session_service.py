"""Casos de uso de ciclo de vida de análisis y control de reintentos.

Estados: en curso → finalizado, o en curso → con error → (reintentar) → en curso. Un error guarda su código del
catálogo (apps/analysis/errors.py) y su texto legible; el detalle técnico va solo a la auditoría.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.services import record_event
from apps.analysis.errors import get_error
from apps.analysis.models import AnalysisSession, ProcessingAttempt
from apps.analysis.services.calibration_service import get_active_calibration
from apps.analysis.services.threshold_service import get_current_threshold_profile
from integrations import vision_client


def mark_error(analysis: AnalysisSession, attempt: ProcessingAttempt, code: str, message: str = "") -> None:
    """Persiste un fallo de procesamiento sin crear resultados parciales.

    `message` es el detalle técnico: se ignora aquí (lo guarda la auditoría) y se guarda el texto del catálogo.
    """
    now = timezone.now()
    AnalysisSession.objects.filter(pk=analysis.pk).update(
        status=AnalysisSession.Status.ERROR, error_code=code, error_message=get_error(code).record_text,
        finished_at=now,
    )
    ProcessingAttempt.objects.filter(pk=attempt.pk).update(
        status=AnalysisSession.Status.ERROR, error_code=code, finished_at=now,
    )


def _vision_session_payload(analysis: AnalysisSession, attempt_number: int) -> dict:
    """Configuración congelada del análisis que M3 necesita para abrir el intento."""
    calibration, thresholds = analysis.calibration, analysis.threshold_profile
    return {
        "analysis_id": str(analysis.pk), "attempt": attempt_number,
        "calibration_version": calibration.version, "source": analysis.source,
        "reference_length_cm": calibration.reference_length_cm,
        "reference_pixels": calibration.reference_pixels,
        "size_ranges": calibration.size_ranges,
        "detection_confidence": thresholds.detection_confidence,
        "visual_condition_confidence": thresholds.visual_condition_confidence,
    }


def _failure_details(analysis: AnalysisSession, exc: vision_client.VisionServiceError, **extra) -> dict:
    return {"analysis_id": str(analysis.pk), "reason": exc.code, "detail": str(exc)[:300], **extra}


@transaction.atomic
def start_analysis(*, batch_code: str, source: str, operator, ip_address: str | None = None) -> AnalysisSession:
    """Crea el análisis en curso y solicita apertura en M3."""
    if source not in AnalysisSession.Source.values:
        raise ValueError("Origen de análisis no válido.")
    if not batch_code.strip():
        raise ValueError("El código de lote es obligatorio.")
    calibration = get_active_calibration()
    thresholds = get_current_threshold_profile()
    analysis = AnalysisSession.objects.create(
        batch_code=batch_code.strip(), operator=operator, source=source,
        calibration=calibration, threshold_profile=thresholds, last_activity_at=timezone.now(),
    )
    attempt = ProcessingAttempt.objects.create(analysis=analysis, attempt_number=1)
    try:
        vision_client.start_session(_vision_session_payload(analysis, attempt.attempt_number))
    except vision_client.VisionServiceError as exc:
        mark_error(analysis, attempt, exc.code)
        record_event("analysis.failed", operator, _failure_details(analysis, exc), ip_address)
        analysis.refresh_from_db()
        return analysis
    record_event("analysis.started", operator, {"analysis_id": str(analysis.pk), "attempt": 1}, ip_address)
    return analysis


@transaction.atomic
def retry_analysis(analysis_id, *, operator, ip_address: str | None = None) -> AnalysisSession:
    """Abre un intento nuevo identificado sin duplicar resultados anteriores."""
    analysis = AnalysisSession.objects.select_for_update().get(pk=analysis_id, operator=operator)
    if analysis.status == AnalysisSession.Status.FINISHED:
        raise ValueError("Este análisis ya está finalizado: no hace falta reintentarlo.")
    if analysis.status != AnalysisSession.Status.ERROR:
        raise ValueError("Este análisis sigue en curso: termina la captura en lugar de reintentarlo.")
    number = analysis.current_attempt + 1
    attempt = ProcessingAttempt.objects.create(analysis=analysis, attempt_number=number)
    analysis.current_attempt = number
    analysis.status = AnalysisSession.Status.IN_PROGRESS
    analysis.error_code = ""
    analysis.error_message = ""
    analysis.finished_at = None
    analysis.last_activity_at = timezone.now()
    analysis.save(update_fields=("current_attempt", "status", "error_code", "error_message", "finished_at",
                                 "last_activity_at"))
    try:
        vision_client.start_session(_vision_session_payload(analysis, number))
    except vision_client.VisionServiceError as exc:
        mark_error(analysis, attempt, exc.code)
        analysis.refresh_from_db()
        record_event("analysis.retry_failed", operator, _failure_details(analysis, exc, attempt=number), ip_address)
        return analysis
    record_event("analysis.retried", operator, {"analysis_id": str(analysis.pk), "attempt": number}, ip_address)
    return analysis


def expire_stale_analyses(now=None) -> int:
    """Pasa a "con error" (interrumpido) los análisis en curso sin actividad reciente. Devuelve cuántos.

    Se llama al consultar el panel, el historial y los reportes: así ningún lote queda "en curso" para siempre y el
    operador puede reintentarlo, sin depender de una tarea programada.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=settings.ANALYSIS_IDLE_MINUTES)
    stale = AnalysisSession.objects.filter(status=AnalysisSession.Status.IN_PROGRESS).filter(
        last_activity_at__lt=cutoff,
    ) | AnalysisSession.objects.filter(
        status=AnalysisSession.Status.IN_PROGRESS, last_activity_at__isnull=True, created_at__lt=cutoff,
    )
    stale_ids = list(stale.values_list("pk", flat=True))
    if not stale_ids:
        return 0
    with transaction.atomic():
        for analysis in AnalysisSession.objects.select_for_update().filter(
            pk__in=stale_ids, status=AnalysisSession.Status.IN_PROGRESS,
        ):
            attempt = ProcessingAttempt.objects.filter(analysis=analysis, attempt_number=analysis.current_attempt).first()
            if attempt is not None:
                mark_error(analysis, attempt, "interrupted")
            record_event("analysis.interrupted", None, {"analysis_id": str(analysis.pk),
                                                        "attempt": analysis.current_attempt})
    return len(stale_ids)
