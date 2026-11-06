"""Vistas HTML de historial, detalle y reportes."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render

from apps.accounts.models import User
from apps.accounts.permissions import role_required
from apps.analysis.models import AnalysisSession, ProcessingAttempt
from apps.results.models import ProductionReport, ShrimpRecord
from apps.results.services.history_service import get_history
from apps.results.services.presentation_service import build_summary


@login_required
@role_required(User.Role.OPERATOR, User.Role.QUALITY, User.Role.SUPERVISOR)
def history_view(request):
    """Lista análisis filtrados con los permisos del rol actual."""
    try:
        sessions = get_history(user=request.user, params=request.GET)
    except ValueError as exc:
        sessions = AnalysisSession.objects.none()
        return render(request, "results/history.html", {"sessions": sessions, "filter_error": str(exc)})
    return render(request, "results/history.html", {"sessions": sessions[:100]})


@login_required
def analysis_results_view(request, pk):
    """Muestra resultados guardados al propietario y a roles de consulta."""
    analysis = get_object_or_404(AnalysisSession.objects.select_related("operator").visible_to(request.user), pk=pk)
    results = ShrimpRecord.objects.of_current_attempt(analysis)
    return render(request, "results/dashboard.html",
                  {"analysis": analysis, "results": results, "summary": build_summary(analysis)})


@login_required
def analysis_snapshot_view(request, pk):
    """Entrega la imagen analizada solo a quien puede ver ese análisis (mismas reglas que el detalle)."""
    analysis = get_object_or_404(AnalysisSession.objects.visible_to(request.user), pk=pk)
    attempt = ProcessingAttempt.objects.filter(analysis=analysis, attempt_number=analysis.current_attempt).first()
    if attempt is None or not attempt.snapshot_path:
        raise Http404("Este análisis no tiene imagen guardada.")
    media_root = Path(settings.MEDIA_ROOT).resolve()
    path = (media_root / attempt.snapshot_path).resolve()
    if media_root not in path.parents or not path.is_file():
        raise Http404("Este análisis no tiene imagen guardada.")
    response = FileResponse(open(path, "rb"), content_type="image/jpeg")
    response["Cache-Control"] = "private, no-store"  # puede cambiar si se reintenta el análisis
    return response


@login_required
@role_required(User.Role.SUPERVISOR)
def reports_view(request):
    """Lista informes al supervisor y provee formulario para generar nuevos."""
    reports = ProductionReport.objects.filter(created_by_id=request.user.pk)
    return render(request, "results/reports.html", {"reports": reports})
