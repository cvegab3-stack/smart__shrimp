"""Serializadores de entrada y salida de análisis."""

from rest_framework import serializers

from apps.analysis.models import AnalysisSession, Calibration, ThresholdProfile


class AnalysisCreateSerializer(serializers.Serializer):
    """Valida lote y origen de una sesión nueva."""

    batch_code = serializers.CharField(max_length=100)
    source = serializers.ChoiceField(choices=AnalysisSession.Source.choices)


class FrameInputSerializer(serializers.Serializer):
    """Valida un fotograma que el navegador entrega a Django."""

    frame_id = serializers.CharField(max_length=100)
    attempt = serializers.IntegerField(min_value=1)
    captured_at = serializers.DateTimeField()
    image_base64 = serializers.CharField()


class CalibrationSerializer(serializers.ModelSerializer):
    """Expone la calibración vigente sin permitir cambios desde el navegador."""

    class Meta:
        model = Calibration
        fields = ("version", "reference_length_cm", "reference_pixels", "size_ranges", "created_at")
        read_only_fields = fields


class CalibrationCreateSerializer(serializers.Serializer):
    """Valida los parámetros de calibración de administrador."""

    reference_length_cm = serializers.FloatField(min_value=0.000001)
    reference_pixels = serializers.IntegerField(min_value=1)
    size_ranges = serializers.DictField(child=serializers.DictField())


class ThresholdSerializer(serializers.ModelSerializer):
    """Representa la versión actual de umbrales."""

    class Meta:
        model = ThresholdProfile
        fields = ("detection_confidence", "visual_condition_confidence", "created_at")


class ThresholdCreateSerializer(serializers.Serializer):
    """Valida umbrales explícitos sin imponer valores por defecto."""

    detection_confidence = serializers.FloatField(min_value=0, max_value=1)
    visual_condition_confidence = serializers.FloatField(min_value=0, max_value=1)
