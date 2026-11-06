"""Rutas HTML de análisis."""

from django.urls import path

from .views import admin_users_view, calibration_view, dashboard_view, live_session_view

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("analysis/new/", live_session_view, name="new-analysis"),
    path("calibration/", calibration_view, name="calibration-page"),
    path("users/", admin_users_view, name="user-management"),
]
