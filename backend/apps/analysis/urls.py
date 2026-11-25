"""Rutas HTML de análisis."""

from django.urls import path

from apps.analysis.models import AnalysisSession

from .views import admin_users_view, calibration_view, dashboard_view, live_session_view, new_analysis_view

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("analysis/new/", new_analysis_view, name="new-analysis"),
    path("analysis/new/foto/", live_session_view, {"source": AnalysisSession.Source.IMAGE}, name="new-analysis-image"),
    path("analysis/new/camara/", live_session_view, {"source": AnalysisSession.Source.VIDEO},
         name="new-analysis-camera"),
    path("calibration/", calibration_view, name="calibration-page"),
    path("users/", admin_users_view, name="user-management"),
]
