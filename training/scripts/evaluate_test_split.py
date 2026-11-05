"""Evaluación reproducible del detector "camaron" en la partición de PRUEBA (test), y solo en ella.

Reutiliza evaluate_detector.py: mismas métricas de Ultralytics (conf=0.001, iou=0.7, imgsz=640) y mismo punto de
operación de la aplicación (operating_point: TP/FP/FN con IoU >= 0.5, error de conteo por imagen).

Antes de medir comprueba que test está separado de train y de val. Se detiene sin medir si:
  - una imagen de test comparte nombre, foto fuente (antes de ".rf." de Roboflow) o contenido (SHA-256) con train/val;
  - comparte sesión de captura (grupo) o vídeo con train/val según audit/images.csv;
  - falta audit/images.csv o una imagen de test no aparece en él (no se puede comprobar la separación).
No existe opción para evaluar val: validación no sustituye a test.

El informe (métricas, SHA-256 del modelo, huella del conjunto de test y resultado de la comprobación) se guarda en
--out (por defecto docs/evidence/detector_test/report.json). Los archivos intermedios de Ultralytics van a
training/runs/detector/eval/ (ignorado por git).

Uso (PowerShell, desde la raíz del proyecto):
    & .\\.venv312\\Scripts\\python.exe training\\scripts\\evaluate_test_split.py `
        --data-dir "C:\\ruta\\a\\dataset"
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

from data_paths import DATA_DIR_ENV, REPO_ROOT, find_in_data_dir
from evaluate_detector import IOU_MATCH, operating_point, resolve

DEFAULT_DATA = "shrimp_roboflow_v4/detect_grouped_reviewed_v1/data.yaml"
DEFAULT_MODEL = "models/detector/best.pt"
DEFAULT_OUT = "docs/evidence/detector_test"
MODEL_INFO = REPO_ROOT / "models" / "detector" / "model_info.json"
RUNS_DIR = REPO_ROOT / "training" / "runs" / "detector" / "eval"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_of(name: str) -> str:
    """Foto o fotograma original: Roboflow añade '_jpg.rf.<hash>' a cada variante aumentada."""
    return re.split(r"_(?:jpg|jpeg|png)\.rf\.", Path(name).stem)[0]


def read_listing(dataset: Path, listing: str) -> list[Path]:
    path = dataset / listing
    if not path.is_file():
        raise SystemExit(f"No existe la lista {path} declarada en data.yaml.")
    return [(path.parent / rel).resolve() for rel in path.read_text(encoding="utf-8").split()]


def load_splits(data_yaml: Path) -> dict[str, list[Path]]:
    data = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    names = data.get("names")
    names = dict(enumerate(names)) if isinstance(names, list) else {int(k): v for k, v in (names or {}).items()}
    if names != {0: "camaron"}:
        raise SystemExit(f"{data_yaml} debe declarar una sola clase 'camaron'; tiene {names}.")
    missing = [split for split in ("train", "val", "test") if not data.get(split)]
    if missing:
        raise SystemExit(f"{data_yaml} no declara {missing}: sin las tres listas no se puede comprobar que test "
                         "esté separado.")
    return {split: read_listing(data_yaml.parent, str(data[split])) for split in ("train", "val", "test")}


def check_separation(splits: dict[str, list[Path]], audit_csv: Path) -> dict:
    """Compara test con train y val por nombre, foto fuente, contenido, sesión y vídeo. No modifica nada."""
    if not audit_csv.is_file():
        raise SystemExit(f"No existe {audit_csv}: sin la sesión y el vídeo de cada imagen no se puede comprobar que "
                         "test esté separado. Indique --audit o regenere la auditoría con prepare_shrimp_dataset.py.")
    with open(audit_csv, encoding="utf-8") as handle:
        audit = {row["image"]: row for row in csv.DictReader(handle)}

    keys: dict[str, dict[str, set[str]]] = {}
    problems: list[str] = []
    for split, images in splits.items():
        found = {"name": set(), "source": set(), "sha256": set(), "group": set(), "video": set()}
        for image in images:
            if not image.is_file():
                problems.append(f"{split}: falta la imagen {image}")
                continue
            found["name"].add(image.name)
            found["source"].add(source_of(image.name))
            found["sha256"].add(sha256_file(image))
            row = audit.get(image.name)
            if row is None:
                problems.append(f"{split}: {image.name} no aparece en {audit_csv.name}; no se puede verificar")
                continue
            found["group"].add(row["group"])
            if row.get("video_id"):
                found["video"].add(row["video_id"])
        keys[split] = found

    shared = {}
    for other in ("train", "val"):
        for key in ("name", "source", "sha256", "group", "video"):
            common = sorted(keys["test"][key] & keys[other][key])
            shared[f"test_{other}_{key}"] = len(common)
            if common:
                problems.append(f"test y {other} comparten {len(common)} '{key}' (p. ej. {common[:3]})")
    return {
        "ok": not problems,
        "audit_csv": str(audit_csv),
        "images": {split: len(images) for split, images in splits.items()},
        "test_groups": sorted(keys["test"]["group"]),
        "shared_counts": shared,
        "problems": problems[:50],
    }


def fingerprint(images: list[Path], dataset: Path) -> tuple[str, int]:
    """SHA-256 de (nombre, hash de imagen, hash de etiqueta) de test: identifica exactamente lo evaluado."""
    digest = hashlib.sha256()
    objects = 0
    for image in sorted(images, key=lambda p: p.name):
        label = dataset / "labels" / f"{image.stem}.txt"
        if not label.is_file():
            raise SystemExit(f"Falta la etiqueta {label}")
        text = label.read_text(encoding="utf-8")
        objects += sum(1 for line in text.splitlines() if line.strip())
        digest.update(f"{image.name}\t{sha256_file(image)}\t{sha256_file(label)}\n".encode())
    return digest.hexdigest(), objects


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=DEFAULT_DATA,
                        help="data.yaml con train/val/test, absoluto o relativo a la carpeta de datos.")
    parser.add_argument("--data-dir", help=f"Carpeta de datos (por defecto {DATA_DIR_ENV} o ..\\dataset).")
    parser.add_argument("--audit", type=Path,
                        help="audit/images.csv (por defecto <dataset>/../audit/images.csv).")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Pesos a evaluar (no se modifican).")
    parser.add_argument("--conf", type=float, default=0.5, help="Confianza de operación (la de la aplicación).")
    parser.add_argument("--device", default="0", help="0 (GPU) o cpu.")
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUT))
    parser.add_argument("--check-only", action="store_true",
                        help="Solo comprueba la separación y la huella de test; no carga el modelo.")
    args = parser.parse_args(argv)

    data_yaml = find_in_data_dir(args.data, args.data_dir)
    dataset = data_yaml.parent
    splits = load_splits(data_yaml)
    audit_csv = args.audit.resolve() if args.audit else dataset.parent / "audit" / "images.csv"

    print(f"Dataset: {data_yaml}")
    separation = check_separation(splits, audit_csv)
    print("Separación:", json.dumps({k: separation[k] for k in ("ok", "images", "shared_counts")}))
    if not separation["ok"]:
        for problem in separation["problems"]:
            print("  -", problem)
        raise SystemExit("Test NO está separado de train/val (o no se pudo comprobar). No se evalúa.")

    test_images = splits["test"]
    test_sha, test_objects = fingerprint(test_images, dataset)
    print(f"Test: {len(test_images)} imágenes, {test_objects} objetos, huella {test_sha[:16]}…")
    if args.check_only:
        return 0

    model_path = resolve(args.model)
    if not model_path.is_file():
        raise SystemExit(f"No existe el modelo {model_path}.")
    model_sha = sha256_file(model_path)
    info = json.loads(MODEL_INFO.read_text(encoding="utf-8")) if MODEL_INFO.is_file() else {}

    import torch
    import ultralytics
    from ultralytics import YOLO

    train_args = (YOLO(str(model_path)).ckpt or {}).get("train_args", {})
    run_name = f"test_{model_sha[:12]}"
    metrics = YOLO(str(model_path)).val(
        data=str(data_yaml), split="test", imgsz=640, batch=8, conf=0.001, iou=0.7, single_cls=True,
        device=args.device, plots=False, verbose=False, project=str(RUNS_DIR), name=run_name, exist_ok=True)
    ultra = {"precision": round(float(metrics.box.mp), 4), "recall": round(float(metrics.box.mr), 4),
             "mAP50": round(float(metrics.box.map50), 4), "mAP50_95": round(float(metrics.box.map), 4)}
    at_conf = operating_point(YOLO(str(model_path)), test_images, dataset, args.conf, args.device)

    cuda = torch.cuda.is_available() and args.device != "cpu"
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "split": "test",
        "command": " ".join([Path(sys.executable).name, *sys.argv]),
        "environment": {"python": platform.python_version(), "torch": torch.__version__,
                        "ultralytics": ultralytics.__version__,
                        "device": torch.cuda.get_device_name(0) if cuda else "cpu"},
        "model": {"path": str(model_path), "sha256": model_sha,
                  "matches_model_info": model_sha == info.get("sha256"),
                  "trained_on": train_args.get("data"), "train_run": train_args.get("name")},
        "dataset": {"data_yaml": str(data_yaml), "images": len(test_images), "objects": test_objects,
                    "test_fingerprint_sha256": test_sha},
        "separation_check": separation,
        "settings": {"ultralytics_val": {"conf": 0.001, "iou": 0.7, "imgsz": 640, "single_cls": True},
                     "operating_point": {"conf": args.conf, "iou_match": IOU_MATCH, "imgsz": 640}},
        "metrics": {"ultralytics": ultra, f"at_conf_{args.conf}": at_conf},
    }
    out = resolve(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Ultralytics:", json.dumps(ultra))
    print(f"Conf {args.conf}:", json.dumps(at_conf))
    print(f"Informe: {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
