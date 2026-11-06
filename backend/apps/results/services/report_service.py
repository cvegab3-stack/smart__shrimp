"""Finalización atómica de sesiones y generación de reportes consolidados."""

from collections import Counter
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import record_event
from apps.analysis.errors import INPUT, get_error
from apps.analysis.models import AnalysisSession, ProcessingAttempt
from apps.analysis.services.session_service import expire_stale_analyses
from apps.results.models import ProductionReport, ShrimpRecord
from integrations import vision_client
from integrations.vision_client import VisionServiceError
from shrimp_contracts.catalog import classes_for

VISUAL_DISCLAIMER = "La condición visual es solo evaluación visual y no reemplaza análisis microbiológicos, químicos ni sanitarios."


class NothingToFinish(ValueError):
    """Se pidió finalizar un intento sin ningún fotograma procesado: no cambia el estado del análisis."""


def _validate_summary(analysis: AnalysisSession, attempt: int, summary: dict) -> list[dict]:
    """Valida claves, intentos, categorías y medidas antes de una escritura."""
    if summary.get("analysis_id") != str(analysis.pk) or summary.get("attempt") != attempt:
        raise ValueError("El resumen no corresponde al análisis e intento solicitados.")
    rows = summary.get("shrimp")
    if not isinstance(rows, list) or summary.get("shrimp_count") != len(rows):
        raise ValueError("El resumen debe incluir una lista completa de ejemplares y su total.")
    if not isinstance(summary.get("rejected_count", 0), int) or summary.get("rejected_count", 0) < 0:
        raise ValueError("El total de rechazos debe ser un entero no negativo.")
    condition_classes = set(classes_for("condicion_visual"))
    integrity_classes = set(classes_for("integridad"))
    presentation_classes = set(classes_for("presentacion"))
    size_classes = {"pequeno", "mediano", "grande"}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Cada ejemplar debe ser un objeto del resumen.")
        track_id = row.get("track_id")
        if not isinstance(track_id, str) or not track_id or track_id in seen:
            raise ValueError("Cada resultado debe tener un track_id único.")
        seen.add(track_id)
        if row.get("visual_condition") not in condition_classes:
            raise ValueError("Condición visual fuera del catálogo.")
        if row.get("integrity") is not None and row["integrity"] not in integrity_classes:
            raise ValueError("Integridad fuera del catálogo.")
        if row.get("presentation") is not None and row["presentation"] not in presentation_classes:
            raise ValueError("Presentación fuera del catálogo.")
        if row.get("size_category") is not None and row["size_category"] not in size_classes:
            raise ValueError("Categoría de tamaño no válida.")
        for field in ("confidence", "visual_condition_confidence"):
            value = row.get(field)
            if value is not None and not 0 <= float(value) <= 1:
                raise ValueError(f"{field} debe estar entre cero y uno.")
        for field in ("length_cm", "estimated_weight_g"):
            value = row.get(field)
            if value is not None and float(value) < 0:
                raise ValueError(f"{field} no puede ser negativo.")
    return rows


def complete_analysis(analysis_id, *, operator: User, ip_address: str | None = None) -> AnalysisSession:
    """Solicita resumen a M3 y guarda el intento completo en una transacción."""
    analysis = AnalysisSession.objects.select_related("calibration").get(pk=analysis_id, operator=operator)
    if analysis.status == AnalysisSession.Status.FINISHED:
        return analysis
    if analysis.status != AnalysisSession.Status.IN_PROGRESS:
        raise ValueError("Solo se pueden finalizar análisis en curso.")
    attempt_number = analysis.current_attempt
    attempt_row = ProcessingAttempt.objects.filter(analysis=analysis, attempt_number=attempt_number).first()
    if attempt_row is None or not attempt_row.frames_processed:
        message = ("Analiza la imagen antes de finalizar." if analysis.source == AnalysisSession.Source.IMAGE
                   else "Aún no se procesó ningún fotograma: inicia la cámara y espera a que se analice antes de finalizar.")
        raise NothingToFinish(message)
    try:
        summary = vision_client.get_session_summary(str(analysis.pk), attempt_number)
        rows = _validate_summary(analysis, attempt_number, summary)
    except (VisionServiceError, ValueError, KeyError, TypeError, AttributeError) as exc:
        code = getattr(exc, "code", "vision_invalid_response")
        if get_error(code).kind == INPUT:  # un resumen nunca es culpa de la imagen: es una respuesta no válida
            code = "vision_invalid_response"
        with transaction.atomic():
            locked = AnalysisSession.objects.select_for_update().get(pk=analysis.pk)
            locked.status = AnalysisSession.Status.ERROR
            locked.error_code = code
            locked.error_message = get_error(code).record_text
            locked.finished_at = timezone.now()
            locked.save(update_fields=("status", "error_code", "error_message", "finished_at"))
            ProcessingAttempt.objects.filter(analysis=locked, attempt_number=attempt_number).update(
                status=AnalysisSession.Status.ERROR, error_code=locked.error_code, finished_at=locked.finished_at,
            )
            record_event("analysis.finalization_failed", operator, {
                "analysis_id": str(analysis.pk), "reason": code, "detail": str(exc)[:300]}, ip_address)
        raise
    with transaction.atomic():
        locked = AnalysisSession.objects.select_for_update().get(pk=analysis.pk)
        if locked.status == AnalysisSession.Status.FINISHED:
            return locked
        if locked.status != AnalysisSession.Status.IN_PROGRESS or locked.current_attempt != attempt_number:
            raise ValueError("El análisis cambió mientras se guardaba el resumen.")
        attempt = ProcessingAttempt.objects.select_for_update().get(analysis=locked, attempt_number=attempt_number)
        records = [ShrimpRecord(
            analysis=locked, attempt=attempt_number, track_id=row["track_id"],
            confidence=row.get("confidence"), integrity=row.get("integrity"),
            presentation=row.get("presentation"), visual_condition=row["visual_condition"],
            visual_condition_confidence=row.get("visual_condition_confidence"),
            length_cm=row.get("length_cm"), size_category=row.get("size_category"),
            estimated_weight_g=row.get("estimated_weight_g"),
        ) for row in rows]
        ShrimpRecord.objects.bulk_create(records)
        locked.status = AnalysisSession.Status.FINISHED
        locked.model_mode = str(summary.get("model_mode", "unknown"))
        locked.model_status = str(summary.get("model_status", ""))
        locked.shrimp_count = len(rows)
        locked.rejected_count = int(summary.get("rejected_count", 0))
        locked.finished_at = timezone.now()
        locked.save(update_fields=("status", "model_mode", "model_status", "shrimp_count", "rejected_count", "finished_at"))
        attempt.status = AnalysisSession.Status.FINISHED
        attempt.finished_at = locked.finished_at
        attempt.save(update_fields=("status", "finished_at"))
        record_event("analysis.completed", operator, {"analysis_id": str(locked.pk), "attempt": attempt_number}, ip_address)
        return locked


def create_production_report(*, date_from: date, date_to: date, supervisor: User, ip_address: str | None = None) -> ProductionReport:
    """Agrega análisis finalizados del intervalo y conserva el informe generado."""
    if date_from > date_to:
        raise ValueError("La fecha «Desde» debe ser anterior o igual a «Hasta».")
    expire_stale_analyses()
    records = ShrimpRecord.objects.filter(
        analysis__status=AnalysisSession.Status.FINISHED,
        analysis__created_at__date__gte=date_from,
        analysis__created_at__date__lte=date_to,
    )
    size_distribution = dict(Counter(value for value in records.values_list("size_category", flat=True) if value))
    condition_distribution = dict(Counter(records.values_list("visual_condition", flat=True)))
    weights = [value for value in records.values_list("estimated_weight_g", flat=True) if value is not None]
    session_ids = records.values_list("analysis_id", flat=True).distinct()
    summary = {
        "analysis_count": AnalysisSession.objects.filter(pk__in=session_ids).count(),
        "shrimp_count": records.count(),
        "size_distribution": size_distribution,
        "visual_condition_distribution": condition_distribution,
        "average_estimated_weight_g": sum(weights) / len(weights) if weights else None,
        "weight_label": "valor estimado",
        "visual_disclaimer": VISUAL_DISCLAIMER,
        "flow": _flow_health(date_from, date_to),
    }
    report = ProductionReport.objects.create(
        created_by_id=supervisor.pk, date_from=date_from, date_to=date_to, summary=summary,
    )
    record_event("report.created", supervisor, {"report_id": str(report.pk)}, ip_address)
    return report


def flow_rows(summary: dict) -> list[tuple[str, int]]:
    """Filas «salud del flujo» para los exportadores (vacío en informes generados antes de existir la métrica)."""
    flow = summary.get("flow")
    if not flow:
        return []
    rows = [("Análisis iniciados", flow["started"]), ("Análisis con error", flow["errors"]),
            ("De ellos, interrumpidos", flow["interrupted"]), ("Análisis reintentados", flow["retried"])]
    rows.extend((f"Causa de error: {cause}", count) for cause, count in flow["error_causes"].items())
    return rows


def _flow_health(date_from: date, date_to: date) -> dict:
    """Salud del flujo en el período: cuántos análisis se iniciaron, cuántos fallaron y por qué, y cuántos se
    reintentaron. Así el supervisor ve la calidad del proceso, no solo la producción."""
    sessions = AnalysisSession.objects.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
    errors = sessions.filter(status=AnalysisSession.Status.ERROR)
    causes = Counter(get_error(code).record_text for code in errors.values_list("error_code", flat=True))
    return {
        "started": sessions.count(),
        "finished": sessions.filter(status=AnalysisSession.Status.FINISHED).count(),
        "errors": errors.count(),
        "interrupted": errors.filter(error_code="interrupted").count(),
        "in_progress": sessions.filter(status=AnalysisSession.Status.IN_PROGRESS).count(),
        "retried": sessions.filter(current_attempt__gt=1).count(),
        "error_causes": dict(causes.most_common()),
    }
