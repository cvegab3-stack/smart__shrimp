"""Rutas HTML de resultados, historial e informes."""

from django.urls import path

from .views import analysis_results_view, analysis_snapshot_view, history_view, reports_view

urlpatterns = [
    path("history/", history_view, name="history-page"),
    path("history/<uuid:pk>/", analysis_results_view, name="results-detail-page"),
    path("history/<uuid:pk>/image/", analysis_snapshot_view, name="results-snapshot"),
    path("reports/", reports_view, name="reports-page"),
]
