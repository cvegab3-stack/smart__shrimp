"""Vistas HTML de historial, detalle y reportes."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render

from apps.accounts.models import User
from apps.accounts.permissions import role_required
from apps.analysis.errors import get_error
from apps.analysis.models import AnalysisSession, ProcessingAttempt
from apps.results.models import ProductionReport, ShrimpRecord
from apps.results.services.history_service import get_history
from apps.results.services.presentation_service import build_summary
from apps.analysis.services.session_service import expire_stale_analyses

HISTORY_PAGE_SIZE = 25


@login_required
@role_required(User.Role.OPERATOR, User.Role.QUALITY, User.Role.SUPERVISOR)
def history_view(request):
    """Lista análisis filtrados con los permisos del rol actual."""
    try:
        sessions = get_history(user=request.user, params=request.GET)
    except ValueError as exc:
        return render(request, "results/history.html", {"sessions": [], "filter_error": str(exc),
                                                          "status_choices": AnalysisSession.Status.choices})
    page = Paginator(sessions, HISTORY_PAGE_SIZE).get_page(request.GET.get("page"))
    for item in page.object_list:
        item.error_text = get_error(item.error_code).record_text if item.status == AnalysisSession.Status.ERROR else ""
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "results/history.html", {
        "sessions": page.object_list, "page": page, "query": query.urlencode(),
        "status_choices": AnalysisSession.Status.choices,
    })


@login_required
def analysis_results_view(request, pk):
    """Muestra resultados guardados al propietario y a roles de consulta."""
    expire_stale_analyses()
    analysis = get_object_or_404(AnalysisSession.objects.select_related("operator").visible_to(request.user), pk=pk)
    results = ShrimpRecord.objects.of_current_attempt(analysis)
    error = get_error(analysis.error_code) if analysis.status == AnalysisSession.Status.ERROR else None
    attempts = list(analysis.attempts.order_by("-attempt_number"))
    for attempt in attempts:
        attempt.error_text = get_error(attempt.error_code).record_text if attempt.error_code else ""
    return render(request, "results/dashboard.html", {
        "analysis": analysis, "results": results, "summary": build_summary(analysis), "error": error,
        "attempts": attempts, "can_retry": error is not None and analysis.operator_id == request.user.pk,
    })


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
    return render(request, "results/reports.html", {"reports": reports, "created": request.GET.get("creado")})
