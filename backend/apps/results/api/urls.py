"""Rutas REST de resultados e informes."""

from django.urls import path

from .views import AnalysisResultsView, HistoryListView, ReportExportView, ReportListCreateView, ResultsExportView

urlpatterns = [
    path("history/", HistoryListView.as_view(), name="analysis-history"),
    path("history/<uuid:pk>/", AnalysisResultsView.as_view(), name="analysis-results"),
    path("history/<uuid:pk>/export.<str:file_type>/", ResultsExportView.as_view(), name="results-export"),
    path("reports/", ReportListCreateView.as_view(), name="production-reports"),
    path("reports/<uuid:pk>/export.<str:file_type>/", ReportExportView.as_view(), name="report-export"),
]
