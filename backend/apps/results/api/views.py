"""API de historial, detalle, informes y exportaciones autorizadas."""

from io import BytesIO

from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import OperationalRoles, SupervisorOnly
from apps.accounts.services import record_event
from apps.analysis.models import AnalysisSession
from apps.results.api.serializers import (
    AnalysisHistorySerializer, ProductionReportSerializer, ReportCreateSerializer,
    ShrimpRecordSerializer,
)
from apps.results.models import ProductionReport, ShrimpRecord
from apps.results.services.csv_exporter import export_analysis_csv, export_report_csv
from apps.results.services.history_service import get_history
from apps.results.services.pdf_exporter import export_analysis_pdf, export_report_pdf
from apps.results.services.report_service import create_production_report


EXPORT_CONTENT_TYPES = {"csv": "text/csv; charset=utf-8", "pdf": "application/pdf"}


def _export_response(source, file_type: str, *, csv, pdf) -> FileResponse:
    """Genera la descarga CSV o PDF; cualquier otro formato es 404."""
    exporter = {"csv": csv, "pdf": pdf}.get(file_type)
    if exporter is None:
        raise Http404
    response = FileResponse(BytesIO(exporter(source)), content_type=EXPORT_CONTENT_TYPES[file_type])
    response["Content-Disposition"] = f'attachment; filename="smart-shrimp-{source.pk}.{file_type}"'
    return response


class HistoryListView(APIView):
    """Lista análisis con filtros por lote, fechas, estado y resultado."""

    permission_classes = (OperationalRoles,)

    def get(self, request):
        try:
            sessions = get_history(user=request.user, params=request.query_params)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return Response(AnalysisHistorySerializer(sessions, many=True).data)


class AnalysisResultsView(APIView):
    """Devuelve un análisis y sus registros históricos sin permitir edición."""

    permission_classes = (OperationalRoles,)

    def get(self, request, pk):
        try:
            analysis = AnalysisSession.objects.select_related("operator").visible_to(request.user).get(pk=pk)
        except AnalysisSession.DoesNotExist as exc:
            raise NotFound("Análisis no encontrado.") from exc
        rows = ShrimpRecord.objects.of_current_attempt(analysis)
        return Response({
            "analysis": AnalysisHistorySerializer(analysis).data,
            "results": ShrimpRecordSerializer(rows, many=True).data,
        })


class ReportListCreateView(APIView):
    """Crea o consulta informes consolidados, solo para supervisores."""

    permission_classes = (SupervisorOnly,)

    def get(self, request):
        reports = ProductionReport.objects.filter(created_by_id=request.user.pk)
        return Response(ProductionReportSerializer(reports, many=True).data)

    def post(self, request):
        serializer = ReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            report = create_production_report(
                **serializer.validated_data, supervisor=request.user,
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return Response(ProductionReportSerializer(report).data, status=status.HTTP_201_CREATED)


class ReportExportView(APIView):
    """Exporta informe persistido a CSV o PDF con las mismas métricas."""

    permission_classes = (SupervisorOnly,)

    def get(self, request, pk, file_type):
        try:
            report = ProductionReport.objects.get(pk=pk)
        except ProductionReport.DoesNotExist as exc:
            raise NotFound("Informe no encontrado.") from exc
        response = _export_response(report, file_type, csv=export_report_csv, pdf=export_report_pdf)
        record_event("report.exported", request.user, {"report_id": str(report.pk), "format": file_type}, request.META.get("REMOTE_ADDR"))
        return response


class ResultsExportView(APIView):
    """Exporta resultados individuales consultados, solo para supervisor."""

    permission_classes = (SupervisorOnly,)

    def get(self, request, pk, file_type):
        try:
            analysis = AnalysisSession.objects.get(pk=pk, status=AnalysisSession.Status.FINISHED)
        except AnalysisSession.DoesNotExist as exc:
            raise NotFound("No hay resultados finalizados para exportar.") from exc
        response = _export_response(analysis, file_type, csv=export_analysis_csv, pdf=export_analysis_pdf)
        record_event("results.exported", request.user, {"analysis_id": str(analysis.pk), "format": file_type}, request.META.get("REMOTE_ADDR"))
        return response
