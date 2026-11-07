"""Consultas del historial y detalle con filtros explícitos."""

from django.utils.dateparse import parse_date

from apps.accounts.models import User
from apps.analysis.models import AnalysisSession
from apps.analysis.services.session_service import expire_stale_analyses


def _date(params, key: str, label: str):
    raw = (params.get(key) or "").strip()
    if not raw:
        return None
    try:
        parsed = parse_date(raw)
    except ValueError:
        parsed = None
    if parsed is None:
        raise ValueError(f"La fecha «{label}» no es válida.")
    return parsed


def get_history(*, user: User, params):
    """Aplica filtros del historial y limita operador a sus propios análisis.

    Antes cierra los análisis interrumpidos, para que el estado mostrado sea el real.
    """
    expire_stale_analyses()
    sessions = AnalysisSession.objects.select_related("operator", "calibration").prefetch_related("shrimp_records").visible_to(user)
    if params.get("batch_code"):
        sessions = sessions.filter(batch_code__icontains=params["batch_code"].strip())
    status = params.get("status")
    if status:
        if status not in AnalysisSession.Status.values:
            raise ValueError("El estado elegido no es válido.")
        sessions = sessions.filter(status=status)
    date_from = _date(params, "date_from", "Desde")
    date_to = _date(params, "date_to", "Hasta")
    if date_from and date_to and date_from > date_to:
        raise ValueError("La fecha «Desde» no puede ser posterior a «Hasta».")
    if date_from:
        sessions = sessions.filter(created_at__date__gte=date_from)
    if date_to:
        sessions = sessions.filter(created_at__date__lte=date_to)
    if params.get("visual_condition"):
        sessions = sessions.filter(shrimp_records__visual_condition=params["visual_condition"])
    if params.get("size_category"):
        sessions = sessions.filter(shrimp_records__size_category=params["size_category"])
    return sessions.distinct().order_by("-created_at")
