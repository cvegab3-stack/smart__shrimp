"""Crea umbrales iniciales para que una instalación nueva pueda analizar sin configuración previa."""

from django.db import migrations

DEFAULT_DETECTION_CONFIDENCE = 0.5
DEFAULT_VISUAL_CONDITION_CONFIDENCE = 0.5


def create_default_threshold_profile(apps, schema_editor):
    ThresholdProfile = apps.get_model("analysis", "ThresholdProfile")
    if not ThresholdProfile.objects.exists():
        # created_by_id=0: creado por el sistema; el administrador puede registrar otra versión.
        ThresholdProfile.objects.create(
            detection_confidence=DEFAULT_DETECTION_CONFIDENCE,
            visual_condition_confidence=DEFAULT_VISUAL_CONDITION_CONFIDENCE,
            created_by_id=0,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("analysis", "0002_analysissession_model_mode_and_more"),
    ]

    operations = [
        migrations.RunPython(create_default_threshold_profile, migrations.RunPython.noop),
    ]
