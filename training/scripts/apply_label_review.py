"""Construye una copia revisada del conjunto de detección agrupado aplicando un registro de correcciones.

No modifica el ZIP ni datasets/<id>/detect: las imágenes se enlazan (o copian) y las etiquetas se copian a la
carpeta de salida, donde se aplican las correcciones de review/corrections.csv.

Acciones de corrections.csv (coordenadas en píxeles de la imagen tal como está en el dataset):
    add_box      imagen, x1, y1, x2, y2   añade un cuadro de clase 0 (camaron)
    delete_line  imagen, line             elimina la línea `line` de la etiqueta ORIGINAL (índice desde 0)
    include      imagen, split            añade a la lista una imagen excluida (p. ej. etiqueta vacía), desde el ZIP

Uso (busca shrimp_roboflow_v4 en la carpeta de datos externa; ver data_paths.py):
    python training/scripts/apply_label_review.py --zip RUTA.zip
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from data_paths import find_in_data_dir

DATASET_ID = "shrimp_roboflow_v4"
SPLITS = {"train": "train", "valid": "val", "test": "test"}
DUPLICATE_IOU = 0.9


def read_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def to_xyxy(line: str) -> tuple[float, float, float, float]:
    _, cx, cy, w, h = (float(v) for v in line.split())
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def iou(a, b) -> float:
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def box_line(x1: float, y1: float, x2: float, y2: float, width: int, height: int) -> str:
    x1, x2 = sorted((max(0.0, min(width, x1)), max(0.0, min(width, x2))))
    y1, y2 = sorted((max(0.0, min(height, y1)), max(0.0, min(height, y2))))
    if x2 - x1 < 2 or y2 - y1 < 2:
        raise ValueError("cuadro demasiado pequeño")
    return (f"0 {(x1 + x2) / 2 / width:.6f} {(y1 + y2) / 2 / height:.6f} "
            f"{(x2 - x1) / width:.6f} {(y2 - y1) / height:.6f}")


def link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def validate(output: Path) -> dict:
    """Comprueba listas, imágenes y etiquetas de la copia revisada."""
    report = {"splits": {}, "errors": [], "possible_duplicates": []}
    for split, yolo in SPLITS.items():
        entries = read_lines(output / f"grouped_{yolo}.txt")
        objects = 0
        for entry in entries:
            image = output / entry.removeprefix("./")
            label = output / "labels" / f"{image.stem}.txt"
            if not image.is_file():
                report["errors"].append(f"falta imagen {entry}")
                continue
            if not label.is_file():
                report["errors"].append(f"falta etiqueta {label.name}")
                continue
            boxes = []
            for number, line in enumerate(read_lines(label)):
                values = line.split()
                try:
                    coords = [float(v) for v in values[1:]]
                except ValueError:
                    coords = []
                if values[0] != "0" or len(coords) != 4 or not all(0 <= v <= 1 for v in coords) \
                        or coords[2] <= 0 or coords[3] <= 0:
                    report["errors"].append(f"línea inválida {label.name}:{number}: {line}")
                    continue
                boxes.append(to_xyxy(line))
            if not boxes:
                report["errors"].append(f"etiqueta sin objetos en lista {label.name}")
            for a, b in itertools.combinations(boxes, 2):
                if iou(a, b) >= DUPLICATE_IOU:
                    report["possible_duplicates"].append(label.name)
            objects += len(boxes)
        report["splits"][split] = {"images": len(entries), "objects": objects,
                                   "unique_images": len(set(entries)) == len(entries)}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path,
                        help=f"Salida de prepare_shrimp_dataset.py (por defecto <carpeta de datos>/{DATASET_ID})")
    parser.add_argument("--data-dir", help="Carpeta de datos (por defecto SMART_SHRIMP_DATA_DIR o ..\\dataset).")
    parser.add_argument("--zip", type=Path, required=True, help="ZIP original (solo lectura, para imágenes excluidas).")
    parser.add_argument("--output", type=Path, help="Por defecto <source>/detect_grouped_reviewed_v1")
    args = parser.parse_args(argv)

    source = find_in_data_dir(args.source or DATASET_ID, args.data_dir)
    output = (args.output or source / "detect_grouped_reviewed_v1").resolve()
    detect = source / "detect"
    corrections_path = output / "review" / "corrections.csv"
    if output == detect or detect in output.parents:
        raise SystemExit("La salida no puede estar dentro de detect/.")
    if not corrections_path.is_file():
        raise SystemExit(f"Falta {corrections_path}")
    inventory = {row["image"]: row for row in csv.DictReader(open(source / "audit" / "images.csv", encoding="utf-8"))}

    # Solo se regeneran images/, labels/ y las listas; review/ se conserva.
    for name in ("images", "labels"):
        if (output / name).exists():
            shutil.rmtree(output / name)
        (output / name).mkdir(parents=True)

    corrections = list(csv.DictReader(open(corrections_path, encoding="utf-8")))
    split_entries = {split: read_lines(detect / f"grouped_{yolo}.txt") for split, yolo in SPLITS.items()}
    included = [c for c in corrections if c["action"] == "include"]
    for c in included:
        entry = f"./images/{c['image']}"
        if entry in itertools.chain.from_iterable(split_entries.values()):
            raise SystemExit(f"include duplicado: {c['image']}")
        if inventory[c["image"]]["grouped_split"] != c["split"]:
            raise SystemExit(f"{c['image']} pertenece a {inventory[c['image']]['grouped_split']}, no a {c['split']}")
        split_entries[c["split"]].append(entry)

    labels: dict[str, list[str]] = {}
    sizes: dict[str, tuple[int, int]] = {}
    with zipfile.ZipFile(args.zip) as archive:
        for entries in split_entries.values():
            for entry in entries:
                name = entry.removeprefix("./images/")
                stem = Path(name).stem
                src_image = detect / "images" / name
                if src_image.is_file():
                    link_or_copy(src_image, output / "images" / name)
                    labels[name] = read_lines(detect / "labels" / f"{stem}.txt")
                else:  # imagen excluida en la preparación (etiqueta vacía): se extrae del ZIP sin modificarla
                    row = inventory[name]
                    (output / "images" / name).write_bytes(archive.read(f"{row['original_split']}/images/{name}"))
                    labels[name] = []
                with Image.open(output / "images" / name) as img:
                    sizes[name] = img.size

    original = {name: list(lines) for name, lines in labels.items()}
    deleted: dict[str, set[int]] = defaultdict(set)
    added: dict[str, list[str]] = defaultdict(list)
    counts = Counter()
    for c in corrections:
        name = c["image"]
        if name not in labels:
            raise SystemExit(f"Corrección sobre una imagen fuera de las listas: {name}")
        if c["action"] == "delete_line":
            line = int(c["line"])
            if not 0 <= line < len(original[name]):
                raise SystemExit(f"Línea {line} inexistente en {name}")
            deleted[name].add(line)
            counts["delete_line"] += 1
        elif c["action"] == "add_box":
            width, height = sizes[name]
            added[name].append(box_line(*(float(c[k]) for k in ("x1", "y1", "x2", "y2")), width, height))
            counts["add_box"] += 1
        elif c["action"] != "include":
            raise SystemExit(f"Acción desconocida: {c['action']}")
        counts["include"] += c["action"] == "include"

    modified = set()
    for name, lines in labels.items():
        new = [line for i, line in enumerate(lines) if i not in deleted[name]] + added[name]
        if new != original[name]:
            modified.add(name)
        (output / "labels" / f"{Path(name).stem}.txt").write_text("\n".join(new) + ("\n" if new else ""),
                                                                   encoding="utf-8")
    for split, yolo in SPLITS.items():
        (output / f"grouped_{yolo}.txt").write_text("\n".join(sorted(split_entries[split])) + "\n", encoding="utf-8")
    (output / "data.yaml").write_text(
        "# SMART SHRIMP detect: partición agrupada con etiquetas revisadas (review/).\n"
        "train: grouped_train.txt\nval: grouped_val.txt\ntest: grouped_test.txt\nnc: 1\nnames:\n  0: camaron\n",
        encoding="utf-8")

    report = validate(output)
    report["corrections"] = dict(counts)
    report["labels_modified"] = len(modified)
    report["labels_modified_by_split"] = dict(Counter(inventory[n]["grouped_split"] for n in modified))
    (output / "review" / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                        encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "possible_duplicates"}, ensure_ascii=False, indent=2))
    print(f"Posibles duplicados (IoU ≥ {DUPLICATE_IOU}): {len(report['possible_duplicates'])}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
