"""Entrena el detector YOLO de una clase "camaron" para el servicio de visión.

No descarga pesos: --model debe ser un .pt local o un .yaml de arquitectura (entrenamiento desde cero).
El dataset se busca fuera del proyecto (ver data_paths.py); solo se lee durante el entrenamiento.
El modelo resultante queda en <project>/<name>/weights/best.pt; para que lo use la aplicación, cópielo a
models/detector/best.pt y actualice models/detector/model_info.json.

Uso:
    python training/scripts/train_detector.py --model training/weights/yolov8n.pt --dry-run
    python training/scripts/train_detector.py --model models/detector/best.pt --name camaron_v2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from data_paths import DATA_DIR_ENV, REPO_ROOT, find_in_data_dir

DEFAULT_CONFIG = REPO_ROOT / "training" / "configs" / "detector_train.yaml"
EXPECTED_CLASSES = {0: "camaron"}


def resolve(path_value: str | Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def check_data_yaml(data_path: Path) -> None:
    """Comprueba que el conjunto sea de una sola clase 'camaron', compatible con el detector actual."""
    if not data_path.is_file():
        raise SystemExit(f"No existe {data_path}. Ejecute antes training/scripts/prepare_shrimp_dataset.py.")
    data = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    names = data.get("names")
    names = dict(enumerate(names)) if isinstance(names, list) else {int(k): v for k, v in (names or {}).items()}
    if names != EXPECTED_CLASSES or int(data.get("nc", 0)) != 1:
        raise SystemExit(f"{data_path} debe declarar nc: 1 y names {{0: camaron}}; tiene {names}.")
    for split in ("train", "val"):
        listing = data_path.parent / str(data.get(split, ""))
        if not listing.is_file() or not listing.read_text(encoding="utf-8").strip():
            raise SystemExit(f"La lista '{split}' ({listing}) no existe o está vacía.")
        first = listing.read_text(encoding="utf-8").split()[0]
        if not (listing.parent / first).is_file():
            raise SystemExit(f"Falta la imagen {listing.parent / first} de la lista '{split}': el dataset está "
                             "incompleto o se movió sin su carpeta images/.")


def check_model(model_value: str) -> Path:
    if not model_value:
        raise SystemExit("Indique --model con un .pt local o un .yaml de arquitectura; no se descargan pesos.")
    if model_value.endswith((".yaml", ".yml")) and not resolve(model_value).is_file():
        # Nombre de arquitectura incluido en Ultralytics (p. ej. yolov8n.yaml): no implica descarga.
        return Path(model_value)
    model_path = resolve(model_value)
    if not model_path.is_file():
        raise SystemExit(f"No existe el modelo inicial {model_path}. Cópielo localmente; el script no descarga pesos.")
    return model_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data", help="data.yaml de una clase, absoluto o relativo a la carpeta de datos.")
    parser.add_argument("--data-dir", help=f"Carpeta de datos (por defecto {DATA_DIR_ENV} o ..\\dataset).")
    parser.add_argument("--model", help="Pesos .pt locales o arquitectura .yaml.")
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--batch", type=int)
    parser.add_argument("--imgsz", type=int)
    parser.add_argument("--device", help="Ej.: 0, cpu.")
    parser.add_argument("--name", help="Nombre de la ejecución dentro de project.")
    parser.add_argument("--dry-run", action="store_true", help="Valida y muestra la configuración sin entrenar.")
    args = parser.parse_args(argv)

    config = yaml.safe_load(resolve(args.config).read_text(encoding="utf-8"))
    data_path = find_in_data_dir(args.data or config["data"], args.data_dir)
    model = check_model(args.model or config.get("model") or "")
    check_data_yaml(data_path)

    train_args = dict(config.get("train") or {})
    for key in ("epochs", "batch", "imgsz", "device"):
        if getattr(args, key) is not None:
            train_args[key] = getattr(args, key)
    train_args.update(data=str(data_path), project=str(resolve(config["project"])), name=args.name or config["name"],
                      exist_ok=False)
    expected = Path(train_args["project"]) / train_args["name"] / "weights" / "best.pt"
    if expected.parent.parent.exists() and not args.dry_run:
        # Ultralytics renombraría la ejecución (camaron_v12...) y la ruta esperada dejaría de ser válida.
        raise SystemExit(f"{expected.parent.parent} ya existe; use --name para una ejecución nueva.")

    print(f"Modelo inicial: {model}")
    for key, value in sorted(train_args.items()):
        print(f"  {key}: {value}")
    print(f"Modelo esperado: {expected}")
    if args.dry_run:
        return 0

    from ultralytics import YOLO

    YOLO(str(model)).train(**train_args)
    print(f"Entrenamiento terminado: {expected}\n"
          "Revise sus métricas antes de copiarlo a models/detector/best.pt (guarde el anterior).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
