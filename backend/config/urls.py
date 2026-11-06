"""Rutas raíz de páginas y API."""

from django.contrib import admin
from django.db import connections
from django.http import JsonResponse
from django.urls import include, path


def health_check(request):
    """Comprueba que Django y la conexión de base de datos responden."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})

urlpatterns = [
    path("healthz/", health_check, name="health-check"),
    path("admin/", admin.site.urls),
    path("", include("apps.analysis.urls")),
    path("", include("apps.results.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("api/accounts/", include("apps.accounts.api.urls")),
    path("api/", include("apps.analysis.api.urls")),
    path("api/", include("apps.results.api.urls")),
]
