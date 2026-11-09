"""Pruebas de atomicidad, historial, reportes y exportaciones."""

import base64
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.analysis.models import AnalysisSession, ProcessingAttempt
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
            "mediano": {"min_cm": 8, "max_cm": 13},
            "grande": {"min_cm": 13, "max_cm": None},
        }
        create_calibration(reference_length_cm=10, reference_pixels=500, size_ranges=ranges, actor=admin)
        create_threshold_profile(detection_confidence=0.5, visual_condition_confidence=0.5, actor=admin)
        with patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True}):
            self.analysis = start_analysis(batch_code="LOT-2026-01", source="imagen", operator=self.operator)
        # La imagen ya se analizó: solo se finaliza un intento con al menos un fotograma procesado.
        self.analysis.attempts.update(frames_processed=1)

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


FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"imagen-de-prueba" * 8  # solo importa la firma JPEG del inicio


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class AnalysisSnapshotAndSummaryTests(TestCase):
    """La imagen adjuntada se guarda y se muestra en el detalle; los resultados se presentan en lenguaje claro."""

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        settings_patch = override_settings(MEDIA_ROOT=self.media.name)
        settings_patch.enable()
        self.addCleanup(settings_patch.disable)
        self.operator = User.objects.create_user("operator", password="password", role=User.Role.OPERATOR)
        self.other = User.objects.create_user("other", password="password", role=User.Role.OPERATOR)
        self.quality = User.objects.create_user("quality", password="password", role=User.Role.QUALITY)
        admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        ranges = {"pequeno": {"min_cm": 0, "max_cm": 8}, "mediano": {"min_cm": 8, "max_cm": 13}, "grande": {"min_cm": 13, "max_cm": 20}}
        create_calibration(reference_length_cm=10, reference_pixels=500, size_ranges=ranges, actor=admin)
        create_threshold_profile(detection_confidence=0.5, visual_condition_confidence=0.5, actor=admin)
        self.image_b64 = base64.b64encode(FAKE_JPEG).decode()

    def start(self, source="imagen"):
        with patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True}):
            return start_analysis(batch_code="LOTE-IMG", source=source, operator=self.operator)

    def send_frame(self, analysis, detections, image_b64=None):
        api = APIClient()
        api.force_authenticate(self.operator)
        with patch("apps.analysis.services.frame_relay_service.vision_client.process_frame",
                   return_value={"detections": detections, "counters": {"counted": 0}}):
            return api.post(f"/api/analyses/{analysis.pk}/frames/", {
                "frame_id": "f1", "attempt": analysis.current_attempt, "captured_at": timezone.now().isoformat(),
                "image_base64": image_b64 or self.image_b64}, format="json")

    def finish(self, analysis, rows):
        summary = {"analysis_id": str(analysis.pk), "attempt": 1, "shrimp": rows, "shrimp_count": len(rows),
                   "rejected_count": 2, "model_mode": "inference", "model_status": "configured"}
        with patch("apps.results.services.report_service.vision_client.get_session_summary", return_value=summary):
            complete_analysis(analysis.pk, operator=self.operator)

    def test_uploaded_image_is_saved_and_served_only_to_allowed_users(self):
        analysis = self.start()
        detection = {"track_id": "track-1", "bbox": [10, 20, 110, 60], "length_cm": 12.0, "size_category": "mediano"}
        self.assertEqual(self.send_frame(analysis, [detection]).status_code, 200)
        attempt = analysis.attempts.get(attempt_number=1)
        self.assertEqual(attempt.snapshot_path, f"analyses/{analysis.pk}/attempt-1.jpg")
        self.assertEqual(attempt.snapshot_detections, [{**detection, "close_up": None}])
        client = Client()
        for user, expected in ((self.operator, 200), (self.quality, 200), (self.other, 404)):
            client.force_login(user)
            response = client.get(f"/history/{analysis.pk}/image/")
            self.assertEqual(response.status_code, expected, user.username)
            if expected == 200:
                self.assertEqual(b"".join(response.streaming_content), FAKE_JPEG)  # es la imagen enviada, no una fija

    def test_non_image_data_is_rejected_without_spending_the_attempt(self):
        analysis = self.start()
        response = self.send_frame(analysis, [], image_b64=base64.b64encode(b"<script>no soy una imagen</script>").decode())
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data["error_kind"], "entrada")
        self.assertIn("no es una imagen", response.data["detail"])
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AnalysisSession.Status.IN_PROGRESS)  # se elige otra foto, sin reintentar
        attempt = ProcessingAttempt.objects.get(analysis=analysis, attempt_number=1)
        self.assertEqual((attempt.snapshot_path, attempt.frames_processed), ("", 0))

    def test_video_keeps_last_frame_with_shrimp_at_most_once_per_second(self):
        analysis = self.start("video")
        self.send_frame(analysis, [])
        self.assertEqual(analysis.attempts.get(attempt_number=1).snapshot_path, "")  # sin camarones: no se guarda
        first = [{"track_id": "track-1", "bbox": [0, 0, 10, 10], "length_cm": 5.0, "size_category": "pequeno"}]
        self.send_frame(analysis, first)
        self.send_frame(analysis, [{**first[0], "track_id": "track-2"}])  # < 1 s después: se omite
        self.assertEqual(analysis.attempts.get(attempt_number=1).snapshot_detections[0]["track_id"], "track-1")

    def test_summary_is_readable_numbered_and_page_shows_real_image(self):
        analysis = self.start()
        self.send_frame(analysis, [{"track_id": f"track-{n}", "bbox": [n, n, n + 50, n + 20], "length_cm": None,
                                    "size_category": None} for n in (2, 10)])
        rows = [{**ROW, "track_id": "track-10", "length_cm": 30.0, "size_category": None},
                {**ROW, "track_id": "track-2", "length_cm": 7.5, "size_category": "pequeno"}]
        self.finish(analysis, rows)
        client = Client()
        client.force_login(self.operator)
        page = client.get(f"/history/{analysis.pk}/")
        html = page.content.decode()
        self.assertIn(f'src="/history/{analysis.pk}/image/"', html)
        self.assertNotIn("shrimp-inspection.png", html)  # ya no se muestra la imagen fija del prototipo
        self.assertNotIn("track-", html.split("<script")[0])  # ni identificadores internos en lo visible
        self.assertLess(html.index("Camarón 1"), html.index("Camarón 2"))
        self.assertIn("7,5 cm", html)
        self.assertIn("Fuera de rango", html)
        self.assertIn("2 detecciones descartadas", html)
        api = APIClient()
        api.force_authenticate(self.operator)
        summary = api.get(f"/api/history/{analysis.pk}/").json()["summary"]
        self.assertEqual([(r["number"], r["size"]) for r in summary["rows"]], [(1, "Pequeño"), (2, "Fuera de rango")])
        self.assertEqual({c["name"]: c["count"] for c in summary["counts"]}["Pequeño"], 1)
        self.assertEqual([b["label"] for b in summary["boxes"]], ["1 · Pequeño · 7,5 cm", "2 · Fuera de rango · 30,0 cm"])
        self.assertFalse(summary["show_condition"] or summary["show_weight"])


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CloseUpAndEmptyResultTests(AnalysisSnapshotAndSummaryTests):
    """Primer plano en imagen: se cuenta con aviso. Sin camarones: mensaje en vez de contadores en cero."""

    test_uploaded_image_is_saved_and_served_only_to_allowed_users = None
    test_non_image_data_is_not_saved_but_analysis_continues = None
    test_video_keeps_last_frame_with_shrimp_at_most_once_per_second = None
    test_summary_is_readable_numbered_and_page_shows_real_image = None

    def page(self, analysis):
        client = Client()
        client.force_login(self.operator)
        return client.get(f"/history/{analysis.pk}/").content.decode()

    def test_close_up_shrimp_is_counted_with_warning(self):
        analysis = self.start()
        self.send_frame(analysis, [{"track_id": "track-1", "bbox": [0, 0, 900, 500], "length_cm": 18.0,
                                    "size_category": "grande", "close_up": True}])
        self.finish(analysis, [{**ROW, "length_cm": 18.0, "size_category": "grande"}])
        html = self.page(analysis)
        self.assertIn("1 camarón ocupa casi toda la imagen", html)
        self.assertIn("(primer plano, poco fiable)", html)
        self.assertIn('class="size-counts"', html)

    def test_no_shrimp_shows_message_instead_of_zero_counters_and_singular_text(self):
        analysis = self.start()
        self.send_frame(analysis, [])
        summary = {"analysis_id": str(analysis.pk), "attempt": 1, "shrimp": [], "shrimp_count": 0,
                   "rejected_count": 1, "model_mode": "inference", "model_status": "configured"}
        with patch("apps.results.services.report_service.vision_client.get_session_summary", return_value=summary):
            complete_analysis(analysis.pk, operator=self.operator)
        html = self.page(analysis)
        self.assertNotIn('class="size-counts"', html)
        self.assertIn("No se contó ningún camarón.", html)
        self.assertIn("1 detección descartada", html)  # antes: "1 detecciones"
        self.assertNotIn("1 detecciones", html)

    def test_page_passes_calibration_resolution_to_compare_with_the_image(self):
        from apps.analysis.models import Calibration
        Calibration.objects.filter(is_active=True).update(image_width=1280, image_height=720)
        analysis = self.start()
        self.send_frame(analysis, [{"track_id": "track-1", "bbox": [1, 1, 5, 5], "length_cm": 5.0, "size_category": "pequeno"}])
        self.finish(analysis, [{**ROW, "length_cm": 5.0, "size_category": "pequeno"}])
        html = self.page(analysis)
        self.assertIn('data-calibration-width="1280" data-calibration-height="720"', html)
        self.assertIn("1280 × 720 px", html)
