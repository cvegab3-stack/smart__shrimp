"""Modelos de análisis, calibración versionada y umbrales explícitos."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.accounts.models import User


def _num(value: float) -> str:
    """Número corto con coma decimal: 8.0 → "8", 8.5 → "8,5", 133.333 → "133,33"."""
    return f"{round(float(value), 2):g}".replace(".", ",")


class Calibration(models.Model):
    """Versión inmutable de la referencia física y rangos de tamaño."""

    version = models.PositiveIntegerField(unique=True)
    reference_length_cm = models.FloatField()
    reference_pixels = models.PositiveIntegerField()
    size_ranges = models.JSONField()
    is_active = models.BooleanField(default=True)
    created_by_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    # Histórico: versiones creadas como copia de otra cuando "Usar esta versión" copiaba en vez de activar.
    # Ya no se rellena (ahora se activa la misma versión), pero se conserva para no perder ese dato.
    based_on_version = models.PositiveIntegerField(null=True, blank=True)
    # Resolución de la imagen en la que se midió la referencia (herramienta 📏). Los píxeles solo equivalen a los
    # mismos cm en imágenes de esa misma resolución; si se escribieron a mano, se desconoce (None).
    image_width = models.PositiveIntegerField(null=True, blank=True)
    image_height = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ("-version",)
        constraints = [models.UniqueConstraint(fields=("is_active",), condition=Q(is_active=True), name="one_active_calibration")]

    @property
    def resolution(self) -> str | None:
        return f"{self.image_width} × {self.image_height} px" if self.image_width and self.image_height else None

    def clean(self):
        errors = {}
        if self.reference_length_cm <= 0:
            errors["reference_length_cm"] = "La medida de referencia debe ser positiva."
        if self.reference_pixels < self.MIN_REFERENCE_PIXELS:
            errors["reference_pixels"] = (
                f"La referencia debe ocupar al menos {self.MIN_REFERENCE_PIXELS} px en la imagen: con menos, un error "
                "de 1 px al medirla cambia todas las longitudes más de un 5 %. Use un objeto más largo o acerque la cámara.")
        range_errors = self._size_range_errors()
        if range_errors:
            errors["size_ranges"] = range_errors
        if errors:
            raise ValidationError(errors)

    SIZE_CATEGORIES = (("pequeno", "Pequeño"), ("mediano", "Mediano"), ("grande", "Grande"))
    # Lógica de la escala (cm ↔ px). Mismos valores en static/js/calibration.js.
    MIN_REFERENCE_PIXELS = 20                    # obligatorio: error de 1 px ≤ 5 %
    PLAUSIBLE_PX_PER_CM = (5, 500)               # aviso: fuera de esto la imagen abarcaría >3,8 m o <4 cm (a 1920 px)

    @property
    def pixels_per_cm(self) -> float:
        return self.reference_pixels / self.reference_length_cm

    @property
    def scale_warning(self) -> str | None:
        """Aviso (no bloquea) si la escala no es verosímil para fotografiar camarones."""
        low, high = self.PLAUSIBLE_PX_PER_CM
        if self.reference_pixels < self.MIN_REFERENCE_PIXELS:
            return (f"La referencia ocupa solo {self.reference_pixels} px: las longitudes calculadas no serán fiables. "
                    "Registre una nueva calibración midiendo la regla en una foto de la cámara.")
        if not low <= self.pixels_per_cm <= high:
            return (f"Escala poco realista ({_num(self.pixels_per_cm)} px por cm). Revise que la medida en píxeles "
                    "corresponda a la regla en una foto de esta cámara.")
        return None

    @property
    def reuse_error(self) -> str | None:
        """Motivo por el que esta versión no puede volver a usarse con las reglas actuales (None = se puede)."""
        try:
            self.clean()
        except ValidationError as error:
            return " ".join(sum(error.message_dict.values(), []))
        return None

    @property
    def size_bands(self) -> list[dict]:
        """Rangos en orden pequeño → grande con nombre visible y texto claro ("hasta 8 cm", "8 – 13 cm")."""
        bands = []
        for key, name in self.SIZE_CATEGORIES:
            item = (self.size_ranges or {}).get(key) or {}
            low, high = item.get("min_cm"), item.get("max_cm")
            if low is None and high is None:
                text = "Cualquier medida"
            elif low is None:
                text = f"hasta {_num(high)} cm"
            elif high is None:
                text = f"desde {_num(low)} cm"
            else:
                text = f"{_num(low)} – {_num(high)} cm"
            bands.append({"key": key, "name": name, "text": text})
        return bands

    def _size_range_errors(self) -> list[str]:
        """Rangos lógicos: sin negativos, mínimo < máximo, sin solaparse y en orden pequeño < mediano < grande.

        Los límites son opcionales (None = sin límite), p. ej. pequeño sin mínimo o grande sin máximo.
        Dos rangos seguidos pueden compartir el límite (pequeño hasta 8, mediano desde 8): esa medida cuenta en la
        categoría menor (ver vision_service/app/pipeline/measurement.py).
        """
        expected = [key for key, _ in self.SIZE_CATEGORIES]
        if not isinstance(self.size_ranges, dict) or set(self.size_ranges) != set(expected):
            return ["Defina rangos para pequeño, mediano y grande."]
        problems, bounds = [], []
        for key, name in self.SIZE_CATEGORIES:
            item = self.size_ranges[key]
            try:
                lower, upper = (None if item.get(k) is None else float(item.get(k)) for k in ("min_cm", "max_cm"))
            except (AttributeError, TypeError, ValueError):
                problems.append(f"{name}: los límites deben ser números.")
                continue
            if lower is not None and lower < 0:
                problems.append(f"{name}: el mínimo no puede ser negativo.")
            if upper is not None and upper <= 0:
                problems.append(f"{name}: el máximo debe ser mayor que 0.")
            if lower is not None and upper is not None and lower >= upper:
                problems.append(f"{name}: el mínimo debe ser menor que el máximo.")
            bounds.append((name, float("-inf") if lower is None else lower, float("inf") if upper is None else upper))
        if problems or len(bounds) != len(expected):
            return problems
        for (left, left_min, left_max), (right, right_min, right_max) in zip(bounds, bounds[1:]):
            if max(left_min, right_min) < min(left_max, right_max):  # tocarse en el límite no es solaparse
                problems.append(f"Los rangos de {left.lower()} y {right.lower()} se superponen.")
            elif left_min > right_min:
                problems.append(f"El rango de {left.lower()} debe ser menor que el de {right.lower()}.")
        # Si pequeño < mediano < grande sin solaparse de dos en dos, pequeño y grande tampoco pueden solaparse.
        return problems

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
    # Última petición del operador sobre este análisis (crear, fotograma, reintento). Si un análisis en curso pasa
    # ANALYSIS_IDLE_MINUTES sin actividad, se considera interrumpido (session_service.expire_stale_analyses).
    last_activity_at = models.DateTimeField(null=True, blank=True)

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
    # Imagen analizada (relativa a MEDIA_ROOT) y los recuadros detectados en ella, para mostrarla en el detalle.
    # Imagen: la foto adjuntada. Video: el último fotograma con camarones (guardado como máximo 1 vez por segundo).
    snapshot_path = models.CharField(max_length=255, blank=True)
    snapshot_detections = models.JSONField(default=list, blank=True)
    # Fotogramas que el servicio procesó en este intento: no se finaliza un intento sin al menos uno.
    frames_processed = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("analysis", "attempt_number"), name="unique_analysis_attempt")]
