"""Flujo integrado de análisis con servicio de visión."""

from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import User
from apps.analysis.models import AnalysisSession
from apps.analysis.services.calibration_service import create_calibration
from apps.analysis.services.session_service import start_analysis
from apps.analysis.services.threshold_service import create_threshold_profile
from apps.results.services.history_service import get_history
from apps.results.services.report_service import complete_analysis


class SessionFlowIntegrationTests(TestCase):
    """Comprueba que un resumen simulado completo llega al historial."""

    def test_inference_session_lifecycle(self):
        operator = User.objects.create_user("operator", password="password", role=User.Role.OPERATOR)
        admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        ranges = {"pequeno": {"min_cm": 0, "max_cm": 8}, "mediano": {"min_cm": 8.1, "max_cm": 13}, "grande": {"min_cm": 13.1, "max_cm": None}}
        create_calibration(reference_length_cm=10, reference_pixels=500, size_ranges=ranges, actor=admin)
        create_threshold_profile(detection_confidence=0.5, visual_condition_confidence=0.5, actor=admin)
        with patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True}):
            analysis = start_analysis(batch_code="INTEGRATION-1", source="imagen", operator=operator)
        summary = {"analysis_id": str(analysis.pk), "attempt": 1, "shrimp": [], "shrimp_count": 0,
                   "rejected_count": 0, "model_mode": "inference", "model_status": "configured"}
        with patch("apps.results.services.report_service.vision_client.get_session_summary", return_value=summary):
            finished = complete_analysis(analysis.pk, operator=operator)
        self.assertEqual(finished.status, AnalysisSession.Status.FINISHED)
        self.assertEqual(finished.model_mode, "inference")
        self.assertEqual(get_history(user=operator, params={}).get(pk=analysis.pk).shrimp_count, 0)
