"""Pruebas de componentes M3 sin afirmar exactitud de modelos no disponibles."""

import base64

import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.auth import require_service_token
from app.api.frame_routes import SessionStart, start_session
from app.api.http_routes import SummaryRequest, session_summary
from app.main import app
from app.pipeline.calibration import pixels_to_cm
from app.pipeline.counting_line import CountingLine
from app.pipeline.detector import DetectorUnavailable, YoloDetector
from app.pipeline.frame_pipeline import FramePipeline
from app.pipeline.tracker import IoUTracker
from app.pipeline.voting import FrameVoting
from app.session.session_registry import SessionRegistry
from app.session.session_state import VisionSession
from shrimp_contracts.token_claims import issue_service_token


def test_fastapi_registers_only_server_api_routes():
    paths = set(app.openapi()["paths"])
    assert "/v1/sessions" in paths
    assert "/v1/frames" in paths
    assert "/v1/sessions/summary" in paths
    assert "/v1/health" in paths


def test_calibrated_length_conversion():
    assert pixels_to_cm(250, 10, 500) == 5


def test_iou_tracker_keeps_identity_for_overlapping_frames():
    tracker = IoUTracker(threshold=0.3)
    first = tracker.update([{"bbox": (0, 0, 20, 10)}])[0]
    second = tracker.update([{"bbox": (2, 0, 22, 10)}])[0]
    assert first["track_id"] == second["track_id"]


def test_counting_line_counts_a_track_only_once():
    line = CountingLine(10)
    assert line.update("track-1", 8, 12) == 1
    assert line.update("track-1", 8, 12) == 1


def test_low_confidence_visual_vote_is_non_conclusive():
    voting = FrameVoting()
    voting.add("track-1", "visual_condition", "fresco", 0.4)
    assert voting.result("track-1", "visual_condition", 0.8) == ("no_concluyente", 0.4)


def test_session_registry_is_idempotent_for_analysis_and_attempt():
    registry = SessionRegistry()
    data = {"analysis_id": "a1", "attempt": 1, "calibration_version": 2}
    assert registry.start(data) is registry.start(data)


def test_detector_does_not_invent_when_weights_are_absent():
    with pytest.raises(DetectorUnavailable):
        YoloDetector().detect(np.zeros((10, 10, 3), dtype=np.uint8), 0.5)


def test_pipeline_counts_detections_without_color_model(monkeypatch):
    from types import SimpleNamespace

    pipeline = FramePipeline()
    pipeline.detector.detect = lambda image, confidence: [{
        "class_name": "camaron", "confidence": 0.95, "bbox": (1.0, 1.0, 6.0, 5.0),
    }]
    pipeline.color = SimpleNamespace(available=False)

    ok, encoded = cv2.imencode(".png", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    image_payload = base64.b64encode(encoded.tobytes()).decode()
    session = VisionSession("a1", 1, 1, detection_confidence=0.5, visual_condition_confidence=0.7)

    result = pipeline.process(session, "f1", image_payload)

    assert len(result["detections"]) == 1
    assert result["detections"][0]["visual_condition"] == "no_concluyente"
    assert result["detections"][0]["estimated_weight_g"] is None
    assert result["counters"]["detected"] == 1


def _blank_frame() -> str:
    ok, encoded = cv2.imencode(".png", np.zeros((100, 100, 3), dtype=np.uint8))
    assert ok
    return base64.b64encode(encoded.tobytes()).decode()


def _pipeline_returning(bbox) -> FramePipeline:
    from types import SimpleNamespace

    pipeline = FramePipeline()
    pipeline.detector.detect = lambda image, confidence: [{"class_name": "camaron", "confidence": 0.9, "bbox": bbox}]
    pipeline.color = SimpleNamespace(available=False)
    return pipeline


def test_video_track_is_registered_only_after_minimum_frames():
    pipeline = _pipeline_returning((10.0, 10.0, 40.0, 30.0))
    session = SessionRegistry().start({"analysis_id": "v1", "attempt": 1, "calibration_version": 1, "source": "video"})
    frame = _blank_frame()
    results = [pipeline.process(session, f"f{i}", frame) for i in range(session.min_track_hits)]
    assert all(not result["detections"] for result in results[:-1])
    assert len(results[-1]["detections"]) == 1
    assert len(session.detections) == 1


def test_oversized_box_is_rejected_not_counted():
    pipeline = _pipeline_returning((0.0, 0.0, 100.0, 90.0))
    session = VisionSession("a2", 1, 1, detection_confidence=0.5, visual_condition_confidence=0.7)
    result = pipeline.process(session, "f1", _blank_frame())
    assert result["detections"] == []
    assert session.rejected_count == 1


def test_auth_dependency_rejects_missing_service_token():
    with pytest.raises(HTTPException) as error:
        require_service_token(None)
    assert error.value.status_code == 401


def test_auth_dependency_accepts_django_token_and_summary_is_empty(monkeypatch):
    import app.api.auth as auth_module
    from app.session.session_registry import session_registry

    monkeypatch.setattr(auth_module, "VISION_SERVICE_TOKEN_SECRET", "test-secret")
    session_registry.reset()
    token = issue_service_token("test-secret", "django")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    assert require_service_token(credentials) == "django"
    started = start_session(SessionStart(
        analysis_id="a1", attempt=1, calibration_version=1,
        detection_confidence=0.5, visual_condition_confidence=0.5,
    ))
    summary = session_summary(SummaryRequest(analysis_id="a1", attempt=1))
    assert started["status"] == "en_curso"
    assert summary["shrimp_count"] == 0
    assert summary["model_mode"] == "inference"
