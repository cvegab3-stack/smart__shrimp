"""Serializadores de resultados, sesiones e informes."""

from rest_framework import serializers

from apps.analysis.models import AnalysisSession
from apps.results.models import ProductionReport, ShrimpRecord
from apps.results.services.report_service import VISUAL_DISCLAIMER


class ShrimpRecordSerializer(serializers.ModelSerializer):
    """Expone valores por ejemplar sin presentar estimaciones como mediciones."""

    weight_label = serializers.SerializerMethodField()
    visual_disclaimer = serializers.SerializerMethodField()

    class Meta:
        model = ShrimpRecord
        fields = (
            "track_id", "confidence", "integrity", "presentation", "visual_condition",
            "visual_condition_confidence", "length_cm", "size_category", "estimated_weight_g",
            "weight_label", "visual_disclaimer",
        )

    def get_weight_label(self, record):
        return "valor estimado" if record.estimated_weight_g is not None else None

    def get_visual_disclaimer(self, record):
        return VISUAL_DISCLAIMER


class AnalysisHistorySerializer(serializers.ModelSerializer):
    """Representa una sesión con el número de resultados guardados."""

    operator_name = serializers.CharField(source="operator.username", read_only=True)

    class Meta:
        model = AnalysisSession
        fields = (
            "id", "batch_code", "operator_name", "source", "status", "shrimp_count",
            "rejected_count", "model_mode", "model_status", "calibration_id",
            "current_attempt", "error_code", "error_message", "created_at", "finished_at",
        )


class ProductionReportSerializer(serializers.ModelSerializer):
    """Serializa la tabla consolidada almacenada."""

    class Meta:
        model = ProductionReport
        fields = ("id", "date_from", "date_to", "summary", "created_at")
        read_only_fields = fields


class ReportCreateSerializer(serializers.Serializer):
    """Valida el período solicitado para un informe."""

    date_from = serializers.DateField()
    date_to = serializers.DateField()
