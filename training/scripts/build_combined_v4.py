"""Construye shrimp_combined_v4: shrimp_combined_v3 + las fotos propias en bandeja de acero (camarones_bandeja_v1).

- No modifica v3 ni camarones_bandeja_v1. Las imágenes de v3 se enlazan (enlace duro, o copia si no es posible).
  Las de bandeja (4064x3048) se guardan reducidas a BANDEJA_MAX_SIDE px de lado mayor: se entrena a 640 y así
  cargan más rápido. Las etiquetas YOLO son relativas al tamaño de la imagen y no cambian.
- v3 conserva su partición (train/val/test) para comparar las métricas con las mismas imágenes.
- Las fotos de bandeja van a una partición por SESIÓN (misma disposición de camarones), nunca foto a foto.
  Sesiones (revisión visual del 15/11/2026; nombre = hora de la foto):
    train: 112706 (3 camarones), 1154xx (9 en fila, más 2 fotos sin camarones: alfombra y mesa),
           115441-115458 (bolsa negra y mano), 1155xx (montón con papel, frasco y celular),
           115650-115712 (3-4 separados)
    val:   115631-115636 (6 separados, otra disposición)
    test:  115611-115620 (montón de 6) y 115731-115736 (1 camarón y bandeja vacía)
  Todas son del mismo día, la misma bandeja y la misma mesa: test mide otra disposición, no otra cámara ni lugar.
- Cada foto de bandeja de train se repite NEW_TRAIN_REPEAT veces para que no se diluya entre las ~6.800 de v3.

Uso:
    python training/scripts/build_combined_v4.py --data-dir "C:\\ruta\\dataset"
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from PIL import Image

NAME = "shrimp_combined_v4"
BASE = "shrimp_combined_v3"
NEW = "camarones_bandeja_v1"
NEW_PREFIX = "bj_"
NEW_TRAIN_REPEAT = 6
BANDEJA_MAX_SIDE = 1600

SPLIT_RULES = [  # (partición, sesión, patrón sobre la hora de la foto: foto_img_20261115_HHMMSS_...)
    ("test", "monton_6", r"^1156(11|18|20)$"),
    ("test", "uno_y_vacia", r"^1157(31|36)$"),
    ("val", "seis_separados", r"^1156(31|34|36)$"),
    ("train", "tres_inicial", r"^112706$"),
    ("train", "nueve_en_fila_y_vacias", r"^1154(04|06|08|15|18)$"),
    ("train", "bolsa_y_mano", r"^1154(41|58)$"),
    ("train", "monton_con_objetos", r"^1155(15|17|22|34|36)$"),
    ("train", "tres_cuatro_separados", r"^(1156(50|52|53)|115712)$"),
]
BASE_LISTS = ("train", "val", "test", "test_baldosa", "val_baldosa", "train_baldosa",
              "v2_test_old", "v2_test_new", "v2_val", "v2_test")


def link(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def session_of(stem: str) -> tuple[str, str]:
    match = re.match(r"^foto_img_\d{8}_(\d{6})_", stem)
    if match:
        for split, session, pattern in SPLIT_RULES:
            if re.match(pattern, match.group(1)):
                return split, session
    raise SystemExit(f"Foto de bandeja sin sesión asignada: {stem}. Añádela a SPLIT_RULES.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, required=True, help="Carpeta dataset (contiene v3 y las fotos de bandeja)")
    args = parser.parse_args(argv)
    base, new, out = args.data_dir / BASE, args.data_dir / NEW, args.data_dir / NAME
    if out.exists():
        raise SystemExit(f"{out} ya existe; no se sobrescribe.")
    for required in [base / f"{name}.txt" for name in BASE_LISTS] + [new / "labels", new / "images"]:
        if not required.exists():
            raise SystemExit(f"Falta {required}")
    (out / "images").mkdir(parents=True)
    (out / "labels").mkdir()

    # 1. v3 tal cual (mismas particiones y listas de evaluación, con prefijo v3_).
    names = set()
    for listing in BASE_LISTS:
        for line in (base / f"{listing}.txt").read_text(encoding="utf-8").split():
            names.add(Path(line).name)
        shutil.copy2(base / f"{listing}.txt", out / f"v3_{listing}.txt")
    for name in sorted(names):
        link(base / "images" / name, out / "images" / name)
        label = base / "labels" / (Path(name).stem + ".txt")
        if label.exists():
            shutil.copy2(label, out / "labels" / label.name)
    lists = {split: (base / f"{split}.txt").read_text(encoding="utf-8").split() for split in ("train", "val", "test")}

    # 2. Fotos de bandeja, por sesión.
    rows, new_lists = [], {"train": [], "val": [], "test": []}
    for image_path in sorted((new / "images").glob("*.jpg")):
        split, session = session_of(image_path.stem)
        label = new / "labels" / f"{image_path.stem}.txt"
        objects = len([line for line in label.read_text(encoding="utf-8").splitlines() if line.strip()])
        stem0 = f"{NEW_PREFIX}{image_path.stem}"
        with Image.open(image_path) as image:
            image.thumbnail((BANDEJA_MAX_SIDE, BANDEJA_MAX_SIDE), Image.LANCZOS)
            image.save(out / "images" / f"{stem0}.jpg", quality=92)
        repeats = NEW_TRAIN_REPEAT if split == "train" else 1
        for r in range(repeats):
            stem = stem0 + (f"_r{r}" if r else "")
            if r:
                link(out / "images" / f"{stem0}.jpg", out / "images" / f"{stem}.jpg")
            shutil.copy2(label, out / "labels" / f"{stem}.txt")
            new_lists[split].append(f"./images/{stem}.jpg")
        rows.append([image_path.name, session, split, f"x{repeats}", objects])
    for split in lists:
        lists[split] += new_lists[split]

    for split, items in lists.items():
        (out / f"{split}.txt").write_text("\n".join(items) + "\n", encoding="utf-8")
    for split, items in new_lists.items():  # solo las de bandeja sin repeticiones, para evaluar aparte
        unique = [i for i in items if not re.search(r"_r\d+\.jpg$", i)]
        (out / f"{split}_bandeja.txt").write_text("\n".join(unique) + "\n", encoding="utf-8")

    header = "nc: 1\nnames:\n  0: camaron\n"
    (out / "data.yaml").write_text("# SMART SHRIMP detect v4: v3 + fotos propias en bandeja de acero\n"
                                   "train: train.txt\nval: val.txt\ntest: test.txt\n" + header, encoding="utf-8")
    evals = {"test_bandeja": "test_bandeja.txt", "val_bandeja": "val_bandeja.txt",
             "test_baldosa": "v3_test_baldosa.txt", "test_old": "v3_v2_test_old.txt",
             "test_new": "v3_v2_test_new.txt", "test_all": "test.txt"}
    for key, listing in evals.items():
        (out / f"data_{key}.yaml").write_text(f"# solo evaluación: {key}\ntrain: train.txt\nval: {listing}\n" + header,
                                               encoding="utf-8")
    with open(out / "new_images.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["imagen", "sesion", "particion", "repeticiones", "camarones"])
        writer.writerows(rows)
    summary = {split: {"imagenes_v3": len(lists[split]) - len(new_lists[split]), "imagenes_bandeja": len(new_lists[split]),
                       "bandeja_unicas": sum(1 for r in rows if r[2] == split),
                       "camarones_bandeja": sum(r[4] for r in rows if r[2] == split)} for split in lists}
    (out / "manifest.json").write_text(json.dumps({
        "dataset_id": NAME, "generated_at": datetime.now().isoformat(timespec="seconds"), "base": str(base),
        "new": str(new), "new_train_repeat": NEW_TRAIN_REPEAT, "bandeja_max_side": BANDEJA_MAX_SIDE,
        "sessions": [{"split": s, "session": n, "pattern": p} for s, n, p in SPLIT_RULES], "splits": summary,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    for split, data in summary.items():
        print(f"{split:5s}: {data['imagenes_v3']} de v3 + {data['bandeja_unicas']} de bandeja "
              f"({data['imagenes_bandeja']} con repeticiones, {data['camarones_bandeja']} camarones)")
    print(f"Listo: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
