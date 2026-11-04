"""Casos de uso de umbrales explícitos, sin valores de modelo inventados."""

from apps.analysis.models import ThresholdProfile
from apps.accounts.services import record_event


def create_threshold_profile(*, detection_confidence: float, visual_condition_confidence: float, actor) -> ThresholdProfile:
    """Registra umbrales dentro del intervalo de confianza permitido."""
    profile = ThresholdProfile(
        detection_confidence=detection_confidence,
        visual_condition_confidence=visual_condition_confidence,
        created_by_id=actor.pk,
    )
    profile.full_clean()
    profile.save()
    record_event("thresholds.created", actor, {"threshold_profile_id": profile.pk})
    return profile


def get_current_threshold_profile() -> ThresholdProfile:
    """Devuelve la última versión configurada de los umbrales."""
    profile = ThresholdProfile.objects.first()
    if profile is None:
        raise ValueError("No hay umbrales de confianza configurados.")
    return profile
