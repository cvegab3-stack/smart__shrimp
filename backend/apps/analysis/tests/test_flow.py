"""Flujo de análisis: clases de error, validación de imagen, transiciones de estado, reintento e interrupción."""

import base64
import struct
from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.analysis.errors import CATALOG, CONFIGURATION, INPUT, TRANSIENT, describe, get_error
from apps.analysis.models import AnalysisSession, ProcessingAttempt
from apps.analysis.services.calibration_service import create_calibration
from apps.analysis.services.image_validation import InvalidImage, image_size, validate_image_base64
from apps.analysis.services.session_service import expire_stale_analyses, start_analysis
from apps.analysis.services.threshold_service import create_threshold_profile
from integrations.vision_client import VisionServiceError, process_frame

RANGES = {"pequeno": {"min_cm": 0, "max_cm": 8}, "mediano": {"min_cm": 8, "max_cm": 13}, "grande": {"min_cm": 13, "max_cm": None}}


def png(width: int, height: int) -> bytes:
    """Cabecera PNG mínima (firma + IHDR): basta para leer las dimensiones."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00" + b"\x00" * 4


def jpeg(width: int, height: int) -> bytes:
    """JPEG con APP0 y SOF0, como los que genera el navegador."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xda" + b"\x00" * 20


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def http_response(status: int, payload=None) -> MagicMock:
    response = MagicMock(status_code=status, text="")
    response.json.return_value = payload if payload is not None else {}
    return response


class ErrorCatalogTests(TestCase):
    """Cada código tiene clase y textos claros; los textos nunca exponen componentes internos."""

    def test_every_code_has_a_kind_and_texts_without_internal_names(self):
        for code, error in CATALOG.items():
            self.assertIn(error.kind, (INPUT, TRANSIENT, CONFIGURATION), code)
            for text in (error.operator_text, error.record_text):
                self.assertTrue(text)
                self.assertNotIn("M3", text)
                self.assertNotIn("HTTP", text)

    def test_input_errors_are_not_retryable_and_legacy_codes_are_readable(self):
        self.assertFalse(get_error("invalid_image").retryable)
        self.assertTrue(get_error("vision_unavailable").retryable)
        self.assertEqual(get_error("vision_summary_error").kind, CONFIGURATION)  # código de versiones anteriores
        self.assertEqual(describe("")["retryable"], False)
        self.assertIn("inesperado", get_error("no_existe").record_text)


@override_settings(VISION_SERVICE_URL="http://vision:8001", VISION_SERVICE_TOKEN_SECRET="secret", VISION_MAX_RETRIES=1)
class VisionClientClassificationTests(TestCase):
    """Solo se repite lo que puede salir bien al repetirlo; cada fallo sale con su código."""

    def call(self, *responses):
        with patch("integrations.vision_client.requests.post", side_effect=list(responses)) as post:
            try:
                return process_frame({"frame_id": "f"}), post.call_count
            except VisionServiceError as exc:
                return exc, post.call_count

    def test_unreadable_image_is_an_input_error_and_is_not_repeated(self):
        error, calls = self.call(http_response(422, {"detail": "No se pudo decodificar"}))
        self.assertEqual((error.code, calls), ("invalid_image", 1))

    def test_lost_session_and_auth_errors_are_not_repeated(self):
        self.assertEqual(self.call(http_response(404))[0].code, "vision_session_lost")
        self.assertEqual(self.call(http_response(409))[0].code, "vision_session_lost")
        error, calls = self.call(http_response(401))
        self.assertEqual((error.code, calls), ("vision_misconfigured", 1))

    def test_server_errors_are_repeated_then_reported_as_unavailable(self):
        result, calls = self.call(http_response(502), http_response(200, {"detections": []}))
        self.assertEqual((result, calls), ({"detections": []}, 2))
        error, calls = self.call(http_response(500), requests.ConnectionError("caído"))
        self.assertEqual((error.code, calls), ("vision_unavailable", 2))

    def test_non_object_response_is_invalid(self):
        error, _ = self.call(http_response(200, ["no", "soy", "objeto"]))
        self.assertEqual(error.code, "vision_invalid_response")

    @override_settings(VISION_SERVICE_TOKEN_SECRET="")
    def test_missing_secret_is_a_configuration_error(self):
        with self.assertRaises(VisionServiceError) as caught:
            process_frame({})
        self.assertEqual(get_error(caught.exception.code).kind, CONFIGURATION)


@override_settings(ANALYSIS_MIN_IMAGE_SIDE=240, ANALYSIS_MAX_IMAGE_MB=1)
class ImageValidationTests(TestCase):
    """Se valida lo que realmente se envía: base64, firma, peso y dimensiones de la cabecera."""

    def test_reads_dimensions_from_png_and_jpeg_headers(self):
        self.assertEqual(image_size(png(640, 480)), (640, 480))
        self.assertEqual(image_size(jpeg(1280, 720)), (1280, 720))
        self.assertIsNone(image_size(b"\xff\xd8\xff\xe0truncado"))

    def test_valid_images_pass(self):
        self.assertTrue(validate_image_base64(b64(jpeg(640, 480))))
        self.assertTrue(validate_image_base64(b64(png(240, 240))))

    def test_each_problem_has_a_clear_reason(self):
        cases = {
            "no-es-base64!!": "dañada",
            b64(b""): "vacía",
            b64(b"GIF89a" + b"\x00" * 20): "no es una imagen",
            b64(jpeg(200, 150)): "demasiado pequeña",
            b64(jpeg(640, 480) + b"\x00" * (1024 * 1024)): "máximo es 1 MB",
        }
        for value, reason in cases.items():
            with self.subTest(reason=reason), self.assertRaises(InvalidImage) as caught:
                validate_image_base64(value)
            self.assertIn(reason, str(caught.exception))


@override_settings(ANALYSIS_IDLE_MINUTES=15)
class AnalysisFlowApiTests(TestCase):
    """Cada respuesta deja al análisis en el estado correcto y le dice a la pantalla qué ofrecer."""

    def setUp(self):
        self.operator = User.objects.create_user("operator", password="password", role=User.Role.OPERATOR)
        self.other = User.objects.create_user("other", password="password", role=User.Role.OPERATOR)
        admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        create_calibration(reference_length_cm=10, reference_pixels=500, size_ranges=RANGES, actor=admin)
        create_threshold_profile(detection_confidence=0.5, visual_condition_confidence=0.5, actor=admin)
        self.api = APIClient()
        self.api.force_authenticate(self.operator)
        self.image = b64(jpeg(640, 480))

    def start(self, source="imagen"):
        with patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True}):
            return start_analysis(batch_code="LOTE-FLUJO", source=source, operator=self.operator)

    def frame(self, analysis, *, side_effect=None, image=None, attempt=None):
        result = {"detections": [], "counters": {"counted": 0}}
        with patch("apps.analysis.services.frame_relay_service.vision_client.process_frame",
                   side_effect=side_effect, return_value=result) as call:
            response = self.api.post(f"/api/analyses/{analysis.pk}/frames/", {
                "frame_id": "f1", "attempt": attempt or analysis.current_attempt,
                "captured_at": timezone.now().isoformat(), "image_base64": image or self.image}, format="json")
        return response, call

    def summary(self, analysis, attempt):
        return {"analysis_id": str(analysis.pk), "attempt": attempt, "shrimp": [], "shrimp_count": 0,
                "rejected_count": 0, "model_mode": "inference", "model_status": "configured"}

    def test_service_down_on_create_returns_the_error_state_with_retry(self):
        with patch("apps.analysis.services.session_service.vision_client.start_session",
                   side_effect=VisionServiceError("ConnectionError", code="vision_unavailable")):
            response = self.api.post("/api/analyses/", {"batch_code": "L-1", "source": "imagen"}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual((response.data["status"], response.data["retryable"]), ("con_error", True))
        self.assertIn("Reintentar", response.data["detail"])
        self.assertEqual(response.data["error_message"], "El servicio de análisis no respondió.")  # sin detalle técnico

    def test_bad_image_is_rejected_before_the_service_and_does_not_change_the_state(self):
        analysis = self.start()
        response, call = self.frame(analysis, image=b64(jpeg(100, 80)))
        self.assertEqual((response.status_code, response.data["error_kind"]), (422, INPUT))
        call.assert_not_called()  # no se gastó una llamada al servicio
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AnalysisSession.Status.IN_PROGRESS)

    def test_image_the_service_cannot_decode_keeps_the_analysis_in_progress(self):
        analysis = self.start()
        response, _ = self.frame(analysis, side_effect=VisionServiceError("HTTP 422", code="invalid_image", status=422))
        self.assertEqual(response.status_code, 422)
        self.assertIn("Elige otra foto", response.data["detail"])
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AnalysisSession.Status.IN_PROGRESS)
        self.assertEqual(self.frame(analysis)[0].status_code, 200)  # la siguiente imagen sí se procesa

    def test_service_failure_on_frame_leaves_a_retryable_error(self):
        analysis = self.start()
        response, _ = self.frame(analysis, side_effect=VisionServiceError("timeout", code="vision_unavailable"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual((response.data["status"], response.data["error_code"]), ("con_error", "vision_unavailable"))
        self.assertTrue(response.data["retryable"])

    def test_frame_counts_and_activity_are_recorded(self):
        analysis = self.start()
        before = AnalysisSession.objects.get(pk=analysis.pk).last_activity_at
        self.assertEqual(self.frame(analysis)[0].status_code, 200)
        attempt = ProcessingAttempt.objects.get(analysis=analysis, attempt_number=1)
        self.assertEqual(attempt.frames_processed, 1)
        self.assertGreaterEqual(AnalysisSession.objects.get(pk=analysis.pk).last_activity_at, before)

    def test_image_frames_get_the_longer_timeout(self):
        with self.settings(VISION_IMAGE_TIMEOUT_SECONDS=15, VISION_TIMEOUT_SECONDS=5):
            _, image_call = self.frame(self.start("imagen"))
            _, video_call = self.frame(self.start("video"))
        self.assertEqual(image_call.call_args.kwargs["timeout"], 15)
        self.assertEqual(video_call.call_args.kwargs["timeout"], 5)

    def test_frame_for_an_analysis_with_error_returns_its_state(self):
        analysis = self.start()
        self.frame(analysis, side_effect=VisionServiceError("timeout"))
        response, call = self.frame(analysis)
        self.assertEqual((response.status_code, response.data["status"]), (409, "con_error"))
        call.assert_not_called()

    def test_frame_from_an_old_attempt_says_it_was_retried_elsewhere(self):
        analysis = self.start()
        self.frame(analysis, side_effect=VisionServiceError("timeout"))
        with patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True}):
            self.api.post(f"/api/analyses/{analysis.pk}/", {}, format="json")
        response, _ = self.frame(analysis, attempt=1)
        self.assertEqual(response.status_code, 409)
        self.assertIn("otra pestaña", response.data["detail"])

    def test_cannot_finish_without_a_processed_frame(self):
        analysis = self.start("video")
        response = self.api.post(f"/api/analyses/{analysis.pk}/complete/", {}, format="json")
        self.assertEqual((response.status_code, response.data["error_code"]), (422, "nothing_to_finish"))
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AnalysisSession.Status.IN_PROGRESS)

    def test_finish_failure_keeps_the_cause_and_success_returns_the_summary(self):
        analysis = self.start()
        self.frame(analysis)
        with patch("apps.results.services.report_service.vision_client.get_session_summary",
                   side_effect=VisionServiceError("HTTP 404", code="vision_session_lost", status=404)):
            failed = self.api.post(f"/api/analyses/{analysis.pk}/complete/", {}, format="json")
        self.assertEqual((failed.status_code, failed.data["error_code"]), (503, "vision_session_lost"))
        self.assertIn("se reinició", failed.data["detail"])
        with patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True}):
            self.assertEqual(self.api.post(f"/api/analyses/{analysis.pk}/", {}, format="json").status_code, 202)
        analysis.refresh_from_db()
        self.frame(analysis)
        with patch("apps.results.services.report_service.vision_client.get_session_summary",
                   return_value=self.summary(analysis, 2)):
            done = self.api.post(f"/api/analyses/{analysis.pk}/complete/", {}, format="json")
        self.assertEqual((done.status_code, done.data["status"]), (200, "finalizado"))
        self.assertIn("summary", done.data)  # la pantalla no necesita otra petición para mostrar el resultado

    def test_invalid_summary_is_a_configuration_error(self):
        analysis = self.start()
        self.frame(analysis)
        with patch("apps.results.services.report_service.vision_client.get_session_summary",
                   return_value={"analysis_id": "otro", "attempt": 1}):
            response = self.api.post(f"/api/analyses/{analysis.pk}/complete/", {}, format="json")
        self.assertEqual((response.status_code, response.data["error_kind"]), (503, CONFIGURATION))
        self.assertIn("administrador", response.data["detail"])

    def test_retry_only_from_error_and_explains_why_not(self):
        analysis = self.start()
        in_progress = self.api.post(f"/api/analyses/{analysis.pk}/", {}, format="json")
        self.assertEqual((in_progress.status_code, in_progress.data["status"]), (409, "en_curso"))
        self.assertIn("sigue en curso", in_progress.data["detail"])
        other = APIClient()
        other.force_authenticate(self.other)
        self.assertEqual(other.post(f"/api/analyses/{analysis.pk}/", {}, format="json").status_code, 404)

    def test_stale_analyses_become_interrupted_and_retryable(self):
        stale = self.start()
        fresh = self.start()
        AnalysisSession.objects.filter(pk=stale.pk).update(last_activity_at=timezone.now() - timedelta(minutes=20))
        AnalysisSession.objects.filter(pk=fresh.pk).update(last_activity_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(expire_stale_analyses(), 1)
        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual((stale.status, stale.error_code), (AnalysisSession.Status.ERROR, "interrupted"))
        self.assertEqual(fresh.status, AnalysisSession.Status.IN_PROGRESS)
        self.assertEqual(ProcessingAttempt.objects.get(analysis=stale).status, AnalysisSession.Status.ERROR)
        with patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True}):
            self.assertEqual(self.api.post(f"/api/analyses/{stale.pk}/", {}, format="json").status_code, 202)

    def test_live_page_opens_an_own_failed_lot_in_retry_mode(self):
        analysis = self.start()
        self.frame(analysis, side_effect=VisionServiceError("timeout"))
        client = Client()
        client.force_login(self.operator)
        html = client.get(f"/analysis/new/?reintentar={analysis.pk}").content.decode()
        self.assertIn('id="retry-analysis-data"', html)
        client.force_login(self.other)
        html = client.get(f"/analysis/new/?reintentar={analysis.pk}").content.decode()
        self.assertNotIn('id="retry-analysis-data"', html)
        self.assertIn("ya no se puede reintentar", html)
        self.assertIn("ya no se puede reintentar", client.get("/analysis/new/?reintentar=no-es-uuid").content.decode())


class AdministratorFlowTests(TestCase):
    """El administrador ve el estado del servicio y los errores que solo él puede corregir."""

    def setUp(self):
        self.admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        self.operator = User.objects.create_user("operator", password="password", role=User.Role.OPERATOR)
        create_calibration(reference_length_cm=10, reference_pixels=500, size_ranges=RANGES, actor=self.admin)
        create_threshold_profile(detection_confidence=0.5, visual_condition_confidence=0.5, actor=self.admin)

    def failed(self, code):
        with patch("apps.analysis.services.session_service.vision_client.start_session",
                   side_effect=VisionServiceError("x", code=code)):
            return start_analysis(batch_code=f"L-{code}", source="imagen", operator=self.operator)

    def test_dashboard_lists_configuration_errors_only(self):
        self.failed("vision_misconfigured")
        self.failed("vision_unavailable")
        client = Client()
        client.force_login(self.admin)
        html = client.get("/").content.decode()
        section = html[html.index('class="config-errors"'):html.index("</ul>", html.index('class="config-errors"'))]
        self.assertIn("Lote L-vision_misconfigured", section)
        self.assertNotIn("L-vision_unavailable", section)  # transitorio: lo resuelve el operador reintentando
        self.assertIn("El servicio de análisis no está bien configurado.", section)
        client.force_login(self.operator)
        self.assertNotIn("Errores de configuración", client.get("/").content.decode())

    def test_vision_health_is_only_for_the_administrator(self):
        api = APIClient()
        api.force_authenticate(self.admin)
        with patch("apps.analysis.api.views.vision_client.health", return_value=False):
            self.assertEqual(api.get("/api/vision/health/").data, {"available": False})
        api.force_authenticate(self.operator)
        self.assertEqual(api.get("/api/vision/health/").status_code, 403)
