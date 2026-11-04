"""Pruebas de atomicidad, historial, reportes y exportaciones."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.analysis.models import AnalysisSession
from apps.analysis.services.calibration_service import create_calibration
from apps.analysis.services.session_service import start_analysis
from apps.analysis.services.threshold_service import create_threshold_profile
from apps.results.models import ShrimpRecord
from apps.results.services.csv_exporter import export_report_csv
from apps.results.services.pdf_exporter import export_report_pdf
from apps.results.services.report_service import complete_analysis, create_production_report

ROW = {
    "track_id": "track-1", "confidence": 0.98, "integrity": "completo",
    "presentation": "con_cascara", "visual_condition": "no_concluyente",
    "visual_condition_confidence": 0.4, "length_cm": 12.0, "size_category": "mediano",
    "estimated_weight_g": None,
}


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ResultServiceTests(TestCase):
    """Prueba persistencia total, revisión histórica y reporte supervisor."""

    def setUp(self):
        self.operator = User.objects.create_user("operator", password="password", role=User.Role.OPERATOR)
        self.supervisor = User.objects.create_user("supervisor", password="password", role=User.Role.SUPERVISOR)
        self.quality = User.objects.create_user("quality", password="password", role=User.Role.QUALITY)
        admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        ranges = {
            "pequeno": {"min_cm": 0, "max_cm": 8},
            "mediano": {"min_cm": 8.1, "max_cm": 13},
            "grande": {"min_cm": 13.1, "max_cm": None},
        }
        create_calibration(reference_length_cm=10, reference_pixels=500, size_ranges=ranges, actor=admin)
        create_threshold_profile(detection_confidence=0.5, visual_condition_confidence=0.5, actor=admin)
        with patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True}):
            self.analysis = start_analysis(batch_code="LOT-2026-01", source="imagen", operator=self.operator)

    @patch("apps.results.services.report_service.vision_client.get_session_summary")
    def test_complete_analysis_saves_all_results_and_is_idempotent(self, get_summary):
        get_summary.return_value = {
            "analysis_id": str(self.analysis.pk), "attempt": 1, "shrimp": [ROW],
            "shrimp_count": 1, "rejected_count": 0, "model_mode": "inference",
            "model_status": "configured",
        }
        first = complete_analysis(self.analysis.pk, operator=self.operator)
        second = complete_analysis(self.analysis.pk, operator=self.operator)
        self.assertEqual(first.status, AnalysisSession.Status.FINISHED)
        self.assertEqual(second.shrimp_count, 1)
        self.assertEqual(ShrimpRecord.objects.filter(analysis=self.analysis).count(), 1)
        self.assertEqual(get_summary.call_count, 1)

    @patch("apps.results.services.report_service.vision_client.get_session_summary")
    def test_invalid_summary_creates_no_partial_records_and_marks_error(self, get_summary):
        get_summary.return_value = {
            "analysis_id": str(self.analysis.pk), "attempt": 1,
            "shrimp": [ROW, {**ROW, "track_id": "track-2", "visual_condition": "sin_cabeza"}],
            "shrimp_count": 2, "rejected_count": 0,
        }
        with self.assertRaises(ValueError):
            complete_analysis(self.analysis.pk, operator=self.operator)
        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.status, AnalysisSession.Status.ERROR)
        self.assertEqual(ShrimpRecord.objects.filter(analysis=self.analysis).count(), 0)

    @patch("apps.results.services.report_service.vision_client.get_session_summary")
    def test_history_filters_and_role_scope(self, get_summary):
        get_summary.return_value = {
            "analysis_id": str(self.analysis.pk), "attempt": 1, "shrimp": [ROW],
            "shrimp_count": 1, "rejected_count": 0, "model_mode": "inference",
            "model_status": "configured",
        }
        complete_analysis(self.analysis.pk, operator=self.operator)
        client = APIClient()
        client.force_authenticate(self.quality)
        response = client.get("/api/history/", {"visual_condition": "no_concluyente", "batch_code": "LOT"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        client.force_authenticate(self.operator)
        detail = client.get(f"/api/history/{self.analysis.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIsNone(detail.data["results"][0]["weight_label"])
        self.assertIn("no reemplaza", detail.data["results"][0]["visual_disclaimer"])

    @patch("apps.results.services.report_service.vision_client.get_session_summary")
    def test_only_supervisor_can_create_and_export_reports(self, get_summary):
        get_summary.return_value = {
            "analysis_id": str(self.analysis.pk), "attempt": 1, "shrimp": [ROW],
            "shrimp_count": 1, "rejected_count": 0, "model_mode": "inference",
            "model_status": "configured",
        }
        complete_analysis(self.analysis.pk, operator=self.operator)
        today = timezone.localdate()
        report = create_production_report(date_from=today - timedelta(days=1), date_to=today + timedelta(days=1), supervisor=self.supervisor)
        self.assertEqual(report.summary["visual_condition_distribution"], {"no_concluyente": 1})
        self.assertIn("valor estimado", export_report_csv(report).decode("utf-8-sig"))
        self.assertTrue(export_report_pdf(report).startswith(b"%PDF"))
        client = APIClient()
        client.force_authenticate(self.quality)
        denied = client.post("/api/reports/", {"date_from": today.isoformat(), "date_to": today.isoformat()}, format="json")
        self.assertEqual(denied.status_code, 403)
        client.force_authenticate(self.supervisor)
        allowed = client.get(f"/api/reports/{report.pk}/export.csv/")
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("attachment", allowed["Content-Disposition"])
