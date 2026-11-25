"""Serializadores de entrada y salida de análisis."""

from django.utils import timezone
from rest_framework import serializers

from apps.analysis.models import AnalysisSession, Calibration, ThresholdProfile
from apps.analysis.services.session_service import LOT_FIELDS


class AnalysisCreateSerializer(serializers.Serializer):
    """Valida una sesión nueva.

    - Cámara (video): conteo de un lote. Código, fecha de registro y peso son obligatorios; el resto es opcional.
    - Imagen: foto de un camarón suelto. No lleva datos de lote; si no se manda código, se genera uno (FOTO-…).
    """

    batch_code = serializers.CharField(max_length=100, required=False, allow_blank=True)
    source = serializers.ChoiceField(choices=AnalysisSession.Source.choices)
    lot_date = serializers.DateField(required=False, allow_null=True)
    lot_weight_kg = serializers.FloatField(min_value=0.001, max_value=100000, required=False, allow_null=True)
    supplier = serializers.CharField(max_length=120, required=False, allow_blank=True)
    pond = serializers.CharField(max_length=60, required=False, allow_blank=True)
    harvest_date = serializers.DateField(required=False, allow_null=True)
    product_presentation = serializers.ChoiceField(choices=AnalysisSession.ProductPresentation.choices, required=False,
                                                   allow_blank=True)
    declared_size = serializers.CharField(max_length=20, required=False, allow_blank=True)
    expected_count = serializers.IntegerField(min_value=1, max_value=1000000, required=False, allow_null=True)
    product_temperature_c = serializers.FloatField(min_value=-40, max_value=60, required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        code = (attrs.get("batch_code") or "").strip()
        if attrs["source"] == AnalysisSession.Source.IMAGE:
            stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
            return {"batch_code": code or f"FOTO-{stamp}", "source": attrs["source"]}
        errors = {}
        if not code:
            errors["batch_code"] = "Escribe el código o nombre del lote."
        if attrs.get("lot_date") is None:
            errors["lot_date"] = "Indica la fecha de registro del lote."
        if attrs.get("lot_weight_kg") is None:
            errors["lot_weight_kg"] = "Indica el peso del lote en kg."
        harvest, registered = attrs.get("harvest_date"), attrs.get("lot_date")
        if harvest and registered and harvest > registered:
            errors["harvest_date"] = "La fecha de cosecha no puede ser posterior a la de registro."
        if errors:
            raise serializers.ValidationError(errors)
        lot = {field: attrs[field] for field in LOT_FIELDS if attrs.get(field) not in (None, "")}
        for field in ("supplier", "pond", "declared_size", "notes"):
            if field in lot:
                lot[field] = lot[field].strip()
        return {"batch_code": code, "source": attrs["source"], **lot}


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
        fields = ("version", "reference_length_cm", "reference_pixels", "size_ranges", "created_at", "based_on_version",
                  "image_width", "image_height")
        read_only_fields = fields


class CalibrationCreateSerializer(serializers.Serializer):
    """Valida los parámetros de calibración de administrador."""

    reference_length_cm = serializers.FloatField(min_value=0.000001)
    reference_pixels = serializers.IntegerField(min_value=1)
    size_ranges = serializers.DictField(child=serializers.DictField())
    # Resolución de la imagen donde se midió (la rellena la herramienta 📏). Opcional, pero ambos o ninguno.
    image_width = serializers.IntegerField(min_value=1, max_value=20000, required=False, allow_null=True)
    image_height = serializers.IntegerField(min_value=1, max_value=20000, required=False, allow_null=True)

    def validate(self, attrs):
        if (attrs.get("image_width") is None) != (attrs.get("image_height") is None):
            raise serializers.ValidationError("Indique el ancho y el alto de la imagen, o ninguno.")
        return attrs


class ThresholdSerializer(serializers.ModelSerializer):
    """Representa la versión actual de umbrales."""

    class Meta:
        model = ThresholdProfile
        fields = ("detection_confidence", "visual_condition_confidence", "created_at")


class ThresholdCreateSerializer(serializers.Serializer):
    """Valida umbrales explícitos sin imponer valores por defecto."""

    detection_confidence = serializers.FloatField(min_value=0, max_value=1)
    visual_condition_confidence = serializers.FloatField(min_value=0, max_value=1)
