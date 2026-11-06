"""Configuración sencilla para desarrollo local en Windows (SQLite)."""

import os

from .base import *  # noqa: F403

DEBUG = True
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "local.sqlite3"}}  # noqa: F405
VISION_SERVICE_URL = os.getenv("VISION_SERVICE_URL", "http://127.0.0.1:8001")
