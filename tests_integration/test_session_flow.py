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
        analysis.attempts.update(frames_processed=1)
        summary = {"analysis_id": str(analysis.pk), "attempt": 1, "shrimp": [], "shrimp_count": 0,
                   "rejected_count": 0, "model_mode": "inference", "model_status": "configured"}
        with patch("apps.results.services.report_service.vision_client.get_session_summary", return_value=summary):
            finished = complete_analysis(analysis.pk, operator=operator)
        self.assertEqual(finished.status, AnalysisSession.Status.FINISHED)
        self.assertEqual(finished.model_mode, "inference")
        self.assertEqual(get_history(user=operator, params={}).get(pk=analysis.pk).shrimp_count, 0)


class AnalysisRecoveryFlowTests(TestCase):
    """Recorrido completo por la API, como lo hace la pantalla: falla, reintento y finalización."""

    def test_failure_retry_and_finish_end_to_end(self):
        import base64
        import struct
        import tempfile

        from django.test import override_settings

        from django.utils import timezone
        from rest_framework.test import APIClient

        from apps.analysis.models import ProcessingAttempt
        from integrations.vision_client import VisionServiceError

        operator = User.objects.create_user("operator", password="password", role=User.Role.OPERATOR)
        admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        ranges = {"pequeno": {"min_cm": 0, "max_cm": 8}, "mediano": {"min_cm": 8.1, "max_cm": 13}, "grande": {"min_cm": 13.1, "max_cm": None}}
        create_calibration(reference_length_cm=10, reference_pixels=500, size_ranges=ranges, actor=admin)
        create_threshold_profile(detection_confidence=0.5, visual_condition_confidence=0.5, actor=admin)
        api = APIClient()
        api.force_authenticate(operator)
        media = tempfile.TemporaryDirectory()  # las imágenes de prueba no van a la carpeta media real
        self.addCleanup(media.cleanup)
        media_settings = override_settings(MEDIA_ROOT=media.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 480, 640, 3) + b"\x00" * 9
        image = base64.b64encode(b"\xff\xd8" + sof0 + b"\xff\xda" + b"\x00" * 10).decode()

        def frame(attempt, **mock):
            with patch("apps.analysis.services.frame_relay_service.vision_client.process_frame", **mock):
                return api.post(f"/api/analyses/{analysis_id}/frames/", {
                    "frame_id": "f", "attempt": attempt, "captured_at": timezone.now().isoformat(),
                    "image_base64": image}, format="json")

        with patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True}):
            created = api.post("/api/analyses/", {"batch_code": "INTEGRACION-2", "source": "imagen"}, format="json")
        self.assertEqual(created.status_code, 201)
        analysis_id = created.data["id"]

        failed = frame(1, side_effect=VisionServiceError("timeout", code="vision_unavailable"))
        self.assertEqual((failed.status_code, failed.data["status"], failed.data["retryable"]), (503, "con_error", True))

        with patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True}):
            retried = api.post(f"/api/analyses/{analysis_id}/", {}, format="json")
        self.assertEqual((retried.status_code, retried.data["attempt"]), (202, 2))

        self.assertEqual(frame(2, return_value={"detections": [], "counters": {}}).status_code, 200)
        summary = {"analysis_id": analysis_id, "attempt": 2, "shrimp": [], "shrimp_count": 0,
                   "rejected_count": 0, "model_mode": "inference", "model_status": "configured"}
        with patch("apps.results.services.report_service.vision_client.get_session_summary", return_value=summary):
            done = api.post(f"/api/analyses/{analysis_id}/complete/", {}, format="json")
        self.assertEqual((done.status_code, done.data["status"]), (200, AnalysisSession.Status.FINISHED))
        statuses = list(ProcessingAttempt.objects.filter(analysis_id=analysis_id).order_by("attempt_number")
                        .values_list("status", flat=True))
        self.assertEqual(statuses, [AnalysisSession.Status.ERROR, AnalysisSession.Status.FINISHED])
        self.assertEqual(get_history(user=operator, params={"status": "finalizado"}).get(pk=analysis_id).current_attempt, 2)
