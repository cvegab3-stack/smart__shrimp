"""Ajustes de producción con controles seguros habilitados."""

import os

from .base import *  # noqa: F403

DEBUG = False
if not os.getenv("DJANGO_SECRET_KEY"):
    raise RuntimeError("Configure DJANGO_SECRET_KEY en el entorno de producción.")
if not os.getenv("DJANGO_ALLOWED_HOSTS", "").strip():
    raise RuntimeError("Configure DJANGO_ALLOWED_HOSTS en producción.")

# DJANGO_HTTPS=1 (por defecto): el sitio se sirve por HTTPS (nginx con certificado delante). Cookies solo por HTTPS
# y redirección de HTTP a HTTPS. DJANGO_HTTPS=0 solo para probar en una red local por HTTP: con cookies "Secure" el
# navegador no las enviaría por HTTP y no se podría iniciar sesión.
HTTPS = os.getenv("DJANGO_HTTPS", "1").lower() in {"1", "true", "yes"}
SESSION_COOKIE_SECURE = HTTPS
CSRF_COOKIE_SECURE = HTTPS
SECURE_SSL_REDIRECT = HTTPS
# /healthz/ lo consulta Docker desde dentro del contenedor, por HTTP: no se redirige.
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
