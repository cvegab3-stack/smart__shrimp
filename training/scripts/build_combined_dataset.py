"""Construye una versión nueva del dataset de detección "camaron" combinando el dataset revisado anterior con
el ZIP `Shrimp.v1i.yolov8.zip` (Roboflow Universe shrimp-s4lfv/shrimp-nwcf0 v1, CC BY 4.0).

- No modifica el ZIP ni el dataset anterior: las imágenes se enlazan (enlace duro, o copia si no es posible) y las
  etiquetas se copian o se escriben de nuevo en la carpeta de salida.
- El dataset anterior conserva su partición agrupada (train/val/test), así las métricas en imágenes anteriores se
  comparan con las mismas imágenes.
- Las imágenes nuevas se agrupan por sesión (escena revisada visualmente y marcas de tiempo a ≤ 60 s) y cada
  sesión va entera a una sola partición. Las variantes de color de una misma foto comparten grupo.
- Los polígonos del ZIP se convierten a cuadros (mínimo/máximo de los vértices); no se añaden ni se mueven objetos.
- Se excluyen las fotos fuente con errores de anotación detectados en la revisión (ver EXCLUDED).

Uso:
    python training/scripts/build_combined_dataset.py --zip C:\\ruta\\Shrimp.v1i.yolov8.zip `
        --base C:\\ruta\\dataset\\shrimp_roboflow_v4\\detect_grouped_reviewed_v1 --output C:\\ruta\\dataset
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

NAME = "shrimp_combined_v2"
NEW_PREFIX = "nv1_"
# Repeticiones de cada imagen nueva de train (archivo enlazado con otro nombre) para que las superficies nuevas
# no queden diluidas entre las ~6.000 imágenes anteriores.
NEW_TRAIN_REPEAT = 2

# Fotos fuente excluidas tras la revisión visual de las 492 imágenes (todas sus variantes).
EXCLUDED = {
    "IMG_20240317_100339": "polígono extra que cubre toda la imagen (w=0,995, h=1,0)",
    "IMG_20240317_095248": "camarón parcial sin anotar en la esquina inferior izquierda",
    "b-16-": "camarón parcial sin anotar en la esquina inferior derecha",
    "b-19-": "camarón parcial sin anotar en la esquina inferior derecha",
}

# Sesiones de captura identificadas en la revisión visual (misma superficie, cámara e iluminación).
SESSION_PATTERNS = [
    ("green_plastic", r"^16586496\d+$"),
    ("tile_dark_object", r"^(1|2|[G-L]-\d-)$"),
    ("tile_shadow", r"^[A-F]-\d-$"),
    ("tile_lights", r"^[M-S]-\d-$"),
    ("white_tile_b", r"^b-(1[6-9]|2\d)-$"),
    ("multi_shrimp", r"^(U-G.*|ej.*)$"),
    ("wall_shadow", r"^(heudh|ido|iiop|jd|ojdpo|ub)$"),
    ("studio_white", r"^(b-([3-9]\d|1\d\d)-|shrimp\d+)$"),
]
TIMESTAMP = re.compile(r"^IMG_(\d{8}_\d{6})$")
TIME_GAP_SECONDS = 60

# Asignación de sesiones completas. Las fotos de estudio son independientes entre sí y se reparten por fuente.
SESSION_SPLIT = {
    "green_plastic": "train", "tile_dark_object": "train", "white_tile_b": "train", "wall_shadow": "train",
    "tile_shadow": "val", "tile_lights": "test", "multi_shrimp": "test",
    "img_20240317_095100": "train", "img_20240317_095527": "val", "img_20240317_095742": "train",
    "img_20240317_100015": "test", "img_20240317_100229": "train",
}
STUDIO_FRACTIONS = {"val": 0.15, "test": 0.15}
SEED = 0


def source_of(stem: str) -> str:
    return re.split(r"_(?:jpg|jpeg|png)\.rf\.", stem)[0]


def assign_sessions(sources: list[str]) -> dict[str, str]:
    session = {}
    stamps = []
    for src in sources:
        match = TIMESTAMP.match(src)
        if match:
            stamps.append((datetime.strptime(match.group(1), "%Y%m%d_%H%M%S"), src))
            continue
        for name, pattern in SESSION_PATTERNS:
            if re.match(pattern, src):
                session[src] = name if name != "studio_white" else f"studio_{src}"
                break
        else:
            raise SystemExit(f"La fuente '{src}' no corresponde a ninguna sesión conocida; revise SESSION_PATTERNS.")
    current, previous = None, None
    for stamp, src in sorted(stamps):
        if previous is None or (stamp - previous).total_seconds() > TIME_GAP_SECONDS:
            current = f"img_{src[4:].lower()}"
        session[src] = current
        previous = stamp
    return session


def split_of(session: str, studio: dict[str, str]) -> str:
    if session.startswith("studio_"):
        return studio[session]
    if session not in SESSION_SPLIT:
        raise SystemExit(f"La sesión '{session}' no tiene partición asignada en SESSION_SPLIT.")
    return SESSION_SPLIT[session]


def link(src: Path, dst: Path) -> str:
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


def polygon_to_box(line: str) -> str:
    parts = line.split()
    values = [float(v) for v in parts[1:]]
    if len(values) == 4:
        return f"0 {' '.join(parts[1:])}"
    xs, ys = values[0::2], values[1::2]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return f"0 {(x0 + x1) / 2:.6f} {(y0 + y1) / 2:.6f} {x1 - x0:.6f} {y1 - y0:.6f}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True, help="Carpeta detect_grouped_reviewed_v1 (solo lectura).")
    parser.add_argument("--output", type=Path, required=True, help="Carpeta de datos donde crear " + NAME)
    args = parser.parse_args(argv)

    out = args.output / NAME
    if out.exists():
        raise SystemExit(f"{out} ya existe; no se sobrescribe. Use otra carpeta de salida o un nombre nuevo.")
    base_lists = {"train": "grouped_train.txt", "val": "grouped_val.txt", "test": "grouped_test.txt"}
    for listing in base_lists.values():
        if not (args.base / listing).is_file():
            raise SystemExit(f"Falta {args.base / listing}")

    zip_sha = hashlib.sha256(args.zip.read_bytes()).hexdigest()
    (out / "images").mkdir(parents=True)
    (out / "labels").mkdir()
    lists = {f"{split}_{part}": [] for split in ("train", "val", "test") for part in ("old", "new")}
    link_modes: dict[str, int] = {}

    # 1. Dataset anterior: misma partición, mismas imágenes y etiquetas.
    old_objects = {}
    for split, listing in base_lists.items():
        count = 0
        for rel in (args.base / listing).read_text(encoding="utf-8").split():
            image = (args.base / rel).resolve()
            label = args.base / "labels" / f"{image.stem}.txt"
            if not image.is_file() or not label.is_file():
                raise SystemExit(f"Falta la imagen o la etiqueta de {rel}")
            mode = link(image, out / "images" / image.name)
            link_modes[mode] = link_modes.get(mode, 0) + 1
            text = label.read_text(encoding="utf-8")
            (out / "labels" / label.name).write_text(text, encoding="utf-8")
            count += len([line for line in text.splitlines() if line.strip()])
            lists[f"{split}_old"].append(f"./images/{image.name}")
        old_objects[split] = count

    # 2. ZIP nuevo: validar, agrupar por sesión y convertir polígonos a cuadros.
    rows = []
    with zipfile.ZipFile(args.zip) as archive:
        if archive.testzip() is not None:
            raise SystemExit("El ZIP tiene archivos dañados.")
        names = set(archive.namelist())
        images = sorted(n for n in names if n.startswith("train/images/") and n.lower().endswith(".jpg"))
        by_source: dict[str, list[str]] = {}
        for name in images:
            by_source.setdefault(source_of(PurePosixPath(name).stem), []).append(name)
        sessions = assign_sessions(sorted(by_source))
        studio = sorted(s for s in set(sessions.values()) if s.startswith("studio_") and
                        not any(sessions[src] == s and src in EXCLUDED for src in by_source))
        random.Random(SEED).shuffle(studio)
        n_val = round(len(studio) * STUDIO_FRACTIONS["val"])
        n_test = round(len(studio) * STUDIO_FRACTIONS["test"])
        studio_split = {s: "val" for s in studio[:n_val]}
        studio_split.update({s: "test" for s in studio[n_val:n_val + n_test]})
        studio_split.update({s: "train" for s in studio[n_val + n_test:]})

        for src in sorted(by_source):
            variants = by_source[src]
            session = sessions[src]
            if src in EXCLUDED:
                for name in variants:
                    rows.append([PurePosixPath(name).name, src, session, "", "excluded", EXCLUDED[src], 0])
                continue
            split = split_of(session, studio_split)
            # En val/test, una sola variante por foto para no triplicar su peso (igual que el dataset anterior).
            used = variants if split == "train" else variants[:1]
            for name in variants:
                stem = PurePosixPath(name).stem
                label_name = f"train/labels/{stem}.txt"
                if label_name not in names:
                    raise SystemExit(f"{name} no tiene etiqueta en el ZIP.")
                lines = [line for line in archive.read(label_name).decode("utf-8").splitlines() if line.strip()]
                if any(line.split()[0] != "0" for line in lines):
                    raise SystemExit(f"{label_name} tiene clases distintas de 0.")
                if name not in used:
                    rows.append([PurePosixPath(name).name, src, session, split, "variant_not_used", "", len(lines)])
                    continue
                boxes = "\n".join(polygon_to_box(line) for line in lines) + "\n"
                data = archive.read(name)
                repeats = NEW_TRAIN_REPEAT if split == "train" else 1
                for r in range(repeats):
                    new_stem = f"{NEW_PREFIX}{stem}" if r == 0 else f"{NEW_PREFIX}r{r}_{stem}"
                    image_path = out / "images" / f"{new_stem}.jpg"
                    if r == 0:
                        image_path.write_bytes(data)
                    else:
                        link(out / "images" / f"{NEW_PREFIX}{stem}.jpg", image_path)
                    (out / "labels" / f"{new_stem}.txt").write_text(boxes, encoding="utf-8")
                    lists[f"{split}_new"].append(f"./images/{new_stem}.jpg")
                rows.append([PurePosixPath(name).name, src, session, split, "used", f"x{repeats}", len(lines)])

    # 3. Listas, data.yaml y manifiesto.
    for key, items in lists.items():
        (out / f"{key}.txt").write_text("\n".join(items) + "\n", encoding="utf-8")
    for split in ("train", "val", "test"):
        (out / f"{split}.txt").write_text("\n".join(lists[f"{split}_old"] + lists[f"{split}_new"]) + "\n",
                                          encoding="utf-8")
    header = "# SMART SHRIMP detect: {}\n"
    (out / "data.yaml").write_text(header.format("dataset anterior revisado + Shrimp.v1i (superficies secas)") +
                                   "train: train.txt\nval: val.txt\ntest: test.txt\nnc: 1\nnames:\n  0: camaron\n",
                                   encoding="utf-8")
    for split in ("val", "test"):
        for part in ("old", "new"):
            (out / f"data_{split}_{part}.yaml").write_text(
                header.format(f"solo evaluación: {split} {part}") +
                f"train: train.txt\nval: {split}_{part}.txt\nnc: 1\nnames:\n  0: camaron\n", encoding="utf-8")
        (out / f"data_{split}_all.yaml").write_text(
            header.format(f"solo evaluación: {split} completo") +
            f"train: train.txt\nval: {split}.txt\nnc: 1\nnames:\n  0: camaron\n", encoding="utf-8")

    with open(out / "new_images.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["zip_image", "source", "session", "split", "status", "note", "objects"])
        writer.writerows(rows)

    def objects_in(listing):
        return sum(len([line for line in (out / "labels" / f"{Path(p).stem}.txt").read_text().splitlines() if line.strip()])
                   for p in listing)

    summary = {
        "dataset_id": NAME,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_dataset": str(args.base),
        "new_zip": {"path": str(args.zip), "sha256": zip_sha, "license": "CC BY 4.0",
                    "source": "https://universe.roboflow.com/shrimp-s4lfv/shrimp-nwcf0/dataset/1"},
        "excluded_sources": EXCLUDED,
        "new_train_repeat": NEW_TRAIN_REPEAT,
        "image_link_modes": link_modes,
        "splits": {key: {"images": len(items), "objects": objects_in(items)} for key, items in lists.items()},
        "new_sessions": {split: sorted({r[2] for r in rows if r[3] == split and r[4] == "used"
                                        and not r[2].startswith("studio_")}) +
                         [f"{sum(1 for s, v in studio_split.items() if v == split)} fotos de estudio"]
                         for split in ("train", "val", "test")},
    }
    (out / "manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
