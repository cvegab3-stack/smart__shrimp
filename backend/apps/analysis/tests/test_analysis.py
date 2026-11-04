"""Pruebas de calibración versionada y ciclo de vida M2."""

from unittest.mock import patch

import requests
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import AuditEvent, User
from apps.analysis.models import AnalysisSession, ProcessingAttempt
from apps.analysis.services.calibration_service import create_calibration
from apps.analysis.services.frame_relay_service import relay_frame
from apps.analysis.services.session_service import retry_analysis, start_analysis
from apps.analysis.services.threshold_service import create_threshold_profile
from integrations.vision_client import VisionServiceError
from integrations.vision_client import process_frame
from shrimp_contracts.token_claims import verify_service_token


RANGES = {
    "pequeno": {"min_cm": 0, "max_cm": 8},
    "mediano": {"min_cm": 8.1, "max_cm": 13},
    "grande": {"min_cm": 13.1, "max_cm": None},
}


class AnalysisServiceTests(TestCase):
    """Cubre referencias inmutables, estados y reintentos."""

    def setUp(self):
        self.operator = User.objects.create_user("operator", password="password", role=User.Role.OPERATOR)
        self.admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        self.calibration = create_calibration(
            reference_length_cm=10, reference_pixels=500, size_ranges=RANGES, actor=self.admin,
        )
        self.thresholds = create_threshold_profile(
            detection_confidence=0.5, visual_condition_confidence=0.6, actor=self.admin,
        )

    def test_calibration_versions_do_not_overwrite_and_ranges_cannot_overlap(self):
        second = create_calibration(
            reference_length_cm=12, reference_pixels=600, size_ranges=RANGES, actor=self.admin,
        )
        self.calibration.refresh_from_db()
        self.assertEqual((self.calibration.version, second.version), (1, 2))
        self.assertFalse(self.calibration.is_active)
        self.assertTrue(second.is_active)
        invalid = {**RANGES, "mediano": {"min_cm": 7, "max_cm": 13}}
        with self.assertRaises(ValidationError):
            create_calibration(reference_length_cm=12, reference_pixels=600, size_ranges=invalid, actor=self.admin)

    @patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True})
    def test_session_starts_with_frozen_calibration_and_attempt(self, start_call):
        session = start_analysis(batch_code="LOT-1", source="imagen", operator=self.operator)
        self.assertEqual(session.status, AnalysisSession.Status.IN_PROGRESS)
        self.assertEqual(session.calibration_id, self.calibration.pk)
        self.assertEqual(ProcessingAttempt.objects.get(analysis=session).attempt_number, 1)
        self.assertEqual(start_call.call_args.args[0]["calibration_version"], 1)

    @patch("apps.analysis.services.session_service.vision_client.start_session", side_effect=VisionServiceError("timeout"))
    def test_processing_failure_transitions_to_error_without_partial_result(self, _start_call):
        session = start_analysis(batch_code="LOT-2", source="video", operator=self.operator)
        self.assertEqual(session.status, AnalysisSession.Status.ERROR)
        self.assertEqual(session.error_code, "vision_unavailable")

    @patch("apps.analysis.services.session_service.vision_client.start_session", side_effect=[VisionServiceError("timeout"), {"ok": True}])
    def test_retry_has_a_new_unique_attempt(self, _start_call):
        session = start_analysis(batch_code="LOT-3", source="imagen", operator=self.operator)
        self.assertEqual(session.status, AnalysisSession.Status.ERROR)
        retried = retry_analysis(session.pk, operator=self.operator)
        self.assertEqual(retried.status, AnalysisSession.Status.IN_PROGRESS)
        self.assertEqual(retried.current_attempt, 2)
        self.assertEqual(list(retried.attempts.values_list("attempt_number", flat=True)), [1, 2])

    @patch("apps.analysis.services.frame_relay_service.vision_client.process_frame", side_effect=VisionServiceError("timeout"))
    @patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True})
    def test_frame_failure_persists_error_so_the_analysis_can_be_retried(self, _start_call, _frame_call):
        session = start_analysis(batch_code="LOT-4", source="video", operator=self.operator)
        with self.assertRaises(VisionServiceError):
            relay_frame(analysis_id=session.pk, attempt_number=1, frame_id="f1", captured_at="2026-01-01T00:00:00Z",
                        image_base64="abc", operator=self.operator)
        session.refresh_from_db()
        self.assertEqual((session.status, session.error_code), (AnalysisSession.Status.ERROR, "vision_unavailable"))
        self.assertEqual(ProcessingAttempt.objects.get(analysis=session).status, AnalysisSession.Status.ERROR)
        self.assertTrue(AuditEvent.objects.filter(action="analysis.frame_failed").exists())
        self.assertEqual(retry_analysis(session.pk, operator=self.operator).current_attempt, 2)

    def test_only_administrator_can_change_calibration(self):
        client = APIClient()
        client.force_authenticate(self.operator)
        response = client.post("/api/calibration/", {
            "reference_length_cm": 10, "reference_pixels": 400, "size_ranges": RANGES,
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(action="permission.denied").exists())


@override_settings(
    VISION_SERVICE_URL="http://vision:8001",
    VISION_SERVICE_TOKEN_SECRET="integration-secret",
    VISION_TIMEOUT_SECONDS=2.5,
    VISION_MAX_RETRIES=1,
)
class VisionClientTests(TestCase):
    """Confirma timeout, reintento y token de servicio en el cliente único de M3."""

    @patch("integrations.vision_client.requests.post")
    def test_timeout_retries_once_then_sends_signed_service_token(self, post):
        response = post.return_value
        response.json.return_value = {"detections": []}
        post.side_effect = [requests.Timeout("first attempt"), response]
        result = process_frame({"frame_id": "f1"})
        self.assertEqual(result, {"detections": []})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["timeout"], 2.5)
        token = post.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        self.assertEqual(verify_service_token(token, "integration-secret").subject, "django")

    @patch("integrations.vision_client.requests.post", side_effect=requests.Timeout("service unavailable"))
    def test_timeout_exhaustion_is_reported_as_service_error(self, post):
        with self.assertRaises(VisionServiceError):
            process_frame({"frame_id": "f1"})
        self.assertEqual(post.call_count, 2)
