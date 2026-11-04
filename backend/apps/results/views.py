"""Vistas HTML de historial, detalle y reportes."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.accounts.models import User
from apps.accounts.permissions import role_required
from apps.analysis.models import AnalysisSession
from apps.results.models import ProductionReport, ShrimpRecord
from apps.results.services.history_service import get_history


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
    return render(request, "results/dashboard.html", {"analysis": analysis, "results": results})


@login_required
@role_required(User.Role.SUPERVISOR)
def reports_view(request):
    """Lista informes al supervisor y provee formulario para generar nuevos."""
    reports = ProductionReport.objects.filter(created_by_id=request.user.pk)
    return render(request, "results/reports.html", {"reports": reports})
