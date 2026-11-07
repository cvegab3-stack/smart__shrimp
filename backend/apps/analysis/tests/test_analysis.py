"""Pruebas de calibración versionada y ciclo de vida M2."""

from unittest.mock import patch

import requests
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
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
        response.status_code = 200
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


class CalibrationRangeValidationTests(TestCase):
    """Los rangos de tamaño deben ser lógicos: sin negativos, mínimo < máximo, sin solaparse y en orden."""

    def setUp(self):
        self.admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def errors_for(self, ranges, length=10, pixels=500):
        with self.assertRaises(ValidationError) as caught:
            create_calibration(reference_length_cm=length, reference_pixels=pixels, size_ranges=ranges, actor=self.admin)
        return " ".join(sum(caught.exception.message_dict.values(), []))

    def test_screenshot_values_are_rejected_with_clear_reasons(self):
        # Valores de la captura del usuario: máximos y mínimos negativos.
        ranges = {"pequeno": {"min_cm": 0.13, "max_cm": -0.16}, "mediano": {"min_cm": -0.11, "max_cm": -0.14},
                  "grande": {"min_cm": -0.09, "max_cm": -0.1}}
        text = self.errors_for(ranges, length=0.001, pixels=1)
        for expected in ("Pequeño: el máximo debe ser mayor que 0.", "Mediano: el mínimo no puede ser negativo.",
                         "Grande: el mínimo no puede ser negativo."):
            self.assertIn(expected, text)
        self.assertFalse(AuditEvent.objects.filter(action="calibration.created").exists())

    def test_min_must_be_lower_than_max(self):
        text = self.errors_for({**RANGES, "mediano": {"min_cm": 13, "max_cm": 9}})
        self.assertIn("Mediano: el mínimo debe ser menor que el máximo.", text)

    def test_ranges_must_go_from_small_to_large(self):
        reversed_ranges = {"pequeno": {"min_cm": 13.1, "max_cm": None}, "mediano": {"min_cm": 8.1, "max_cm": 13},
                           "grande": {"min_cm": 0, "max_cm": 8}}
        self.assertIn("El rango de pequeño debe ser menor que el de mediano.", self.errors_for(reversed_ranges))

    def test_optional_limits_still_allowed(self):
        open_ended = {"pequeno": {"min_cm": None, "max_cm": 8}, "mediano": {"min_cm": 8.1, "max_cm": 13},
                      "grande": {"min_cm": 13.1, "max_cm": None}}
        self.assertEqual(create_calibration(reference_length_cm=10, reference_pixels=500, size_ranges=open_ended,
                                            actor=self.admin).version, 1)

    def test_api_returns_400_with_readable_message_and_rejects_negative_reference(self):
        response = self.client.post("/api/calibration/", {"reference_length_cm": 10, "reference_pixels": 500, "size_ranges": {
            **RANGES, "pequeno": {"min_cm": -1, "max_cm": 8}}}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Pequeño: el mínimo no puede ser negativo.", str(response.json()))
        for field, value in (("reference_length_cm", -10), ("reference_pixels", -500)):
            payload = {"reference_length_cm": 10, "reference_pixels": 500, "size_ranges": RANGES, field: value}
            self.assertEqual(self.client.post("/api/calibration/", payload, format="json").status_code, 400, field)

    def test_threshold_values_render_with_decimal_point_for_number_inputs(self):
        # Con idioma español, 0.5 se escribía "0,5" y el campo numérico del navegador lo mostraba vacío.
        create_threshold_profile(detection_confidence=0.5, visual_condition_confidence=0.75, actor=self.admin)
        client = Client()
        client.force_login(self.admin)
        response = client.get("/calibration/")
        self.assertContains(response, 'id="detection-threshold" type="number" min="0" max="1" step="0.01" value="0.5"')
        self.assertContains(response, 'value="0.75"')
        self.assertContains(response, 'id="pequeno-min" type="number" min="0"')


class CalibrationSharedLimitTests(TestCase):
    """El máximo de una categoría puede ser el mínimo de la siguiente (sin hueco entre ellas)."""

    def setUp(self):
        self.admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)

    def test_shared_limits_are_accepted(self):
        shared = {"pequeno": {"min_cm": 0, "max_cm": 8}, "mediano": {"min_cm": 8, "max_cm": 13},
                  "grande": {"min_cm": 13, "max_cm": None}}
        self.assertEqual(create_calibration(reference_length_cm=10, reference_pixels=400, size_ranges=shared,
                                            actor=self.admin).size_ranges, shared)

    def test_real_overlap_is_still_rejected(self):
        overlap = {"pequeno": {"min_cm": 0, "max_cm": 8.5}, "mediano": {"min_cm": 8, "max_cm": 13},
                   "grande": {"min_cm": 13, "max_cm": None}}
        with self.assertRaises(ValidationError) as caught:
            create_calibration(reference_length_cm=10, reference_pixels=400, size_ranges=overlap, actor=self.admin)
        self.assertIn("Los rangos de pequeño y mediano se superponen.", str(caught.exception))


class CalibrationScaleLogicTests(TestCase):
    """La escala cm↔px debe ser medible (≥ 20 px) y se avisa si no es verosímil; los rangos se muestran claros."""

    SHARED = {"pequeno": {"min_cm": 0, "max_cm": 8}, "mediano": {"min_cm": 8, "max_cm": 13},
              "grande": {"min_cm": 13, "max_cm": None}}

    def setUp(self):
        self.admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        self.operator = User.objects.create_user("operator", password="password", role=User.Role.OPERATOR)

    def test_reference_under_20_pixels_is_rejected(self):
        # Valores de la captura del usuario: 4 cm = 3 px.
        with self.assertRaises(ValidationError) as caught:
            create_calibration(reference_length_cm=4, reference_pixels=3, size_ranges=self.SHARED, actor=self.admin)
        self.assertIn("al menos 20 px", str(caught.exception))
        self.assertEqual(create_calibration(reference_length_cm=1, reference_pixels=20, size_ranges=self.SHARED,
                                            actor=self.admin).version, 1)

    def test_scale_warning_only_when_implausible(self):
        from apps.analysis.models import Calibration
        normal = Calibration(reference_length_cm=10, reference_pixels=400, size_ranges=self.SHARED)
        self.assertEqual(normal.pixels_per_cm, 40)
        self.assertIsNone(normal.scale_warning)
        self.assertIn("poco realista", Calibration(reference_length_cm=100, reference_pixels=200).scale_warning)
        self.assertIn("poco realista", Calibration(reference_length_cm=1, reference_pixels=900).scale_warning)
        # Calibración antigua guardada antes de la regla de 20 px (como la del usuario): se avisa en pantalla.
        self.assertIn("solo 3 px", Calibration(reference_length_cm=4, reference_pixels=3).scale_warning)

    def test_bands_use_display_names_and_clear_text(self):
        from apps.analysis.models import Calibration
        open_ended = {"pequeno": {"min_cm": None, "max_cm": 8}, "mediano": {"min_cm": 8, "max_cm": 13.5},
                      "grande": {"min_cm": 13.5, "max_cm": None}}
        bands = Calibration(reference_length_cm=10, reference_pixels=400, size_ranges=open_ended).size_bands
        self.assertEqual([(b["name"], b["text"]) for b in bands],
                         [("Pequeño", "hasta 8 cm"), ("Mediano", "8 – 13,5 cm"), ("Grande", "desde 13,5 cm")])

    def test_pages_show_scale_names_and_zero_minimum(self):
        create_calibration(reference_length_cm=10, reference_pixels=400, size_ranges=self.SHARED, actor=self.admin)
        client = Client()
        client.force_login(self.admin)
        page = client.get("/calibration/")
        self.assertContains(page, "1 cm = 40 px")
        self.assertContains(page, "Pequeño")
        self.assertNotContains(page, "Pequeno<")
        self.assertNotContains(page, "poco realista")
        client.force_login(self.operator)
        page = client.get("/analysis/new/")
        self.assertContains(page, "<dt>Pequeño</dt><dd>0 – 8 cm</dd>")  # antes el 0 se mostraba como "—"


class CalibrationPageHelpTests(TestCase):
    """El administrador tiene la herramienta de medición y la explicación de los umbrales; el operador solo lee."""

    def setUp(self):
        self.admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        self.operator = User.objects.create_user("operator", password="password", role=User.Role.OPERATOR)

    def page(self, user):
        client = Client()
        client.force_login(user)
        return client.get("/calibration/")

    def test_admin_gets_measurement_tool_and_threshold_help(self):
        page = self.page(self.admin)
        self.assertContains(page, 'id="measure-panel"')
        self.assertContains(page, "js/calibration_measure.js")
        self.assertContains(page, "Recomendado: <strong>0.5</strong>")

    def test_operator_does_not_get_measurement_tool(self):
        page = self.page(self.operator)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'id="measure-panel"')
        self.assertNotContains(page, "calibration_measure.js")


class CalibrationHistoryTests(TestCase):
    """«Usar esta versión» pone en uso la misma versión (sin copiarla) y no se crean versiones duplicadas."""

    V1 = {"pequeno": {"min_cm": 0, "max_cm": 8}, "mediano": {"min_cm": 8, "max_cm": 13}, "grande": {"min_cm": 13, "max_cm": None}}
    V2 = {"pequeno": {"min_cm": 0, "max_cm": 6}, "mediano": {"min_cm": 6, "max_cm": 10}, "grande": {"min_cm": 10, "max_cm": None}}

    def setUp(self):
        self.admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        self.operator = User.objects.create_user("operator", password="password", role=User.Role.OPERATOR)
        create_calibration(reference_length_cm=10, reference_pixels=400, size_ranges=self.V1, actor=self.admin)
        create_calibration(reference_length_cm=12, reference_pixels=600, size_ranges=self.V2, actor=self.admin)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def test_activating_an_old_version_uses_it_without_creating_a_copy(self):
        from apps.analysis.models import Calibration
        response = self.api.post("/api/calibration/1/activate/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 1)
        self.assertEqual(Calibration.objects.count(), 2)  # no se creó ninguna versión nueva
        self.assertEqual(Calibration.objects.get(is_active=True).version, 1)
        event = AuditEvent.objects.get(action="calibration.activated")
        self.assertEqual(event.details, {"calibration_version": 1, "previous_version": 2})

    @patch("apps.analysis.services.session_service.vision_client.start_session", return_value={"ok": True})
    def test_analyses_keep_the_version_they_were_measured_with(self, _start):
        create_threshold_profile(detection_confidence=0.5, visual_condition_confidence=0.5, actor=self.admin)
        before = start_analysis(batch_code="LOTE-A", source="imagen", operator=self.operator)
        self.api.post("/api/calibration/1/activate/", {}, format="json")
        after = start_analysis(batch_code="LOTE-B", source="imagen", operator=self.operator)
        before.refresh_from_db()
        self.assertEqual((before.calibration.version, after.calibration.version), (2, 1))

    def test_identical_values_are_not_duplicated(self):
        from apps.analysis.models import Calibration
        same_as_v1 = {"reference_length_cm": 10.0, "reference_pixels": 400, "size_ranges": {
            "pequeno": {"min_cm": 0.0, "max_cm": 8.0}, "mediano": {"min_cm": 8, "max_cm": 13}, "grande": {"min_cm": 13, "max_cm": None}}}
        response = self.api.post("/api/calibration/", same_as_v1, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("iguales a los de la versión 1", str(response.json()))
        response = self.api.post("/api/calibration/", {"reference_length_cm": 12, "reference_pixels": 600, "size_ranges": self.V2}, format="json")
        self.assertIn("ya están en uso (versión 2)", str(response.json()))
        self.assertEqual(Calibration.objects.count(), 2)
        changed = {**same_as_v1, "reference_pixels": 401}  # un solo valor distinto ya es otra versión
        self.assertEqual(self.api.post("/api/calibration/", changed, format="json").status_code, 201)

    def test_cannot_activate_active_missing_or_invalid_versions(self):
        from apps.analysis.models import Calibration
        self.assertIn("ya está en uso", str(self.api.post("/api/calibration/2/activate/", {}, format="json").json()))
        self.assertEqual(self.api.post("/api/calibration/99/activate/", {}, format="json").status_code, 400)
        Calibration.objects.bulk_create([Calibration(version=50, reference_length_cm=4, reference_pixels=3, size_ranges=self.V1,
                                                     is_active=False, created_by_id=self.admin.pk)])  # como la v1 del usuario
        response = self.api.post("/api/calibration/50/activate/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("al menos 20 px", str(response.json()))
        self.assertEqual(Calibration.objects.get(is_active=True).version, 2)

    def test_only_admin_can_activate_and_page_shows_history(self):
        api = APIClient()
        api.force_authenticate(self.operator)
        self.assertEqual(api.post("/api/calibration/1/activate/", {}, format="json").status_code, 403)
        client = Client()
        client.force_login(self.admin)
        page = client.get("/calibration/")
        self.assertContains(page, "Historial de versiones")
        self.assertContains(page, 'data-activate-version="1"')
        self.assertNotContains(page, 'data-activate-version="2"')  # la que está en uso no se ofrece
        client.force_login(self.operator)
        self.assertNotContains(client.get("/calibration/"), "data-activate-version")


class CalibrationResolutionTests(TestCase):
    """La calibración guarda la resolución de la foto donde se midió (herramienta 📏)."""

    RANGES = {"pequeno": {"min_cm": 0, "max_cm": 8}, "mediano": {"min_cm": 8, "max_cm": 13}, "grande": {"min_cm": 13, "max_cm": None}}

    def setUp(self):
        self.admin = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def post(self, **extra):
        return self.api.post("/api/calibration/", {"reference_length_cm": 10, "reference_pixels": 400,
                                                   "size_ranges": self.RANGES, **extra}, format="json")

    def test_resolution_is_saved_shown_and_optional(self):
        from apps.analysis.models import Calibration
        response = self.post(image_width=1280, image_height=720)
        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.json()["image_width"], response.json()["image_height"]), (1280, 720))
        self.assertEqual(Calibration.objects.get(version=1).resolution, "1280 × 720 px")
        client = Client()
        client.force_login(self.admin)
        self.assertContains(client.get("/calibration/"), "1280 × 720 px")
        manual = self.post(reference_pixels=401)  # píxeles escritos a mano: sin resolución
        self.assertEqual(manual.status_code, 201)
        self.assertIsNone(Calibration.objects.get(version=2).resolution)

    def test_width_and_height_go_together(self):
        response = self.post(image_width=1280)
        self.assertEqual(response.status_code, 400)
        self.assertIn("ancho y el alto", str(response.json()))

    def test_same_values_with_another_resolution_is_a_different_version(self):
        self.assertEqual(self.post(image_width=1280, image_height=720).status_code, 201)
        self.assertEqual(self.post(image_width=1280, image_height=720).status_code, 400)  # duplicado exacto
        self.assertEqual(self.post(image_width=1920, image_height=1080).status_code, 201)  # otra cámara/resolución
