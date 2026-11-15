"""RNF-02: fotogramas por segundo de vision_service en modo video (promedio ≥ 15 FPS durante 5 min).

Abre una sesión de video y envía fotogramas uno tras otro, esperando cada respuesta como el navegador, pero sin su
tope de 15 FPS: así se mide la capacidad del servicio. Los fotogramas salen de --video, o de las imágenes de
samples/frames (o --images) en bucle si no se da un video. Reporta:
  - FPS promedio: fotogramas procesados / tiempo total;
  - FPS mínimo: el menor número de fotogramas terminados en un segundo completo de la prueba;
  - latencia por fotograma (media, p95, máximo).
El informe se guarda en docs/evidence/rendimiento/fps_<fecha>.json.

Uso (desde la raíz del proyecto, con el entorno de vision_service):
    python scripts/benchmark_fps.py --start-service --video C:\\ruta\\video_planta.mp4
    python scripts/benchmark_fps.py --start-service --images C:\\ruta\\fotos_planta   # sin video: fotos en bucle
    python scripts/benchmark_fps.py --url http://127.0.0.1:8001 --secret <clave> --duration 300

Una prueba de menos de 5 min o con imágenes sintéticas no se da por válida para RNF-02.
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchmark_common as bc  # noqa: E402

REQUIREMENT = {"id": "RNF-02", "criterion": "vídeo promedio ≥ 15 FPS durante 5 min"}
REQUIRED_SECONDS = 300


def fps_per_second(completions: list[float], elapsed: float) -> list[int]:
    """Fotogramas terminados en cada segundo completo (los instantes son relativos al inicio)."""
    windows = [0] * int(math.floor(elapsed))
    for moment in completions:
        index = int(moment)
        if index < len(windows):
            windows[index] += 1
    return windows


def stream(client, frames: list[bytes], seconds: float, confidence: float, prefix: str) -> dict:
    """Envía fotogramas en serie durante `seconds` y devuelve los tiempos medidos."""
    analysis_id = bc.new_analysis_id(prefix)
    client.start_session(analysis_id, "video", confidence)
    latencies, completions, errors = [], [], []
    started = time.perf_counter()
    k = 0
    while time.perf_counter() - started < seconds:
        sent = time.perf_counter()
        try:
            client.frame(analysis_id, f"{analysis_id}-{k}", frames[k % len(frames)])
            now = time.perf_counter()
            latencies.append(now - sent)
            completions.append(now - started)
        except (OSError, RuntimeError) as exc:
            errors.append(f"fotograma {k}: {exc}")
        k += 1
    elapsed = time.perf_counter() - started
    try:
        client.summary(analysis_id)
    except (OSError, RuntimeError) as exc:
        errors.append(f"resumen: {exc}")
    return {"latencies": latencies, "completions": completions, "errors": errors, "elapsed": elapsed, "sent": k}


def summarize(run: dict) -> dict:
    elapsed, latencies = run["elapsed"], run["latencies"]
    windows = fps_per_second(run["completions"], elapsed)
    return {
        "duration_s": round(elapsed, 2),
        "frames_sent": run["sent"],
        "frames_ok": len(latencies),
        "frames_error": len(run["errors"]),
        "fps_mean": round(len(latencies) / elapsed, 2) if elapsed > 0 else None,
        "fps_min_1s": min(windows) if windows else None,
        "fps_max_1s": max(windows) if windows else None,
        "seconds_below_15": sum(1 for w in windows if w < 15),
        "frame_latency": None if not latencies else {
            "mean_s": round(statistics.fmean(latencies), 4), "p95_s": round(bc.percentile(latencies, 95), 4),
            "max_s": round(max(latencies), 4)},
    }


def verdict(summary: dict, requested_seconds: float, synthetic: bool, threshold: float) -> dict:
    reasons = []
    if requested_seconds < REQUIRED_SECONDS:
        reasons.append(f"duración {requested_seconds:g} s; el requisito pide {REQUIRED_SECONDS} s (5 min)")
    if synthetic:
        reasons.append("fotogramas sintéticos: no son imágenes reales de camarones")
    fps = summary["fps_mean"]
    meets_threshold = fps is not None and fps >= threshold and summary["frames_error"] == 0
    return {"threshold_fps_mean": threshold, "fps_mean": fps, "fps_min_1s": summary["fps_min_1s"],
            "errors": summary["frames_error"], "valid": not reasons, "invalid_reasons": reasons,
            "meets": meets_threshold if not reasons else None,
            "meets_threshold_ignoring_validity": meets_threshold}


def main(argv=None) -> int:
    bc.safe_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    bc.add_service_arguments(parser)
    parser.add_argument("--video", type=Path, help="Video de prueba; sin él se usan las imágenes de --images.")
    parser.add_argument("--images", type=Path, default=bc.DEFAULT_IMAGES,
                        help="Sin --video: carpeta de fotos (puede estar fuera del repo) que se recorre en bucle. "
                             "Por defecto samples/frames.")
    parser.add_argument("--duration", type=float, default=REQUIRED_SECONDS, help="Segundos medidos (por defecto 300).")
    parser.add_argument("--warmup", type=float, default=5, help="Segundos de calentamiento que no cuentan.")
    parser.add_argument("--max-frames", type=int, default=450, help="Fotogramas del video cargados en memoria.")
    parser.add_argument("--width", type=int, default=1920, help="Ancho enviado (0 = el del video o la imagen).")
    parser.add_argument("--height", type=int, default=1080, help="Alto enviado (0 = el del video o la imagen).")
    parser.add_argument("--quality", type=int, default=82, help="Calidad JPEG (la de la app en video: 82).")
    parser.add_argument("--threshold", type=float, default=15.0, help="FPS promedio mínimo.")
    args = parser.parse_args(argv)
    if args.duration <= 0:
        parser.error("--duration debe ser mayor que 0.")

    size = (args.width, args.height) if args.width and args.height else None
    if args.video:
        frames, frames_info = bc.load_video_frames(args.video, size, args.quality, args.max_frames)
    else:
        frames, frames_info = bc.load_image_frames(args.images, size or (1920, 1080), args.quality)
    with bc.service_client(args) as (client, service_url, local):
        report = bc.base_report("fps", REQUIREMENT, args, service_url, local, frames_info)
        if args.warmup:
            stream(client, frames, args.warmup, args.confidence, "bench-fps-warmup")
        run = stream(client, frames, args.duration, args.confidence, "bench-fps")

    summary = summarize(run)
    report.update({
        "settings": {"duration_s": args.duration, "warmup_s": args.warmup, "jpeg_quality": args.quality,
                     "confidence": args.confidence, "browser_cap_fps": None,
                     "note": "sin el tope de 15 FPS del navegador: mide la capacidad del servicio"},
        "fps": summary,
        "errors": run["errors"][:20],
        "result": verdict(summary, args.duration, frames_info["synthetic"], args.threshold),
    })
    path = bc.save_report(args.out, "fps", report)
    result = report["result"]
    print(f"FPS promedio {summary['fps_mean']}, mínimo en 1 s {summary['fps_min_1s']} "
          f"({summary['frames_ok']} fotogramas en {summary['duration_s']} s, {summary['frames_error']} con error)")
    state = {True: "CUMPLE", False: "NO CUMPLE", None: "NO VÁLIDA como evidencia"}[result["meets"]]
    print(f"RNF-02 (promedio >= {args.threshold} FPS): {state}" +
          (f" — {'; '.join(result['invalid_reasons'])}" if result["invalid_reasons"] else ""))
    print(f"Informe: {path}")
    return 0 if summary["frames_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
