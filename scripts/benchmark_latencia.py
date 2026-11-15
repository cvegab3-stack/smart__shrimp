"""RNF-01: latencia de análisis de imagen en vision_service (p95 ≤ 2 s en 100 análisis a 1920×1080).

Cada análisis es lo que hace Django en modo imagen: abrir la sesión, enviar un fotograma y pedir el resumen.
Se mide el tiempo de los tres pasos juntos y, aparte, solo el del fotograma. Antes se hacen unos análisis de
calentamiento que no cuentan. El informe se guarda en docs/evidence/rendimiento/latencia_<fecha>.json.

Uso (desde la raíz del proyecto, con el entorno de vision_service):
    # Levanta el servicio aquí con el modelo actual, mide y lo detiene
    python scripts/benchmark_latencia.py --start-service
    # Contra un servicio ya en marcha (misma clave que Django)
    python scripts/benchmark_latencia.py --url http://127.0.0.1:8001 --secret <VISION_SERVICE_TOKEN_SECRET>

Las imágenes salen de samples/frames (o --images) y se llevan a 1920×1080. Si no hay ninguna, se usan imágenes
sintéticas: sirven para probar el script, no como evidencia (el informe no da por cumplido el requisito).
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchmark_common as bc  # noqa: E402

REQUIREMENT = {"id": "RNF-01", "criterion": "1920×1080, p95 ≤ 2 s en 100 análisis"}
REQUIRED_ANALYSES = 100
REQUIRED_SIZE = (1920, 1080)


def run_analyses(client, frames: list[bytes], count: int, confidence: float, prefix: str) -> tuple[list, list, list]:
    totals, frame_times, errors = [], [], []
    for k in range(count):
        analysis_id = bc.new_analysis_id(prefix)
        jpeg = frames[k % len(frames)]
        started = time.perf_counter()
        try:
            client.start_session(analysis_id, "imagen", confidence)
            frame_started = time.perf_counter()
            client.frame(analysis_id, f"{analysis_id}-1", jpeg)
            frame_times.append(time.perf_counter() - frame_started)
            client.summary(analysis_id)
            totals.append(time.perf_counter() - started)
        except (OSError, RuntimeError) as exc:
            errors.append(f"análisis {k + 1}: {exc}")
    return totals, frame_times, errors


def stats(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"n": len(values), "mean_s": round(statistics.fmean(values), 4),
            "p50_s": round(bc.percentile(values, 50), 4), "p95_s": round(bc.percentile(values, 95), 4),
            "max_s": round(max(values), 4), "min_s": round(min(values), 4)}


def verdict(total: dict | None, errors: list, count: int, size, synthetic: bool, threshold: float) -> dict:
    """cumple = True/False solo si la prueba es válida para RNF-01; si no, None con los motivos."""
    reasons = []
    if count < REQUIRED_ANALYSES:
        reasons.append(f"se pidieron {count} análisis; el requisito pide {REQUIRED_ANALYSES}")
    if tuple(size) != REQUIRED_SIZE:
        reasons.append(f"resolución {size[0]}x{size[1]}; el requisito pide 1920x1080")
    if synthetic:
        reasons.append("imágenes sintéticas: no son fotos reales de camarones")
    p95 = total["p95_s"] if total else None
    meets_threshold = p95 is not None and p95 <= threshold and not errors
    return {"threshold_p95_s": threshold, "p95_s": p95, "errors": len(errors), "valid": not reasons,
            "invalid_reasons": reasons, "meets": meets_threshold if not reasons else None,
            "meets_threshold_ignoring_validity": meets_threshold}


def main(argv=None) -> int:
    bc.safe_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    bc.add_service_arguments(parser)
    parser.add_argument("--images", type=Path, default=bc.DEFAULT_IMAGES, help="Carpeta de imágenes de prueba.")
    parser.add_argument("--n", type=int, default=REQUIRED_ANALYSES, help="Análisis medidos (por defecto 100).")
    parser.add_argument("--warmup", type=int, default=3, help="Análisis de calentamiento que no cuentan.")
    parser.add_argument("--width", type=int, default=REQUIRED_SIZE[0])
    parser.add_argument("--height", type=int, default=REQUIRED_SIZE[1])
    parser.add_argument("--quality", type=int, default=92, help="Calidad JPEG (la de la app en modo imagen: 92).")
    parser.add_argument("--threshold", type=float, default=2.0, help="Umbral de p95 en segundos.")
    args = parser.parse_args(argv)
    if args.n < 1:
        parser.error("--n debe ser al menos 1.")

    size = (args.width, args.height)
    frames, frames_info = bc.load_image_frames(args.images, size, args.quality)
    with bc.service_client(args) as (client, service_url, local):
        report = bc.base_report("latencia", REQUIREMENT, args, service_url, local, frames_info)
        if args.warmup:
            run_analyses(client, frames, args.warmup, args.confidence, "bench-warmup")
        totals, frame_times, errors = run_analyses(client, frames, args.n, args.confidence, "bench-lat")

    total_stats = stats(totals)
    report.update({
        "settings": {"analyses": args.n, "warmup": args.warmup, "jpeg_quality": args.quality,
                     "confidence": args.confidence},
        "latency_analysis": total_stats,
        "latency_frame_only": stats(frame_times),
        "errors": errors[:20],
        "result": verdict(total_stats, errors, args.n, size, frames_info["synthetic"], args.threshold),
    })
    path = bc.save_report(args.out, "latencia", report)
    result = report["result"]
    if total_stats:
        print(f"Análisis: media {total_stats['mean_s']} s, p95 {total_stats['p95_s']} s, máximo {total_stats['max_s']} s"
              f" ({total_stats['n']} correctos, {len(errors)} con error)")
    else:
        print(f"Ningún análisis terminó bien ({len(errors)} errores). Primero: {errors[0] if errors else '-'}")
    state = {True: "CUMPLE", False: "NO CUMPLE", None: "NO VÁLIDA como evidencia"}[result["meets"]]
    print(f"RNF-01 (p95 <= {args.threshold} s): {state}" +
          (f" — {'; '.join(result['invalid_reasons'])}" if result["invalid_reasons"] else ""))
    print(f"Informe: {path}")
    return 0 if total_stats else 1


if __name__ == "__main__":
    sys.exit(main())
