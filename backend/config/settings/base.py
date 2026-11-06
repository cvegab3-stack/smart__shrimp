"""Configuración común de Django basada en variables de entorno."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "insecure-local-development-key")
DEBUG = os.getenv("DJANGO_DEBUG", "0").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
# Orígenes extra para CSRF, p. ej. "https://smartshrimp.example.com" detrás de un proxy que cambie el puerto.
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "rest_framework", "apps.accounts", "apps.analysis", "apps.results",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "apps.accounts.context_processors.account_settings",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.getenv("POSTGRES_DB", "smart_shrimp"),
    "USER": os.getenv("POSTGRES_USER", "smart_shrimp"),
    "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
    "HOST": os.getenv("POSTGRES_HOST", "localhost"),
    "PORT": os.getenv("POSTGRES_PORT", "5432"),
    "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
}}
# Reglas de contraseña: longitud mínima (por defecto 8), no parecerse a los datos de la cuenta, no ser común y no
# ser solo números. Se aplican al crear cuentas, al asignarlas el administrador y al cambiarlas el usuario.
PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": PASSWORD_MIN_LENGTH}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "es-ec"
TIME_ZONE = "America/Guayaquil"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
# La sesión vence tras SESSION_IDLE_MINUTES sin peticiones (cada petición la renueva) o al cerrar el navegador.
# La página avisa SESSION_WARNING_SECONDS antes y, al vencer, lleva al acceso (static/js/session_timeout.js).
SESSION_COOKIE_AGE = int(os.getenv("SESSION_IDLE_MINUTES", "30")) * 60
SESSION_WARNING_SECONDS = int(os.getenv("SESSION_WARNING_SECONDS", "120"))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    # Sin sesión la API responde 401 (no 403), para que la página distinga "sesión vencida" de "sin permiso".
    "EXCEPTION_HANDLER": "apps.accounts.api.exceptions.exception_handler",
}
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/accounts/login/"
VISION_SERVICE_URL = os.getenv("VISION_SERVICE_URL", "http://vision:8001")
VISION_SERVICE_TOKEN_SECRET = os.getenv("VISION_SERVICE_TOKEN_SECRET", "")
VISION_TIMEOUT_SECONDS = float(os.getenv("VISION_TIMEOUT_SECONDS", "5"))
# Una imagen suelta (y el resumen final) puede tardar más que un fotograma de video, sobre todo en CPU.
VISION_IMAGE_TIMEOUT_SECONDS = float(os.getenv("VISION_IMAGE_TIMEOUT_SECONDS", "15"))
VISION_MAX_RETRIES = int(os.getenv("VISION_MAX_RETRIES", "1"))
# Flujo de análisis. Imagen enviada: como máximo ANALYSIS_MAX_IMAGE_MB ya convertida a JPEG (en base64 ocupa ~4/3)
# y al menos ANALYSIS_MIN_IMAGE_SIDE px por lado. El cuerpo admitido coincide con client_max_body_size de nginx.
ANALYSIS_MAX_IMAGE_MB = float(os.getenv("ANALYSIS_MAX_IMAGE_MB", "12"))
ANALYSIS_MIN_IMAGE_SIDE = int(os.getenv("ANALYSIS_MIN_IMAGE_SIDE", "240"))
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
# Un análisis en curso sin actividad durante estos minutos se considera interrumpido y se puede reintentar.
ANALYSIS_IDLE_MINUTES = int(os.getenv("ANALYSIS_IDLE_MINUTES", "15"))
