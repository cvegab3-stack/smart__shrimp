"""Ajustes de producción con controles seguros habilitados."""

import os

from .base import *  # noqa: F403

DEBUG = False
if not os.getenv("DJANGO_SECRET_KEY"):
    raise RuntimeError("Configure DJANGO_SECRET_KEY en el entorno de producción.")
if not os.getenv("DJANGO_ALLOWED_HOSTS", "").strip():
    raise RuntimeError("Configure DJANGO_ALLOWED_HOSTS en producción.")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
