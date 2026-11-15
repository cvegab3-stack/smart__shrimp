"""Pruebas de benchmark_latencia.py y benchmark_fps.py contra un vision_service falso (sin modelo ni GPU).

El servidor falso valida el token HMAC real de shrimp_contracts y responde como la API de M3.
    python -m pytest scripts/tests
"""

from __future__ import annotations

import base64
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import benchmark_common as bc  # noqa: E402
import benchmark_fps  # noqa: E402
import benchmark_latencia  # noqa: E402
from shrimp_contracts.token_claims import verify_service_token  # noqa: E402

SECRET = "clave-de-prueba"


class FakeVision:
    """Estado del servidor falso: qué recibió y si debe fallar."""

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.frames: list[dict] = []
        self.summaries: list[str] = []
        self.client_ports: list[int] = []  # puerto de origen de cada petición: uno solo = conexión reutilizada
        self.fail_frames = False


def make_handler(state: FakeVision):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # admite keep-alive, como uvicorn

        def log_message(self, *args):  # silencio en la salida de pytest
            pass

        def parse_request(self):
            ok = super().parse_request()
            state.client_ports.append(self.client_address[1])
            return ok

        def _reply(self, code: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            try:
                verify_service_token(header.removeprefix("Bearer "), SECRET)
                return True
            except ValueError:
                self._reply(401, {"detail": "Token de servicio no válido."})
                return False

        def do_GET(self):
            if self._authorized() and self.path == "/v1/health":
                self._reply(200, {"status": "ok"})

        def do_POST(self):
            if not self._authorized():
                return
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/v1/sessions":
                state.sessions[payload["analysis_id"]] = payload
                self._reply(200, {"status": "en_curso"})
            elif self.path == "/v1/frames":
                if state.fail_frames:
                    self._reply(500, {"detail": "fallo simulado"})
                    return
                state.frames.append(payload)
                self._reply(200, {"detections": []})
            elif self.path == "/v1/sessions/summary":
                state.summaries.append(payload["analysis_id"])
                self._reply(200, {"shrimp_count": 0})
            else:
                self._reply(404, {"detail": "no existe"})

    return Handler


@pytest.fixture
def fake_service():
    state = FakeVision()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()
    server.server_close()


@pytest.fixture
def weights(tmp_path: Path) -> Path:
    path = tmp_path / "falso.pt"
    path.write_bytes(b"pesos falsos")
    return path


def write_images(folder: Path, count: int, size=(640, 480)) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for k in range(count):
        image = np.full((size[1], size[0], 3), 40 * (k + 1), dtype=np.uint8)
        cv2.imwrite(str(folder / f"foto_{k}.jpg"), image)
    return folder


def sent_size(frame_payload: dict) -> tuple[int, int]:
    image = cv2.imdecode(np.frombuffer(base64.b64decode(frame_payload["image_base64"]), np.uint8), cv2.IMREAD_COLOR)
    return image.shape[1], image.shape[0]


def only_report(folder: Path, prefix: str) -> dict:
    reports = list(folder.glob(f"{prefix}_*.json"))
    assert len(reports) == 1
    return json.loads(reports[0].read_text(encoding="utf-8"))


def common_args(fake, weights: Path, out: Path) -> list[str]:
    return ["--url", fake.url, "--secret", SECRET, "--weights", str(weights), "--out", str(out)]


# --- utilidades -------------------------------------------------------------------------------------------------

def test_percentile_matches_linear_interpolation():
    values = [float(v) for v in range(1, 11)]
    assert bc.percentile(values, 95) == pytest.approx(np.percentile(values, 95))
    assert bc.percentile(values, 50) == pytest.approx(5.5)
    assert bc.percentile([3.0], 95) == 3.0
    with pytest.raises(ValueError):
        bc.percentile([], 95)


def test_model_summary_reports_sha_and_missing_file(weights: Path, tmp_path: Path):
    import hashlib

    summary = bc.model_summary(weights)
    assert summary["sha256"] == hashlib.sha256(b"pesos falsos").hexdigest()
    assert summary["matches_model_info"] is False
    assert bc.model_summary(tmp_path / "no_existe.pt")["sha256"] is None


def test_client_rejected_with_wrong_secret(fake_service):
    wrong, right = bc.VisionClient(fake_service.url, "otra-clave"), bc.VisionClient(fake_service.url, SECRET)
    try:
        with pytest.raises(RuntimeError, match="HTTP 401"):
            wrong.health()
        assert right.health() == {"status": "ok"}
    finally:
        wrong.close()
        right.close()


def test_client_reuses_one_connection_like_django(fake_service, weights: Path, tmp_path: Path):
    benchmark_latencia.main([*common_args(fake_service, weights, tmp_path / "evidencia"), "--images",
                             str(write_images(tmp_path / "frames", 1)), "--n", "5", "--warmup", "1"])
    assert len(fake_service.client_ports) == 18  # 6 análisis × (sesión + fotograma + resumen)
    assert len(set(fake_service.client_ports)) == 1


def test_connection_error_is_an_oserror_for_the_benchmarks():
    client = bc.VisionClient("http://127.0.0.1:9", SECRET, timeout=2)  # puerto sin servicio
    try:
        with pytest.raises(OSError):
            client.health()
    finally:
        client.close()


def test_service_command_and_env_point_to_vision_service(weights: Path):
    command = bc.service_command(8099)
    assert command[1:4] == ["-m", "uvicorn", "app.main:app"]
    assert command[command.index("--port") + 1] == "8099"
    assert command[command.index("--timeout-keep-alive") + 1] == "30"  # igual que vision_service/Dockerfile
    env = bc.service_env(weights, "s")
    assert env["DETECTOR_WEIGHTS"] == str(weights) and env["VISION_SERVICE_TOKEN_SECRET"] == "s"
    assert "contracts" in env["PYTHONPATH"] and "vision_service" in env["PYTHONPATH"]


def test_without_images_uses_synthetic_frames(tmp_path: Path):
    frames, info = bc.load_image_frames(tmp_path / "vacia", (64, 36), 80, synthetic_count=3)
    assert len(frames) == 3 and info["synthetic"] is True and info["sent_size"] == "64x36"


def test_video_frames_are_read_and_resized(tmp_path: Path):
    video = tmp_path / "prueba.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
    if not writer.isOpened():
        pytest.skip("OpenCV de este equipo no puede escribir video MJPG")
    for k in range(6):
        writer.write(np.full((120, 160, 3), 30 * k, dtype=np.uint8))
    writer.release()
    frames, info = bc.load_video_frames(video, (80, 60), 80, max_frames=4)
    assert len(frames) == 4 and info["kind"] == "video" and info["original_sizes"] == ["160x120"]
    image = cv2.imdecode(np.frombuffer(frames[0], np.uint8), cv2.IMREAD_COLOR)
    assert (image.shape[1], image.shape[0]) == (80, 60)


# --- latencia (RNF-01) -------------------------------------------------------------------------------------------

def test_latency_valid_run_meets_threshold(fake_service, weights: Path, tmp_path: Path):
    images = write_images(tmp_path / "frames", 2)
    out = tmp_path / "evidencia"
    code = benchmark_latencia.main([*common_args(fake_service, weights, out), "--images", str(images),
                                    "--warmup", "2"])
    assert code == 0
    report = only_report(out, "latencia")

    # 100 medidos + 2 de calentamiento; cada análisis abre sesión, envía un fotograma y pide el resumen.
    assert len(fake_service.sessions) == len(fake_service.frames) == len(fake_service.summaries) == 102
    assert all(s["source"] == "imagen" for s in fake_service.sessions.values())
    assert sent_size(fake_service.frames[0]) == (1920, 1080)

    assert report["requirement"]["id"] == "RNF-01"
    assert report["model"]["sha256"] == bc.sha256_file(weights)
    assert {"cpu", "cpu_count", "gpu", "os"} <= set(report["hardware"])
    assert report["generated_at"]
    assert report["input"]["synthetic"] is False and report["input"]["original_sizes"] == ["640x480"]
    latency = report["latency_analysis"]
    assert latency["n"] == 100 and latency["mean_s"] <= latency["p95_s"] <= latency["max_s"]
    assert report["result"]["valid"] is True and report["result"]["meets"] is True


def test_latency_fails_threshold(fake_service, weights: Path, tmp_path: Path):
    images = write_images(tmp_path / "frames", 1)
    out = tmp_path / "evidencia"
    benchmark_latencia.main([*common_args(fake_service, weights, out), "--images", str(images), "--warmup", "0",
                             "--threshold", "0.0000001"])
    result = only_report(out, "latencia")["result"]
    assert result["valid"] is True and result["meets"] is False


def test_latency_short_synthetic_run_is_not_valid_evidence(fake_service, weights: Path, tmp_path: Path):
    out = tmp_path / "evidencia"
    benchmark_latencia.main([*common_args(fake_service, weights, out), "--images", str(tmp_path / "vacia"),
                             "--n", "5", "--warmup", "0", "--width", "64", "--height", "36"])
    report = only_report(out, "latencia")
    result = report["result"]
    assert report["latency_analysis"]["n"] == 5
    assert result["valid"] is False and result["meets"] is None
    assert result["meets_threshold_ignoring_validity"] is True
    assert len(result["invalid_reasons"]) == 3  # menos de 100, otra resolución y sintéticas


def test_latency_errors_are_counted_and_never_meet(fake_service, weights: Path, tmp_path: Path):
    fake_service.fail_frames = True
    out = tmp_path / "evidencia"
    code = benchmark_latencia.main([*common_args(fake_service, weights, out), "--images",
                                    str(write_images(tmp_path / "frames", 1)), "--n", "3", "--warmup", "0"])
    report = only_report(out, "latencia")
    assert code == 1
    assert report["latency_analysis"] is None and len(report["errors"]) == 3
    assert "HTTP 500" in report["errors"][0]
    assert report["result"]["meets_threshold_ignoring_validity"] is False
    assert benchmark_latencia.verdict(None, ["x"], 100, (1920, 1080), False, 2.0)["meets"] is False


# --- FPS (RNF-02) ------------------------------------------------------------------------------------------------

def test_fps_per_second_counts_full_seconds_only():
    assert benchmark_fps.fps_per_second([0.1, 0.5, 1.2, 1.9, 2.4], 2.5) == [2, 2]


def test_fps_verdict_requires_five_minutes_and_real_frames():
    summary = {"fps_mean": 20.0, "fps_min_1s": 18, "frames_error": 0}
    assert benchmark_fps.verdict(summary, 300, False, 15)["meets"] is True
    assert benchmark_fps.verdict({**summary, "fps_mean": 14.9}, 300, False, 15)["meets"] is False
    assert benchmark_fps.verdict({**summary, "frames_error": 1}, 300, False, 15)["meets"] is False
    short = benchmark_fps.verdict(summary, 60, True, 15)
    assert short["meets"] is None and len(short["invalid_reasons"]) == 2


def test_fps_run_with_image_sequence(fake_service, weights: Path, tmp_path: Path):
    images = write_images(tmp_path / "frames", 3)
    out = tmp_path / "evidencia"
    code = benchmark_fps.main([*common_args(fake_service, weights, out), "--images", str(images),
                               "--duration", "1.5", "--warmup", "0", "--width", "320", "--height", "180"])
    assert code == 0
    report = only_report(out, "fps")

    assert len(fake_service.sessions) == 1
    assert next(iter(fake_service.sessions.values()))["source"] == "video"
    assert sent_size(fake_service.frames[0]) == (320, 180)
    assert len(fake_service.summaries) == 1

    fps = report["fps"]
    assert report["requirement"]["id"] == "RNF-02"
    assert report["model"]["sha256"] == bc.sha256_file(weights)
    assert fps["frames_ok"] == len(fake_service.frames) > 0
    assert fps["fps_mean"] > 0 and fps["fps_min_1s"] is not None
    assert report["result"]["valid"] is False and report["result"]["meets"] is None  # 1,5 s < 5 min
