"""Emisión y validación de tokens HMAC de servicio entre Django y M3."""

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

ISSUER = "smart-shrimp-django"
AUDIENCE = "smart-shrimp-vision"
MAX_TTL_SECONDS = 300


@dataclass(frozen=True, slots=True)
class ServiceTokenClaims:
    """Claims mínimos de autenticación servidor a servidor."""

    subject: str
    issued_at: int
    expires_at: int
    token_id: str
    issuer: str = ISSUER
    audience: str = AUDIENCE


def issue_service_token(secret: str, subject: str, ttl_seconds: int = 120) -> str:
    """Emite un token firmado, con vigencia limitada a cinco minutos."""
    if not secret:
        raise ValueError("La clave del token de servicio no puede estar vacía.")
    if not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"La vigencia debe estar entre 1 y {MAX_TTL_SECONDS} segundos.")
    now = int(time.time())
    claims = ServiceTokenClaims(subject, now, now + ttl_seconds, str(uuid.uuid4()))
    payload = base64.urlsafe_b64encode(json.dumps(asdict(claims), separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return payload.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def verify_service_token(token: str, secret: str, now: int | None = None) -> ServiceTokenClaims:
    """Verifica firma, emisor, audiencia y expiración de un token."""
    try:
        payload_part, signature_part = token.split(".", maxsplit=1)
        supplied = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
        expected = hmac.new(secret.encode(), payload_part.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected):
            raise ValueError("Firma de token inválida.")
        payload = base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4))
        claims: dict[str, Any] = json.loads(payload)
        result = ServiceTokenClaims(
            subject=claims["subject"], issued_at=int(claims["issued_at"]),
            expires_at=int(claims["expires_at"]), token_id=claims["token_id"],
            issuer=claims["issuer"], audience=claims["audience"],
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Token de servicio inválido.") from exc
    current_time = int(time.time()) if now is None else now
    if result.issuer != ISSUER or result.audience != AUDIENCE:
        raise ValueError("Emisor o audiencia de token incorrectos.")
    if result.issued_at > current_time or result.expires_at <= current_time:
        raise ValueError("Token de servicio expirado o aún no vigente.")
    if result.expires_at - result.issued_at > MAX_TTL_SECONDS:
        raise ValueError("La vigencia del token supera el máximo permitido.")
    return result
