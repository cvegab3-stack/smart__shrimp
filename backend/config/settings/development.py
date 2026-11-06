"""Ajustes de desarrollo; no usar en producción."""

from .base import *  # noqa: F403

DEBUG = True
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
