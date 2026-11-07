"""Lo que control de calidad y supervisión ven del flujo: historial, detalle honesto y salud en los reportes."""

from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.analysis.models import AnalysisSession
from apps.analysis.services.calibration_service import create_calibration
from apps.analysis.services.session_service import retry_analysis, start_analysis
from apps.analysis.services.threshold_service import create_threshold_profile
from apps.results.services.csv_exporter import export_report_csv
from apps.results.services.pdf_exporter import export_report_pdf
from apps.results.services.report_service import complete_analysis, create_production_report
from integrations.vision_client import VisionServiceError

RANGES = {"pequeno": {"min_cm": 0, "max_cm": 8}, "mediano": {"min_cm": 8, "max_cm": 13}, "grande": {"min_cm": 13, "max_cm": None}}
START = "apps.analysis.services.session_service.vision_client.start_session"


class ReviewFlowTests(TestCase):

    def setUp(self):
        self.operator = User.objects.create_user("operador1", password="password", role=User.Role.OPERATOR,
                                                 first_name="Ana", last_name="Pérez")
        self.other = User.objects.create_user("operador2", password="password", role=User.Role.OPERATOR)
        self.quality = User.objects.create_user("calidad", password="password", role=User.Role.QUALITY)
        self.supervisor = User.objects.create_user("supervisor", password="password", role=User.Role.SUPERVISOR)
        admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        create_calibration(reference_length_cm=10, reference_pixels=500, size_ranges=RANGES, actor=admin)
        create_threshold_profile(detection_confidence=0.5, visual_condition_confidence=0.5, actor=admin)
        with patch(START, side_effect=VisionServiceError("ConnectionError", code="vision_unavailable")):
            self.failed = start_analysis(batch_code="LOTE-FALLA", source="imagen", operator=self.operator)
        with patch(START, return_value={"ok": True}):
            self.finished = start_analysis(batch_code="LOTE-OK", source="imagen", operator=self.operator)
        self.finished.attempts.update(frames_processed=1)
        summary = {"analysis_id": str(self.finished.pk), "attempt": 1, "shrimp": [], "shrimp_count": 0,
                   "rejected_count": 0, "model_mode": "inference", "model_status": "configured"}
        with patch("apps.results.services.report_service.vision_client.get_session_summary", return_value=summary):
            complete_analysis(self.finished.pk, operator=self.operator)

    def page(self, user, url):
        client = Client()
        client.force_login(user)
        return client.get(url).content.decode()

    def test_history_filters_by_status_and_shows_operator_and_cause_to_reviewers(self):
        html = self.page(self.quality, "/history/?status=con_error")
        self.assertIn("LOTE-FALLA", html)
        self.assertNotIn("LOTE-OK", html)
        self.assertIn("Ana Pérez", html)  # columna operador para revisores
        self.assertIn("El servicio de análisis no respondió.", html)
        self.assertNotIn("?reintentar=", html)  # solo el dueño puede reintentar
        own = self.page(self.operator, "/history/")
        self.assertIn(f"?reintentar={self.failed.pk}", own)
        self.assertNotIn('<small>Operador</small>', own)

    def test_history_rejects_inverted_dates_and_unknown_status_in_plain_language(self):
        html = self.page(self.quality, "/history/?date_from=2026-05-10&date_to=2026-05-01")
        self.assertIn("no puede ser posterior", html)
        api = APIClient()
        api.force_authenticate(self.quality)
        response = api.get("/api/history/", {"status": "inventado"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("no es válido", str(response.data))
        self.assertIn("no es válida", str(api.get("/api/history/", {"date_from": "2026-99-99"}).data))

    def test_history_is_paginated(self):
        with patch(START, return_value={"ok": True}):
            for number in range(26):
                start_analysis(batch_code=f"LOTE-P{number}", source="imagen", operator=self.other)
        first = self.page(self.quality, "/history/")
        self.assertIn("página 1 de 2", first)
        self.assertIn("page=2", first)
        self.assertIn("Página 2 de 2", self.page(self.quality, "/history/?page=2"))

    def test_failed_detail_is_honest_and_offers_retry_only_to_the_owner(self):
        html = self.page(self.quality, f"/history/{self.failed.pk}/")
        self.assertIn("El servicio de análisis no respondió.", html)
        self.assertIn("step active failed", html)
        self.assertNotIn('<span class="step-number">✓</span><span>Resultados', html)
        self.assertNotIn("?reintentar=", html)
        self.assertIn("Ana Pérez", html)
        self.assertIn(f"?reintentar={self.failed.pk}", self.page(self.operator, f"/history/{self.failed.pk}/"))

    def test_detail_lists_every_attempt_with_its_cause(self):
        with patch(START, side_effect=VisionServiceError("HTTP 401", code="vision_misconfigured")):
            retry_analysis(self.failed.pk, operator=self.operator)
        html = self.page(self.quality, f"/history/{self.failed.pk}/")
        self.assertIn("<h2>Intentos</h2>", html)
        self.assertIn("El servicio de análisis no respondió.", html)
        self.assertIn("no está bien configurado", html)
        self.assertIn("no servirá hasta que el administrador", html)

    def test_report_includes_flow_health_in_screen_and_exports(self):
        with patch(START, return_value={"ok": True}):
            stale = start_analysis(batch_code="LOTE-ABANDONADO", source="video", operator=self.operator)
        AnalysisSession.objects.filter(pk=stale.pk).update(last_activity_at=timezone.now() - timedelta(hours=2))
        today = timezone.localdate()
        report = create_production_report(date_from=today, date_to=today, supervisor=self.supervisor)
        flow = report.summary["flow"]
        self.assertEqual((flow["started"], flow["finished"], flow["errors"], flow["interrupted"]), (3, 1, 2, 1))
        self.assertIn("El servicio de análisis no respondió.", flow["error_causes"])
        self.assertIn("Análisis con error", export_report_csv(report).decode("utf-8-sig"))
        self.assertTrue(export_report_pdf(report).startswith(b"%PDF"))
        html = self.page(self.supervisor, "/reports/?creado=1")
        self.assertIn("Reporte generado", html)
        self.assertIn("Salud del flujo", html)

    def test_old_reports_without_flow_still_render_and_export(self):
        today = timezone.localdate()
        report = create_production_report(date_from=today, date_to=today, supervisor=self.supervisor)
        report.summary.pop("flow")
        report.save()
        self.assertIn("Camarones analizados", export_report_csv(report).decode("utf-8-sig"))
        self.assertNotIn("Salud del flujo", self.page(self.supervisor, "/reports/"))
