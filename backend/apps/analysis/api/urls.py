"""Rutas REST de análisis y configuración."""

from django.urls import path

from .views import AnalysisCompleteView, AnalysisDetailView, AnalysisListCreateView, CalibrationView, FrameRelayView, ThresholdView

urlpatterns = [
    path("analyses/", AnalysisListCreateView.as_view(), name="analysis-list-create"),
    path("analyses/<uuid:pk>/", AnalysisDetailView.as_view(), name="analysis-detail"),
    path("analyses/<uuid:pk>/frames/", FrameRelayView.as_view(), name="analysis-frame"),
    path("analyses/<uuid:pk>/complete/", AnalysisCompleteView.as_view(), name="analysis-complete"),
    path("calibration/", CalibrationView.as_view(), name="calibration"),
    path("thresholds/", ThresholdView.as_view(), name="thresholds"),
]
