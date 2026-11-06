"""Contratos compartidos del sistema SMART SHRIMP."""

from .catalog import classes_for, load_catalog
from .frame_messages import Detection, FrameRequest, FrameResponse
from .session_summary import SessionSummary, ShrimpResult
from .token_claims import ServiceTokenClaims, issue_service_token, verify_service_token

__all__ = [
    "Detection", "FrameRequest", "FrameResponse", "ServiceTokenClaims",
    "SessionSummary", "ShrimpResult", "classes_for", "issue_service_token",
    "load_catalog", "verify_service_token",
]
