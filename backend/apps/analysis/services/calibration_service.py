"""Casos de uso para crear, activar y consultar calibraciones versionadas."""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.services import record_event
from apps.analysis.models import Calibration


def _same_values(calibration: Calibration, reference_length_cm: float, reference_pixels: int, size_ranges: dict,
                 image_width: int | None = None, image_height: int | None = None) -> bool:
    """Misma referencia, píxeles, rangos y resolución de medida (8 y 8.0 cuentan como iguales)."""
    def normalized(ranges):
        return {key: tuple(None if (value := (item or {}).get(bound)) is None else float(value)
                           for bound in ("min_cm", "max_cm"))
                for key, item in (ranges or {}).items()}
    return (float(calibration.reference_length_cm) == float(reference_length_cm)
            and int(calibration.reference_pixels) == int(reference_pixels)
            and normalized(calibration.size_ranges) == normalized(size_ranges)
            and (calibration.image_width, calibration.image_height) == (image_width, image_height))


@transaction.atomic
def create_calibration(*, reference_length_cm: float, reference_pixels: int, size_ranges: dict, actor, ip_address: str | None = None,
                       image_width: int | None = None, image_height: int | None = None) -> Calibration:
    """Crea la versión siguiente y la pone en uso, sin modificar calibraciones históricas.

    Si ya existe una versión con exactamente los mismos valores no se duplica: se indica cuál es, para usarla
    desde el historial.
    """
    existing = list(Calibration.objects.select_for_update().order_by("-version"))
    duplicate = next((c for c in existing if _same_values(c, reference_length_cm, reference_pixels, size_ranges,
                                                          image_width, image_height)), None)
    if duplicate is not None:
        raise ValidationError(
            f"Estos valores ya están en uso (versión {duplicate.version})." if duplicate.is_active else
            f"Estos valores son iguales a los de la versión {duplicate.version}. Úsala desde el historial.")
    current_version = existing[0].version if existing else 0
    Calibration.objects.filter(is_active=True).update(is_active=False)
    calibration = Calibration(
        version=current_version + 1,
        reference_length_cm=reference_length_cm,
        reference_pixels=reference_pixels,
        size_ranges=size_ranges,
        created_by_id=actor.pk,
        image_width=image_width,
        image_height=image_height,
    )
    calibration.full_clean()
    calibration.save()
    record_event("calibration.created", actor, {"calibration_version": calibration.version}, ip_address)
    return calibration


@transaction.atomic
def activate_calibration(version: int, *, actor, ip_address: str | None = None) -> Calibration:
    """Pone en uso una versión anterior del historial (la misma versión, sin copiarla).

    Solo cambia cuál está vigente: sus valores no se tocan y cada análisis conserva la versión con la que se
    midió. La bitácora registra qué versión se activó y cuál estaba antes. Una versión que no cumple las reglas
    actuales (p. ej. referencia de menos de 20 px) no se activa.
    """
    target = Calibration.objects.select_for_update().filter(version=version).first()
    if target is None:
        raise ValueError(f"No existe la calibración versión {version}.")
    if target.is_active:
        raise ValueError(f"La versión {version} ya está en uso.")
    if target.reuse_error:
        raise ValidationError(target.reuse_error)
    previous = Calibration.objects.filter(is_active=True).values_list("version", flat=True).first()
    # Primero se desactiva la vigente: la base de datos solo admite una activa a la vez.
    Calibration.objects.filter(is_active=True).update(is_active=False)
    Calibration.objects.filter(pk=target.pk).update(is_active=True)
    record_event("calibration.activated", actor, {"calibration_version": version, "previous_version": previous}, ip_address)
    target.refresh_from_db()
    return target


def get_active_calibration() -> Calibration:
    """Obtiene la calibración vigente o falla antes de iniciar mediciones."""
    calibration = Calibration.objects.filter(is_active=True).first()
    if calibration is None:
        raise ValueError("No existe una calibración vigente.")
    return calibration
