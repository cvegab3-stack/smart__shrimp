"""Vistas HTML para inicio, captura y calibración."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.permissions import role_required
from apps.analysis.api.views import analysis_payload
from apps.analysis.errors import CONFIGURATION_CODES, get_error
from apps.analysis.models import AnalysisSession, Calibration, ThresholdProfile
from apps.analysis.services.session_service import expire_stale_analyses

# Días que el panel del administrador muestra los errores de configuración (los únicos que puede corregir él).
CONFIG_ERRORS_DAYS = 7


@login_required
def dashboard_view(request):
    """Muestra actividad reciente visible para el rol actual."""
    expire_stale_analyses()
    sessions = AnalysisSession.objects.select_related("operator").order_by("-created_at").visible_to(request.user)
    summary = sessions.aggregate(
        total=Count("pk"),
        completed=Count("pk", filter=Q(status=AnalysisSession.Status.FINISHED)),
        in_progress=Count("pk", filter=Q(status=AnalysisSession.Status.IN_PROGRESS)),
        errors=Count("pk", filter=Q(status=AnalysisSession.Status.ERROR)),
        shrimp=Sum("shrimp_count"),
    )
    calibration = Calibration.objects.filter(is_active=True).first()
    context = {"sessions": sessions[:8], "summary": summary, "calibration": calibration}
    if request.user.role == User.Role.ADMINISTRATOR:
        since = timezone.now() - timedelta(days=CONFIG_ERRORS_DAYS)
        config_errors = list(AnalysisSession.objects.select_related("operator").filter(
            status=AnalysisSession.Status.ERROR, error_code__in=CONFIGURATION_CODES, created_at__gte=since,
        ).order_by("-created_at")[:10])
        for item in config_errors:
            item.error_text = get_error(item.error_code).record_text
        context.update(config_errors=config_errors, config_errors_days=CONFIG_ERRORS_DAYS)
    return render(request, "analysis/dashboard.html", context)


@login_required
@role_required(User.Role.OPERATOR)
def live_session_view(request):
    """Sirve el flujo de lote, imagen o captura de cámara.

    Con ?reintentar=<id> abre un lote propio con error directamente en el reintento (llega desde "Mis lotes").
    """
    calibration = Calibration.objects.filter(is_active=True).first()
    context = {
        "calibration": calibration,
        "max_image_bytes": int(settings.ANALYSIS_MAX_IMAGE_MB * 1024 * 1024),
        "min_image_side": settings.ANALYSIS_MIN_IMAGE_SIDE,
    }
    retry_id = request.GET.get("reintentar")
    if retry_id:
        expire_stale_analyses()
        try:
            analysis = AnalysisSession.objects.select_related("calibration").get(
                pk=retry_id, operator=request.user, status=AnalysisSession.Status.ERROR,
            )
        except (AnalysisSession.DoesNotExist, DjangoValidationError, ValueError):  # ajeno, inexistente o mal formado
            context["retry_missing"] = True
        else:
            context["retry_analysis"] = analysis_payload(analysis)
    return render(request, "analysis/live_session.html", context)


@login_required
def calibration_view(request):
    """Muestra la referencia vigente; solo el administrador puede actualizarla."""
    calibrations = list(Calibration.objects.annotate(analyses=Count("analysis_sessions")).order_by("-version"))
    calibration = next((c for c in calibrations if c.is_active), None)
    creators = dict(User.objects.filter(pk__in={c.created_by_id for c in calibrations}).values_list("pk", "username"))
    for item in calibrations:
        item.creator = creators.get(item.created_by_id, "—")
    categories = (("pequeno", "Pequeño"), ("mediano", "Mediano"), ("grande", "Grande"))
    return render(request, "analysis/calibration.html", {
        "calibration": calibration, "categories": categories,
        "history": [c for c in calibrations if not c.is_active],
        "threshold_profile": ThresholdProfile.objects.first(),
        "min_image_side": settings.ANALYSIS_MIN_IMAGE_SIDE,
    })


@login_required
@role_required(User.Role.ADMINISTRATOR)
def admin_users_view(request):
    """Sirve la gestión de usuarios al administrador."""
    return render(request, "accounts/user_management.html")
