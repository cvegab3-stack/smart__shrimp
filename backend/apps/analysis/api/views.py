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
from apps.analysis.models import AnalysisSession, Calibration, ThresholdProfile
from apps.analysis.services.calibration_service import activate_calibration, create_calibration
from apps.analysis.services.frame_relay_service import relay_frame
from apps.analysis.services.snapshot_service import save_snapshot
from apps.analysis.services.session_service import retry_analysis, start_analysis
from apps.analysis.services.threshold_service import create_threshold_profile
from apps.results.services.report_service import complete_analysis
from integrations.vision_client import VisionServiceError


def _analysis_data(analysis: AnalysisSession) -> dict:
    return {
        "id": str(analysis.pk), "batch_code": analysis.batch_code, "source": analysis.source,
        "status": analysis.status, "attempt": analysis.current_attempt,
        "calibration_version": analysis.calibration.version,
        "model_mode": analysis.model_mode, "model_status": analysis.model_status,
        "shrimp_count": analysis.shrimp_count, "rejected_count": analysis.rejected_count,
        "error_code": analysis.error_code, "error_message": analysis.error_message,
        "created_at": analysis.created_at,
    }


class AnalysisListCreateView(APIView):
    """Lista análisis permitidos e inicia sesiones para operadores."""

    def get_permissions(self):
        self.permission_classes = (OperatorOnly,) if self.request.method == "POST" else (OperationalRoles,)
        return super().get_permissions()

    def get(self, request):
        sessions = AnalysisSession.objects.select_related("calibration").visible_to(request.user)
        return Response([_analysis_data(item) for item in sessions.order_by("-created_at")])

    def post(self, request):
        serializer = AnalysisCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            analysis = start_analysis(**serializer.validated_data, operator=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        code = status.HTTP_201_CREATED if analysis.status == AnalysisSession.Status.IN_PROGRESS else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(_analysis_data(analysis), status=code)


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
        return Response(_analysis_data(self.get_object(request, pk)))

    def post(self, request, pk):
        try:
            analysis = retry_analysis(pk, operator=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        except (AnalysisSession.DoesNotExist, ValueError) as exc:
            raise ValidationError(str(exc)) from exc
        code = status.HTTP_202_ACCEPTED if analysis.status == AnalysisSession.Status.IN_PROGRESS else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(_analysis_data(analysis), status=code)


class AnalysisCompleteView(APIView):
    """Finaliza por completo y persiste resultados atómicamente."""

    permission_classes = (OperatorOnly,)

    def post(self, request, pk):
        try:
            analysis = complete_analysis(pk, operator=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        except AnalysisSession.DoesNotExist as exc:
            raise NotFound("Análisis no encontrado.") from exc
        except VisionServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return Response(_analysis_data(analysis))


class FrameRelayView(APIView):
    """Acepta fotogramas del navegador y los reenvía por el cliente interno."""

    permission_classes = (OperatorOnly,)

    def post(self, request, pk):
        serializer = FrameInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = relay_frame(
                analysis_id=pk, operator=request.user,
                ip_address=request.META.get("REMOTE_ADDR"),
                attempt_number=data["attempt"], frame_id=data["frame_id"],
                captured_at=data["captured_at"], image_base64=data["image_base64"],
            )
        except AnalysisSession.DoesNotExist as exc:
            raise NotFound("Análisis no encontrado.") from exc
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        except VisionServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        analysis = AnalysisSession.objects.get(pk=pk)
        save_snapshot(analysis, data["attempt"], data["image_base64"], result.get("detections") or [])
        return Response(result)


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
