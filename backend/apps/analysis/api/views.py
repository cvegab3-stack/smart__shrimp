"""API de análisis, calibración, umbrales y recepción de fotogramas."""

from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.accounts.permissions import AdministratorOnly, OperationalRoles, OperatorOnly
from apps.analysis.api.serializers import (
    AnalysisCreateSerializer, CalibrationCreateSerializer, CalibrationSerializer,
    FrameInputSerializer, ThresholdCreateSerializer, ThresholdSerializer,
)
from apps.analysis.errors import INPUT, describe, get_error
from apps.analysis.models import AnalysisSession, Calibration, ThresholdProfile
from apps.analysis.services.calibration_service import activate_calibration, create_calibration
from apps.analysis.services.frame_relay_service import AnalysisNotInProgress, relay_frame
from apps.analysis.services.image_validation import InvalidImage, validate_image_base64
from apps.analysis.services.snapshot_service import save_snapshot
from apps.analysis.services.session_service import expire_stale_analyses, retry_analysis, start_analysis
from apps.analysis.services.threshold_service import create_threshold_profile
from apps.results.services.presentation_service import build_summary
from apps.results.services.report_service import NothingToFinish, complete_analysis
from integrations import vision_client
from integrations.vision_client import VisionServiceError


def analysis_payload(analysis: AnalysisSession) -> dict:
    """Estado del análisis tal como lo necesita la pantalla: incluye la clase del error y qué decirle al operador."""
    return {
        "id": str(analysis.pk), "batch_code": analysis.batch_code, "source": analysis.source,
        "status": analysis.status, "attempt": analysis.current_attempt,
        "calibration_version": analysis.calibration.version,
        "model_mode": analysis.model_mode, "model_status": analysis.model_status,
        "shrimp_count": analysis.shrimp_count, "rejected_count": analysis.rejected_count,
        "error_code": analysis.error_code, "error_message": analysis.error_message,
        "created_at": analysis.created_at, **describe(analysis.error_code),
    }


def _input_error(message: str, code: str = "invalid_image") -> Response:
    """Error de entrada: el análisis no cambia; se corrige el dato y se reenvía."""
    return Response({"detail": message, "error_code": code, "error_kind": INPUT, "retryable": False},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY)


def _state_response(analysis: AnalysisSession, http_status: int, detail: str | None = None) -> Response:
    """Respuesta de fallo con el estado real del análisis, para que la pantalla ofrezca la acción correcta."""
    analysis.refresh_from_db()
    data = analysis_payload(analysis)
    if detail is None:
        detail = data["operator_message"] or "El análisis no se pudo completar."
    return Response({**data, "detail": detail}, status=http_status)


def _not_in_progress_detail(analysis: AnalysisSession, attempt: int | None = None) -> str:
    if analysis.status == AnalysisSession.Status.FINISHED:
        return "Este análisis ya está finalizado. Empieza un análisis nuevo para otro lote."
    if analysis.status == AnalysisSession.Status.ERROR:
        return get_error(analysis.error_code).operator_text
    if attempt is not None and attempt != analysis.current_attempt:
        return "Este análisis se reintentó en otra pestaña o ventana. Continúa allí o recarga esta página."
    return "Este análisis ya no admite cambios."


class AnalysisListCreateView(APIView):
    """Lista análisis permitidos e inicia sesiones para operadores."""

    def get_permissions(self):
        self.permission_classes = (OperatorOnly,) if self.request.method == "POST" else (OperationalRoles,)
        return super().get_permissions()

    def get(self, request):
        expire_stale_analyses()
        sessions = AnalysisSession.objects.select_related("calibration").visible_to(request.user)
        return Response([analysis_payload(item) for item in sessions.order_by("-created_at")])

    def post(self, request):
        serializer = AnalysisCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            analysis = start_analysis(**serializer.validated_data, operator=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        if analysis.status != AnalysisSession.Status.IN_PROGRESS:
            return _state_response(analysis, status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(analysis_payload(analysis), status=status.HTTP_201_CREATED)


class AnalysisDetailView(APIView):
    """Devuelve estado de análisis o crea un nuevo intento tras un error."""

    def get_permissions(self):
        self.permission_classes = (OperatorOnly,) if self.request.method == "POST" else (OperationalRoles,)
        return super().get_permissions()

    def get_object(self, request, pk):
        query = AnalysisSession.objects.select_related("calibration", "operator").visible_to(request.user)
        try:
            return query.get(pk=pk)
        except AnalysisSession.DoesNotExist as exc:
            raise NotFound("Análisis no encontrado.") from exc

    def get(self, request, pk):
        expire_stale_analyses()
        return Response(analysis_payload(self.get_object(request, pk)))

    def post(self, request, pk):
        try:
            analysis = retry_analysis(pk, operator=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        except AnalysisSession.DoesNotExist as exc:
            raise NotFound("Análisis no encontrado.") from exc
        except ValueError as exc:
            return _state_response(AnalysisSession.objects.get(pk=pk), status.HTTP_409_CONFLICT, str(exc))
        if analysis.status != AnalysisSession.Status.IN_PROGRESS:
            return _state_response(analysis, status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(analysis_payload(analysis), status=status.HTTP_202_ACCEPTED)


class AnalysisCompleteView(APIView):
    """Finaliza por completo y persiste resultados atómicamente; responde ya con el resumen para mostrarlo."""

    permission_classes = (OperatorOnly,)

    def post(self, request, pk):
        try:
            analysis = AnalysisSession.objects.select_related("calibration").get(pk=pk, operator=request.user)
        except AnalysisSession.DoesNotExist as exc:
            raise NotFound("Análisis no encontrado.") from exc
        if analysis.status == AnalysisSession.Status.ERROR:
            return _state_response(analysis, status.HTTP_409_CONFLICT, _not_in_progress_detail(analysis))
        try:
            analysis = complete_analysis(pk, operator=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        except NothingToFinish as exc:
            return _input_error(str(exc), code="nothing_to_finish")
        except (VisionServiceError, ValueError):
            # complete_analysis ya dejó el intento con error y su causa: se devuelve ese estado.
            return _state_response(analysis, status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({**analysis_payload(analysis), "summary": build_summary(analysis)})


class FrameRelayView(APIView):
    """Acepta fotogramas del navegador y los reenvía por el cliente interno."""

    permission_classes = (OperatorOnly,)

    def post(self, request, pk):
        serializer = FrameInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            validate_image_base64(data["image_base64"])
        except InvalidImage as exc:
            return _input_error(str(exc))
        try:
            result = relay_frame(
                analysis_id=pk, operator=request.user,
                ip_address=request.META.get("REMOTE_ADDR"),
                attempt_number=data["attempt"], frame_id=data["frame_id"],
                captured_at=data["captured_at"], image_base64=data["image_base64"],
            )
        except AnalysisSession.DoesNotExist as exc:
            raise NotFound("Análisis no encontrado.") from exc
        except AnalysisNotInProgress:
            analysis = AnalysisSession.objects.get(pk=pk)
            return _state_response(analysis, status.HTTP_409_CONFLICT, _not_in_progress_detail(analysis, data["attempt"]))
        except VisionServiceError as exc:
            if get_error(exc.code).kind == INPUT:
                return _input_error(get_error(exc.code).operator_text)
            return _state_response(AnalysisSession.objects.get(pk=pk), status.HTTP_503_SERVICE_UNAVAILABLE)
        analysis = AnalysisSession.objects.get(pk=pk)
        save_snapshot(analysis, data["attempt"], data["image_base64"], result.get("detections") or [])
        return Response(result)


class VisionHealthView(APIView):
    """Indica al administrador si el servicio de análisis responde."""

    permission_classes = (AdministratorOnly,)

    def get(self, request):
        return Response({"available": vision_client.health()})


class CalibrationView(APIView):
    """Lee la calibración vigente o crea una versión como administrador."""

    def get_permissions(self):
        self.permission_classes = (AdministratorOnly,) if self.request.method == "POST" else (OperationalRoles,)
        return super().get_permissions()

    def get(self, request):
        calibration = Calibration.objects.filter(is_active=True).first()
        if calibration is None:
            return Response({"detail": "No existe una calibración vigente."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CalibrationSerializer(calibration).data)

    def post(self, request):
        serializer = CalibrationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            calibration = create_calibration(**serializer.validated_data, actor=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", exc.messages)) from exc
        return Response(CalibrationSerializer(calibration).data, status=status.HTTP_201_CREATED)


class CalibrationActivateView(APIView):
    """Pone en uso una versión anterior del historial, sin copiarla (solo administrador)."""

    permission_classes = (AdministratorOnly,)

    def post(self, request, version):
        try:
            calibration = activate_calibration(version, actor=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", exc.messages)) from exc
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(CalibrationSerializer(calibration).data)


class ThresholdView(APIView):
    """Consulta o registra la versión vigente de umbrales."""

    def get_permissions(self):
        self.permission_classes = (AdministratorOnly,) if self.request.method == "POST" else (OperationalRoles,)
        return super().get_permissions()

    def get(self, request):
        profile = ThresholdProfile.objects.first()
        return Response(ThresholdSerializer(profile).data if profile else None)

    def post(self, request):
        serializer = ThresholdCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = create_threshold_profile(**serializer.validated_data, actor=request.user)
        return Response(ThresholdSerializer(profile).data, status=status.HTTP_201_CREATED)
