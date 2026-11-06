"""Consultas del historial y detalle con filtros explícitos."""

from django.utils.dateparse import parse_date

from apps.accounts.models import User
from apps.analysis.models import AnalysisSession


def get_history(*, user: User, params):
    """Aplica filtros del historial y limita operador a sus propios análisis."""
    sessions = AnalysisSession.objects.select_related("operator", "calibration").prefetch_related("shrimp_records").visible_to(user)
    if params.get("batch_code"):
        sessions = sessions.filter(batch_code__icontains=params["batch_code"].strip())
    if params.get("status"):
        sessions = sessions.filter(status=params["status"])
    if params.get("date_from"):
        parsed = parse_date(params["date_from"])
        if parsed is None:
            raise ValueError("date_from debe usar formato AAAA-MM-DD.")
        sessions = sessions.filter(created_at__date__gte=parsed)
    if params.get("date_to"):
        parsed = parse_date(params["date_to"])
        if parsed is None:
            raise ValueError("date_to debe usar formato AAAA-MM-DD.")
        sessions = sessions.filter(created_at__date__lte=parsed)
    if params.get("visual_condition"):
        sessions = sessions.filter(shrimp_records__visual_condition=params["visual_condition"])
    if params.get("size_category"):
        sessions = sessions.filter(shrimp_records__size_category=params["size_category"])
    return sessions.distinct().order_by("-created_at")
