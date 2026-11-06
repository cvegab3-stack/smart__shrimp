"""Único cliente backend autorizado para comunicarse con M3.

Clasifica cada fallo con un código del catálogo (apps/analysis/errors.py) y solo repite automáticamente lo que
puede salir bien al repetirlo (red caída, tiempo agotado, error 5xx). Un 4xx no se repite: la misma petición
volvería a fallar igual.
"""

import time
from typing import Any

import requests
from django.conf import settings

from shrimp_contracts.token_claims import issue_service_token


class VisionServiceError(RuntimeError):
    """Fallo del servicio de visión, con el código del catálogo que lo describe.

    El mensaje es técnico (para auditoría); el texto que ve cada persona sale del catálogo según `code`.
    """

    def __init__(self, message: str = "", *, code: str = "vision_unavailable", status: int | None = None):
        super().__init__(message or code)
        self.code = code
        self.status = status


def _code_for_status(status: int) -> str:
    if status == 422:
        return "invalid_image"  # el servicio no pudo decodificar la imagen: es un problema del archivo
    if status in (404, 409):
        return "vision_session_lost"  # el servicio no tiene (o tiene otra) sesión de este intento: se reinició
    if status >= 500:
        return "vision_unavailable"
    return "vision_misconfigured"  # 400/401/403: contrato o secreto distintos entre Django y el servicio


def _detail(response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]
    return str(data.get("detail", data))[:300] if isinstance(data, dict) else str(data)[:300]


def _post(path: str, payload: dict[str, Any], *, timeout: float | None = None,
          retries: int | None = None) -> dict[str, Any]:
    """Envía una petición autenticada con límite de tiempo y reintento acotado de los fallos transitorios."""
    secret = settings.VISION_SERVICE_TOKEN_SECRET
    if not secret:
        raise VisionServiceError("No está configurado el secreto del servicio de visión.", code="vision_misconfigured")
    token = issue_service_token(secret, "django")
    timeout = float(timeout if timeout is not None else getattr(settings, "VISION_TIMEOUT_SECONDS", 5))
    retries = int(retries if retries is not None else getattr(settings, "VISION_MAX_RETRIES", 1))
    last_error: VisionServiceError | None = None
    for retry in range(retries + 1):
        try:
            response = requests.post(
                f"{settings.VISION_SERVICE_URL.rstrip('/')}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_error = VisionServiceError(f"{type(exc).__name__}: {exc}", code="vision_unavailable")
        else:
            if response.status_code >= 400:
                code = _code_for_status(response.status_code)
                error = VisionServiceError(f"HTTP {response.status_code}: {_detail(response)}", code=code,
                                           status=response.status_code)
                if code != "vision_unavailable":
                    raise error  # 4xx: repetir la misma petición no cambia el resultado
                last_error = error
            else:
                try:
                    result = response.json()
                except ValueError:
                    result = None
                if isinstance(result, dict):
                    return result
                raise VisionServiceError("Respuesta que no es un objeto JSON.", code="vision_invalid_response")
        if retry < retries:
            time.sleep(min(0.1 * (retry + 1), 0.5))
    raise last_error


def start_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Abre una sesión de procesamiento en M3."""
    return _post("/v1/sessions", payload)


def process_frame(payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
    """Envía un fotograma a M3 y devuelve sus detecciones (una imagen suelta admite más tiempo que el video)."""
    return _post("/v1/frames", payload, timeout=timeout)


def get_session_summary(analysis_id: str, attempt: int) -> dict[str, Any]:
    """Solicita el resumen final de la sesión a M3."""
    return _post("/v1/sessions/summary", {"analysis_id": analysis_id, "attempt": attempt},
                 timeout=getattr(settings, "VISION_IMAGE_TIMEOUT_SECONDS", None))


def health(timeout: float = 2.0) -> bool:
    """Indica si el servicio responde (para el panel del administrador). Nunca lanza."""
    secret = settings.VISION_SERVICE_TOKEN_SECRET
    if not secret:
        return False
    try:
        response = requests.get(
            f"{settings.VISION_SERVICE_URL.rstrip('/')}/v1/health",
            headers={"Authorization": f"Bearer {issue_service_token(secret, 'django')}"}, timeout=timeout,
        )
        return response.status_code == 200
    except requests.RequestException:
        return False
