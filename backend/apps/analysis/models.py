"""Modelos de análisis, calibración versionada y umbrales explícitos."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.accounts.models import User


class Calibration(models.Model):
    """Versión inmutable de la referencia física y rangos de tamaño."""

    version = models.PositiveIntegerField(unique=True)
    reference_length_cm = models.FloatField()
    reference_pixels = models.PositiveIntegerField()
    size_ranges = models.JSONField()
    is_active = models.BooleanField(default=True)
    created_by_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-version",)
        constraints = [models.UniqueConstraint(fields=("is_active",), condition=Q(is_active=True), name="one_active_calibration")]

    def clean(self):
        errors = {}
        if self.reference_length_cm <= 0:
            errors["reference_length_cm"] = "La medida de referencia debe ser positiva."
        if self.reference_pixels <= 0:
            errors["reference_pixels"] = "La longitud en píxeles debe ser positiva."
        expected = ("pequeno", "mediano", "grande")
        if not isinstance(self.size_ranges, dict) or set(self.size_ranges) != set(expected):
            errors["size_ranges"] = "Defina rangos para pequeno, mediano y grande."
        else:
            normalized = []
            for category in expected:
                item = self.size_ranges[category]
                try:
                    lower, upper = item.get("min_cm"), item.get("max_cm")
                    if lower is not None and float(lower) < 0:
                        raise ValueError
                    if upper is not None and float(upper) <= 0:
                        raise ValueError
                    if lower is not None and upper is not None and float(lower) >= float(upper):
                        raise ValueError
                    normalized.append((category, float(lower) if lower is not None else float("-inf"), float(upper) if upper is not None else float("inf")))
                except (AttributeError, TypeError, ValueError):
                    errors["size_ranges"] = f"Rango inválido para {category}."
            for index, (left_name, left_min, left_max) in enumerate(normalized):
                for right_name, right_min, right_max in normalized[index + 1:]:
                    if max(left_min, right_min) <= min(left_max, right_max):
                        errors["size_ranges"] = f"Los rangos de {left_name} y {right_name} se superponen."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and Calibration.objects.filter(pk=self.pk).exists():
            raise ValidationError("Las calibraciones versionadas no se sobrescriben.")
        self.full_clean()
        super().save(*args, **kwargs)


class ThresholdProfile(models.Model):
    """Umbrales de confianza requeridos para iniciar procesamiento."""

    detection_confidence = models.FloatField()
    visual_condition_confidence = models.FloatField()
    created_by_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")

    def clean(self):
        errors = {}
        for field in ("detection_confidence", "visual_condition_confidence"):
            value = getattr(self, field)
            if not 0 <= value <= 1:
                errors[field] = "La confianza debe estar entre 0 y 1."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class AnalysisSessionQuerySet(models.QuerySet):
    """Consultas de análisis según el rol de quien consulta."""

    def visible_to(self, user):
        """El operador solo ve sus propios análisis; los roles de consulta ven todos."""
        return self.filter(operator=user) if user.role == User.Role.OPERATOR else self


class AnalysisSession(models.Model):
    """Lote procesado por un operador con referencias de configuración congeladas."""

    class Status(models.TextChoices):
        IN_PROGRESS = "en_curso", "En curso"
        FINISHED = "finalizado", "Finalizado"
        ERROR = "con_error", "Con error"

    class Source(models.TextChoices):
        IMAGE = "imagen", "Imagen"
        VIDEO = "video", "Video"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_code = models.CharField(max_length=100)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="analysis_sessions")
    source = models.CharField(max_length=12, choices=Source.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS, db_index=True)
    calibration = models.ForeignKey(Calibration, on_delete=models.PROTECT, related_name="analysis_sessions")
    threshold_profile = models.ForeignKey(ThresholdProfile, on_delete=models.PROTECT, related_name="analysis_sessions")
    current_attempt = models.PositiveIntegerField(default=1)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    model_mode = models.CharField(max_length=24, blank=True)
    model_status = models.CharField(max_length=80, blank=True)
    shrimp_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = AnalysisSessionQuerySet.as_manager()


class ProcessingAttempt(models.Model):
    """Clave de idempotencia para evitar duplicar reintentos."""

    analysis = models.ForeignKey(AnalysisSession, on_delete=models.CASCADE, related_name="attempts")
    attempt_number = models.PositiveIntegerField()
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=16, choices=AnalysisSession.Status.choices, default=AnalysisSession.Status.IN_PROGRESS)
    error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("analysis", "attempt_number"), name="unique_analysis_attempt")]
