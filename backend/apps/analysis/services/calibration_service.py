"""Casos de uso para crear y consultar calibraciones versionadas."""

from django.db import transaction

from apps.accounts.services import record_event
from apps.analysis.models import Calibration


@transaction.atomic
def create_calibration(*, reference_length_cm: float, reference_pixels: int, size_ranges: dict, actor, ip_address: str | None = None) -> Calibration:
    """Crea la versión siguiente sin modificar calibraciones históricas."""
    current_version = Calibration.objects.select_for_update().order_by("-version").values_list("version", flat=True).first() or 0
    Calibration.objects.filter(is_active=True).update(is_active=False)
    calibration = Calibration(
        version=current_version + 1,
        reference_length_cm=reference_length_cm,
        reference_pixels=reference_pixels,
        size_ranges=size_ranges,
        created_by_id=actor.pk,
    )
    calibration.full_clean()
    calibration.save()
    record_event("calibration.created", actor, {"calibration_version": calibration.version}, ip_address)
    return calibration


def get_active_calibration() -> Calibration:
    """Obtiene la calibración vigente o falla antes de iniciar mediciones."""
    calibration = Calibration.objects.filter(is_active=True).first()
    if calibration is None:
        raise ValueError("No existe una calibración vigente.")
    return calibration
