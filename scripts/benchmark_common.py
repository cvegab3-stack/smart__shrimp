"""Utilidades compartidas por benchmark_latencia.py y benchmark_fps.py.

Miden solo el servicio de visión (M3) por su API HTTP, con el mismo token HMAC que usa Django. No incluyen Django,
la red hasta el navegador ni la captura de la cámara: la evidencia de RNF-01/RNF-02 de extremo a extremo necesita
además esa parte.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import platform
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "contracts"))

from shrimp_contracts.token_claims import issue_service_token  # noqa: E402

DEFAULT_URL = "http://127.0.0.1:8001"
DEFAULT_IMAGES = REPO_ROOT / "samples" / "frames"
DEFAULT_OUT = REPO_ROOT / "docs" / "evidence" / "rendimiento"
DEFAULT_WEIGHTS = REPO_ROOT / "models" / "detector" / "best.pt"
MODEL_INFO = REPO_ROOT / "models" / "detector" / "model_info.json"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}
# Rangos de tamaño de ejemplo: con calibración el servicio también mide longitud y categoría, como en planta.
SIZE_RANGES = {"pequeno": {"min_cm": 0, "max_cm": 8}, "mediano": {"min_cm": 8, "max_cm": 12},
               "grande": {"min_cm": 12, "max_cm": None}}


def safe_console() -> None:
    """Evita que la consola de Windows (cp1252) aborte el script al imprimir caracteres como ≤ o ×."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")


def percentile(values: list[float], p: float) -> float:
    """Percentil con interpolación lineal (el mismo criterio que numpy por defecto)."""
    if not values:
        raise ValueError("No hay valores.")
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    low = int(k)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (k - low)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_summary(weights: Path) -> dict:
    """SHA-256 de los pesos y si coinciden con models/detector/model_info.json."""
    if not weights.is_file():
        return {"path": str(weights), "sha256": None, "note": "no existe el archivo de pesos"}
    sha = sha256_file(weights)
    try:
        expected = json.loads(MODEL_INFO.read_text(encoding="utf-8")).get("sha256")
    except (OSError, ValueError):
        expected = None
    return {"path": str(weights), "sha256": sha, "matches_model_info": sha == expected if expected else None}


def _run(command: list[str]) -> str:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=20, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def cpu_name() -> str:
    if sys.platform == "win32":
        name = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])
        return name or os.getenv("PROCESSOR_IDENTIFIER", "") or platform.processor()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor()


def hardware_info(service_is_local: bool) -> dict:
    """Equipo donde corre el benchmark. Si el servicio es remoto, su hardware no se conoce desde aquí."""
    gpus = [line.strip() for line in _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                                           "--format=csv,noheader"]).splitlines() if line.strip()]
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": cpu_name(),
        "cpu_count": os.cpu_count(),
        "gpu": gpus or None,
        "service_is_local": service_is_local,
        "note": None if service_is_local else "servicio remoto: el hardware anotado es el del cliente, no el de M3",
    }


def encode_jpeg(image, quality: int) -> bytes:
    import cv2

    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("No se pudo codificar la imagen.")
    return buffer.tobytes()


def resize_to(image, size: tuple[int, int] | None):
    import cv2

    if size and (image.shape[1], image.shape[0]) != size:
        return cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    return image


def synthetic_frames(count: int, size: tuple[int, int], quality: int) -> list[bytes]:
    """Fotogramas de relleno (fondo con textura y manchas claras), solo para probar el script."""
    import numpy as np

    width, height = size
    patch_w, patch_h = max(1, width // 16), max(1, height // 27)  # 120×40 px en 1920×1080
    rng = np.random.default_rng(0)
    frames = []
    for k in range(count):
        image = rng.integers(40, 90, (height, width, 3), dtype=np.uint8)
        for _ in range(12):
            x, y = int(rng.integers(0, width - patch_w + 1)), int(rng.integers(0, height - patch_h + 1))
            image[y:y + patch_h, x:x + patch_w] = (180 + k % 40, 160, 150)
        frames.append(encode_jpeg(image, quality))
    return frames


def load_image_frames(images_dir: Path, size: tuple[int, int] | None, quality: int,
                      synthetic_count: int = 10) -> tuple[list[bytes], dict]:
    """Imágenes de la carpeta, llevadas a `size` y en JPEG; si no hay, fotogramas sintéticos (marcado en el informe)."""
    import cv2

    files = sorted(p for p in images_dir.glob("*") if p.suffix.lower() in IMAGE_SUFFIXES) if images_dir.is_dir() else []
    frames, sizes = [], set()
    for path in files:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        sizes.add(f"{image.shape[1]}x{image.shape[0]}")
        frames.append(encode_jpeg(resize_to(image, size), quality))
    if frames:
        return frames, {"source": str(images_dir), "kind": "imagenes", "synthetic": False, "files": len(frames),
                        "original_sizes": sorted(sizes), "sent_size": f"{size[0]}x{size[1]}" if size else None}
    if size is None:
        raise SystemExit(f"No hay imágenes en {images_dir} y sin --width/--height no se pueden generar sintéticas.")
    return synthetic_frames(synthetic_count, size, quality), {
        "source": f"sintéticas (no hay imágenes en {images_dir})", "kind": "sinteticas", "synthetic": True,
        "files": synthetic_count, "original_sizes": [], "sent_size": f"{size[0]}x{size[1]}"}


def load_video_frames(video: Path, size: tuple[int, int] | None, quality: int, max_frames: int) -> tuple[list[bytes], dict]:
    """Hasta `max_frames` fotogramas del video, en JPEG (luego se envían en bucle)."""
    import cv2

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise SystemExit(f"No se pudo abrir el video {video}.")
    frames, original = [], None
    try:
        while len(frames) < max_frames:
            ok, image = capture.read()
            if not ok:
                break
            original = original or f"{image.shape[1]}x{image.shape[0]}"
            frames.append(encode_jpeg(resize_to(image, size), quality))
        source_fps = capture.get(cv2.CAP_PROP_FPS) or None
    finally:
        capture.release()
    if not frames:
        raise SystemExit(f"El video {video} no tiene fotogramas legibles.")
    return frames, {"source": str(video), "kind": "video", "synthetic": False, "files": len(frames),
                    "original_sizes": [original], "source_fps": source_fps,
                    "sent_size": f"{size[0]}x{size[1]}" if size else original}


class VisionClient:
    """Cliente mínimo de la API de M3 con el mismo costo por petición que Django.

    Igual que backend/integrations/vision_client.py: requests con una Session que reutiliza la conexión TCP y un
    token nuevo por petición. Si Django cambia su forma de conectarse, este cliente debe seguirla para que la
    medida siga siendo comparable. (requests llega al entorno de vision_service como dependencia de ultralytics.)
    """

    def __init__(self, base_url: str, secret: str, timeout: float = 30.0) -> None:
        import requests

        if not secret:
            raise SystemExit("Falta la clave: use --secret o la variable VISION_SERVICE_TOKEN_SECRET.")
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.timeout = timeout
        self.session = requests.Session()

    def close(self) -> None:
        self.session.close()

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        # requests.RequestException hereda de OSError: quien llama trata red caída y HTTP >= 400 por igual.
        response = self.session.request(
            method, self.base_url + path, json=payload, timeout=self.timeout,
            headers={"Authorization": "Bearer " + issue_service_token(self.secret, "benchmark")})
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code} {response.text[:300]}")
        return response.json() if response.content else {}

    def health(self) -> dict:
        return self._request("GET", "/v1/health")

    def start_session(self, analysis_id: str, source: str, confidence: float) -> dict:
        return self._request("POST", "/v1/sessions", {
            "analysis_id": analysis_id, "attempt": 1, "calibration_version": 1, "source": source,
            "reference_length_cm": 10.0, "reference_pixels": 500, "size_ranges": SIZE_RANGES,
            "detection_confidence": confidence, "visual_condition_confidence": 0.5})

    def frame(self, analysis_id: str, frame_id: str, jpeg: bytes) -> dict:
        return self._request("POST", "/v1/frames", {
            "analysis_id": analysis_id, "attempt": 1, "frame_id": frame_id,
            "captured_at": datetime.now().astimezone().isoformat(), "calibration_version": 1,
            "image_base64": base64.b64encode(jpeg).decode()})

    def summary(self, analysis_id: str) -> dict:
        return self._request("POST", "/v1/sessions/summary", {"analysis_id": analysis_id, "attempt": 1})


def new_analysis_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def service_command(port: int) -> list[str]:
    """Mismo arranque que el despliegue (vision_service/Dockerfile), incluido el keep-alive de 30 s."""
    return [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(REPO_ROOT / "vision_service"),
            "--host", "127.0.0.1", "--port", str(port), "--timeout-keep-alive", "30"]


def service_env(weights: Path, secret: str) -> dict:
    env = dict(os.environ)
    env.update({"VISION_SERVICE_TOKEN_SECRET": secret, "DETECTOR_WEIGHTS": str(weights),
                "PYTHONPATH": os.pathsep.join([str(REPO_ROOT / "vision_service"), str(REPO_ROOT / "contracts")])})
    return env


@contextlib.contextmanager
def running_service(port: int, weights: Path, timeout: float = 300.0):
    """Levanta vision_service en 127.0.0.1:<port> con una clave temporal y lo detiene al terminar."""
    secret = secrets.token_urlsafe(32)
    log = tempfile.NamedTemporaryFile("w+", suffix="_vision_benchmark.log", delete=False, encoding="utf-8")
    process = subprocess.Popen(service_command(port), env=service_env(weights, secret), stdout=log,
                               stderr=subprocess.STDOUT, cwd=REPO_ROOT)
    client = VisionClient(f"http://127.0.0.1:{port}", secret)
    try:
        deadline = time.monotonic() + timeout
        while True:
            if process.poll() is not None:
                log.seek(0)
                raise SystemExit(f"vision_service terminó al arrancar (código {process.returncode}):\n{log.read()[-2000:]}")
            try:
                client.health()
                break
            except (OSError, RuntimeError):
                if time.monotonic() > deadline:
                    raise SystemExit(f"vision_service no respondió en {timeout:.0f} s; registro: {log.name}")
                time.sleep(1)
        yield client
    finally:
        client.close()
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()


def save_report(out_dir: Path, prefix: str, report: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{prefix}_{datetime.now():%Y-%m-%d_%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def add_service_arguments(parser) -> None:
    parser.add_argument("--url", default=DEFAULT_URL, help=f"vision_service ya en marcha (por defecto {DEFAULT_URL}).")
    parser.add_argument("--secret", default=os.getenv("VISION_SERVICE_TOKEN_SECRET", ""),
                        help="Clave del token (por defecto VISION_SERVICE_TOKEN_SECRET). No hace falta con --start-service.")
    parser.add_argument("--start-service", action="store_true",
                        help="Levantar vision_service en este equipo con una clave temporal y detenerlo al terminar.")
    parser.add_argument("--port", type=int, default=8011, help="Puerto para --start-service (por defecto 8011).")
    parser.add_argument("--weights", type=Path, default=Path(os.getenv("DETECTOR_WEIGHTS") or DEFAULT_WEIGHTS),
                        help="Pesos del detector: los usa --start-service y se anota su SHA-256.")
    parser.add_argument("--confidence", type=float, default=0.5, help="Confianza de detección de la sesión.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Carpeta del informe JSON.")


@contextlib.contextmanager
def service_client(args):
    """Cliente del servicio pedido: uno levantado aquí (--start-service) o el de --url."""
    if args.start_service:
        with running_service(args.port, args.weights) as client:
            yield client, f"http://127.0.0.1:{args.port} (levantado por el benchmark)", True
    else:
        client = VisionClient(args.url, args.secret)
        local = args.url.split("//", 1)[-1].split(":")[0].split("/")[0] in {"127.0.0.1", "localhost"}
        try:
            yield client, args.url, local
        finally:
            client.close()


def base_report(kind: str, requirement: dict, args, service_url: str, service_is_local: bool, frames_info: dict) -> dict:
    return {
        "benchmark": kind,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "command": " ".join([Path(sys.argv[0]).name, *sys.argv[1:]]) if sys.argv else None,
        "requirement": requirement,
        "scope": "solo vision_service (M3) por HTTP; sin Django, navegador ni cámara",
        "service": service_url,
        "hardware": hardware_info(service_is_local),
        "model": model_summary(args.weights),
        "input": frames_info,
    }
