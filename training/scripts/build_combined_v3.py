"""Construye shrimp_combined_v3: shrimp_combined_v2 + las fotos nuevas en baldosa (camarones_nuevos_v1, corregidas).

- No modifica v2 ni camarones_nuevos_v1: las imágenes se enlazan (enlace duro, o copia si no es posible) y las
  etiquetas se copian a la carpeta nueva.
- v2 conserva su partición (train/val/test), así las métricas anteriores se comparan con las mismas imágenes.
- Las imágenes nuevas van a una partición por SESIÓN de captura, nunca foto a foto: varias fotos son la misma
  escena con un camarón movido y los fotogramas de un video son casi iguales; mezclarlas daría métricas falsas.
  Sesiones (revisión visual del 14/11/2026):
    train: sesión grande en baldosa (camaron1, 3-15, 18), primeros planos (camaron2, camaron 5) y video 2
    val:   serie 1c-7c y camaron16, 17, 19 (pocos camarones, otra toma)
    test:  video 1 (21 fotogramas, ~10 camarones amontonados en cada uno)
  Todas son del mismo día y la misma baldosa: test mide montones y video, no otras superficies.
- Cada imagen nueva de train se repite NEW_TRAIN_REPEAT veces (enlaces con otro nombre) para que no se diluya
  entre las ~6.600 de v2.

Uso:
    python training/scripts/build_combined_v3.py --data-dir "C:\\ruta\\dataset"
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

NAME = "shrimp_combined_v3"
BASE = "shrimp_combined_v2"
NEW = "camarones_nuevos_v1"
NEW_PREFIX = "nv2_"
NEW_TRAIN_REPEAT = 4

SPLIT_RULES = [  # (partición, sesión, patrón sobre el nombre de la imagen nueva)
    ("test", "video_1", r"^video_de_camaron_1_"),
    ("train", "video_2", r"^video_de_camaron_2_"),
    ("val", "fotos_serie_c", r"^foto_(\dc|camaron1[679]|camaron_19)$"),
    ("train", "fotos_primer_plano", r"^foto_camaron(2|_5)$"),
    ("train", "fotos_sesion_baldosa", r"^foto_camaron(1|[3-9]|1[0-5]|_18)$"),
]


def link(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def session_of(stem: str) -> tuple[str, str]:
    for split, session, pattern in SPLIT_RULES:
        if re.match(pattern, stem):
            return split, session
    raise SystemExit(f"Imagen nueva sin sesión asignada: {stem}. Añádela a SPLIT_RULES.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, required=True, help="Carpeta dataset (contiene v2 y las fotos nuevas)")
    args = parser.parse_args(argv)
    base, new, out = args.data_dir / BASE, args.data_dir / NEW, args.data_dir / NAME
    if out.exists():
        raise SystemExit(f"{out} ya existe; no se sobrescribe.")
    for required in (base / "train.txt", new / "labels", new / "images"):
        if not required.exists():
            raise SystemExit(f"Falta {required}")
    (out / "images").mkdir(parents=True)
    (out / "labels").mkdir()

    lists: dict[str, list[str]] = {"train": [], "val": [], "test": []}
    # 1. v2 tal cual (mismas particiones y listas de evaluación).
    names = set()
    for listing in ("train", "val", "test", "train_new", "val_new", "test_new", "train_old", "val_old", "test_old"):
        for line in (base / f"{listing}.txt").read_text(encoding="utf-8").split():
            names.add(Path(line).name)
        shutil.copy2(base / f"{listing}.txt", out / f"v2_{listing}.txt")
    for name in sorted(names):
        link(base / "images" / name, out / "images" / name)
        label = base / "labels" / (Path(name).stem + ".txt")
        if label.exists():
            shutil.copy2(label, out / "labels" / label.name)
    for split in lists:
        lists[split] += (base / f"{split}.txt").read_text(encoding="utf-8").split()

    # 2. Fotos nuevas, por sesión.
    rows, new_lists = [], {"train": [], "val": [], "test": []}
    for image in sorted((new / "images").glob("*.jpg")):
        split, session = session_of(image.stem)
        label = new / "labels" / f"{image.stem}.txt"
        objects = len([line for line in label.read_text(encoding="utf-8").splitlines() if line.strip()])
        repeats = NEW_TRAIN_REPEAT if split == "train" else 1
        for r in range(repeats):
            stem = f"{NEW_PREFIX}{image.stem}" + (f"_r{r}" if r else "")
            link(image, out / "images" / f"{stem}.jpg")
            shutil.copy2(label, out / "labels" / f"{stem}.txt")
            new_lists[split].append(f"./images/{stem}.jpg")
        rows.append([image.name, session, split, f"x{repeats}", objects])
    for split in lists:
        lists[split] += new_lists[split]

    for split, items in lists.items():
        (out / f"{split}.txt").write_text("\n".join(items) + "\n", encoding="utf-8")
    for split, items in new_lists.items():  # solo las nuevas sin repeticiones, para evaluar aparte
        unique = [i for i in items if not re.search(r"_r\d+\.jpg$", i)]
        (out / f"{split}_baldosa.txt").write_text("\n".join(unique) + "\n", encoding="utf-8")

    header = "nc: 1\nnames:\n  0: camaron\n"
    (out / "data.yaml").write_text("# SMART SHRIMP detect v3: v2 + fotos nuevas en baldosa\n"
                                   "train: train.txt\nval: val.txt\ntest: test.txt\n" + header, encoding="utf-8")
    evals = {"test_baldosa": "test_baldosa.txt", "val_baldosa": "val_baldosa.txt", "test_old": "v2_test_old.txt",
             "test_new": "v2_test_new.txt", "test_all": "test.txt"}
    for key, listing in evals.items():
        (out / f"data_{key}.yaml").write_text(f"# solo evaluación: {key}\ntrain: train.txt\nval: {listing}\n" + header,
                                               encoding="utf-8")
    with open(out / "new_images.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["imagen", "sesion", "particion", "repeticiones", "camarones"])
        writer.writerows(rows)
    summary = {split: {"imagenes_v2": len(lists[split]) - len(new_lists[split]), "imagenes_nuevas": len(new_lists[split]),
                       "nuevas_unicas": sum(1 for r in rows if r[2] == split),
                       "camarones_nuevos": sum(r[4] for r in rows if r[2] == split)} for split in lists}
    (out / "manifest.json").write_text(json.dumps({
        "dataset_id": NAME, "generated_at": datetime.now().isoformat(timespec="seconds"), "base": str(base),
        "new": str(new), "new_train_repeat": NEW_TRAIN_REPEAT,
        "sessions": [{"split": s, "session": n, "pattern": p} for s, n, p in SPLIT_RULES], "splits": summary,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    for split, data in summary.items():
        print(f"{split:5s}: {data['imagenes_v2']} de v2 + {data['nuevas_unicas']} nuevas "
              f"({data['imagenes_nuevas']} con repeticiones, {data['camarones_nuevos']} camarones)")
    print(f"Listo: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
