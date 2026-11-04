"""Resultados persistidos por ejemplar e informes consolidados."""

import uuid

from django.db import models

from apps.analysis.models import AnalysisSession


class ShrimpRecordQuerySet(models.QuerySet):
    """Consultas de resultados por ejemplar."""

    def of_current_attempt(self, analysis: AnalysisSession):
        """Resultados vigentes del análisis: los del último intento, no los de intentos fallidos."""
        return self.filter(analysis=analysis, attempt=analysis.current_attempt)


class ShrimpRecord(models.Model):
    """Resultado de un track; los grupos de clasificación permanecen separados."""

    analysis = models.ForeignKey(AnalysisSession, on_delete=models.CASCADE, related_name="shrimp_records")
    attempt = models.PositiveIntegerField()
    track_id = models.CharField(max_length=100)
    confidence = models.FloatField(null=True, blank=True)
    integrity = models.CharField(max_length=24, null=True, blank=True)
    presentation = models.CharField(max_length=24, null=True, blank=True)
    visual_condition = models.CharField(max_length=24)
    visual_condition_confidence = models.FloatField(null=True, blank=True)
    length_cm = models.FloatField(null=True, blank=True)
    size_category = models.CharField(max_length=16, null=True, blank=True)
    estimated_weight_g = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ShrimpRecordQuerySet.as_manager()

    class Meta:
        ordering = ("track_id",)
        constraints = [models.UniqueConstraint(fields=("analysis", "attempt", "track_id"), name="unique_shrimp_track_per_attempt")]


class ProductionReport(models.Model):
    """Copia trazable de un consolidado generado por un supervisor."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by_id = models.PositiveBigIntegerField()
    date_from = models.DateField()
    date_to = models.DateField()
    summary = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
