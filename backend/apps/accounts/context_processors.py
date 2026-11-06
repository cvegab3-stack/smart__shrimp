"""Datos de cuenta disponibles en todas las plantillas."""

from django.conf import settings
from django.contrib.auth.password_validation import password_validators_help_texts


def account_settings(request):
    """Duración de la sesión (para el aviso de vencimiento) y reglas de contraseña vigentes."""
    return {
        "session_idle_seconds": settings.SESSION_COOKIE_AGE,
        "session_warning_seconds": settings.SESSION_WARNING_SECONDS,
        "password_min_length": settings.PASSWORD_MIN_LENGTH,
        "password_rules": password_validators_help_texts(),
    }
