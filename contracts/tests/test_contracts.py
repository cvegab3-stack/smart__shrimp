"""Pruebas unitarias de los contratos compartidos."""

from datetime import datetime, timezone

import pytest

from shrimp_contracts import (
    Detection,
    FrameRequest,
    FrameResponse,
    SessionSummary,
    ShrimpResult,
    classes_for,
    issue_service_token,
    load_catalog,
    verify_service_token,
)


def test_catalog_keeps_visual_condition_separate() -> None:
    catalog = load_catalog()
    assert classes_for("condicion_visual") == (
        "fresco", "intermedio", "deteriorado", "no_concluyente"
    )
    assert "pelado" not in classes_for("condicion_visual")
    assert "no_concluyente" not in catalog["reglas"]["condicion_visual_entrenable"]


def test_frame_messages_serialize_timestamps_and_detections() -> None:
    request = FrameRequest("analysis-1", 1, "frame-1", datetime.now(timezone.utc), "abc", 2)
    assert request.to_dict()["captured_at"].endswith("+00:00")
    response = FrameResponse("analysis-1", 1, "frame-1", (Detection("track-1", 0.98, (1, 2, 3, 4)),), {"count": 1})
    assert response.to_dict()["detections"][0]["track_id"] == "track-1"


def test_summary_has_per_class_totals() -> None:
    row = ShrimpResult("track-1", "completo", "pelado", "fresco", 0.95, 12.0, "mediano", 8.5)
    payload = SessionSummary("analysis-1", 1, (row,), 2).to_dict()
    assert payload["totals"]["integrity"] == {"completo": 1}
    assert payload["totals"]["visual_condition"] == {"fresco": 1}
    assert payload["totals"]["rejected"] == 2


def test_service_token_round_trip_and_expiration() -> None:
    token = issue_service_token("test-secret", "django", ttl_seconds=30)
    claims = verify_service_token(token, "test-secret", now=int(datetime.now(timezone.utc).timestamp()))
    assert claims.subject == "django"
    with pytest.raises(ValueError, match="vigencia"):
        issue_service_token("test-secret", "django", ttl_seconds=301)
    with pytest.raises(ValueError, match="inválido"):
        verify_service_token(token, "wrong-secret")
