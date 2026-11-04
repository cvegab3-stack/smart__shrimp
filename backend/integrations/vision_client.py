"""Único cliente backend autorizado para comunicarse con M3."""

import time
from typing import Any

import requests
from django.conf import settings

from shrimp_contracts.token_claims import issue_service_token


class VisionServiceError(RuntimeError):
    """Error de transporte o respuesta no válida del servicio de visión."""


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Envía una petición autenticada con límite de tiempo y reintento acotado."""
    secret = settings.VISION_SERVICE_TOKEN_SECRET
    if not secret:
        raise VisionServiceError("No está configurado el secreto del servicio de visión.")
    token = issue_service_token(secret, "django")
    timeout = float(getattr(settings, "VISION_TIMEOUT_SECONDS", 5))
    retries = int(getattr(settings, "VISION_MAX_RETRIES", 1))
    last_error: Exception | None = None
    for retry in range(retries + 1):
        try:
            response = requests.post(
                f"{settings.VISION_SERVICE_URL.rstrip('/')}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise VisionServiceError("M3 devolvió una respuesta no válida.")
            return result
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if retry < retries:
                time.sleep(min(0.1 * (retry + 1), 0.5))
    raise VisionServiceError("El servicio de visión no respondió después de los reintentos configurados.") from last_error


def start_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Abre una sesión de procesamiento en M3."""
    return _post("/v1/sessions", payload)


def process_frame(payload: dict[str, Any]) -> dict[str, Any]:
    """Envía un fotograma a M3 y devuelve sus detecciones."""
    return _post("/v1/frames", payload)


def get_session_summary(analysis_id: str, attempt: int) -> dict[str, Any]:
    """Solicita el resumen final de la sesión a M3."""
    return _post("/v1/sessions/summary", {"analysis_id": analysis_id, "attempt": attempt})
