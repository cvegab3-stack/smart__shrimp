"""Vistas HTML para inicio, captura y calibración."""

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render

from apps.accounts.models import User
from apps.accounts.permissions import role_required
from apps.analysis.models import AnalysisSession, Calibration, ThresholdProfile


@login_required
def dashboard_view(request):
    """Muestra actividad reciente visible para el rol actual."""
    sessions = AnalysisSession.objects.select_related("operator").order_by("-created_at").visible_to(request.user)
    summary = sessions.aggregate(
        total=Count("pk"),
        completed=Count("pk", filter=Q(status=AnalysisSession.Status.FINISHED)),
        in_progress=Count("pk", filter=Q(status=AnalysisSession.Status.IN_PROGRESS)),
        errors=Count("pk", filter=Q(status=AnalysisSession.Status.ERROR)),
        shrimp=Sum("shrimp_count"),
    )
    calibration = Calibration.objects.filter(is_active=True).first()
    return render(request, "analysis/dashboard.html", {
        "sessions": sessions[:8], "summary": summary, "calibration": calibration,
    })


@login_required
@role_required(User.Role.OPERATOR)
def live_session_view(request):
    """Sirve el flujo de lote, imagen o captura de cámara."""
    calibration = Calibration.objects.filter(is_active=True).first()
    return render(request, "analysis/live_session.html", {"calibration": calibration})


@login_required
def calibration_view(request):
    """Muestra la referencia vigente; solo el administrador puede actualizarla."""
    calibration = Calibration.objects.filter(is_active=True).first()
    categories = (("pequeno", "Pequeño"), ("mediano", "Mediano"), ("grande", "Grande"))
    return render(request, "analysis/calibration.html", {
        "calibration": calibration, "categories": categories,
        "threshold_profile": ThresholdProfile.objects.first(),
    })


@login_required
@role_required(User.Role.ADMINISTRATOR)
def admin_users_view(request):
    """Sirve la gestión de usuarios al administrador."""
    return render(request, "accounts/user_management.html")
