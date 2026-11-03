"""Autenticación de solicitudes servidor a servidor emitidas por Django."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shrimp_contracts.token_claims import verify_service_token

from app.config import VISION_SERVICE_TOKEN_SECRET

bearer_scheme = HTTPBearer(auto_error=False)


def require_service_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> str:
    """Valida firma y claims del token de corta duración."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not VISION_SERVICE_TOKEN_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticación de servicio requerida.")
    try:
        claims = verify_service_token(credentials.credentials, VISION_SERVICE_TOKEN_SECRET)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de servicio no válido.") from exc
    return claims.subject
