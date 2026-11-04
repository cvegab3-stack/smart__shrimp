"""Evalúa uno o varios detectores "camaron" con las mismas particiones de un dataset combinado.

Para cada modelo y subconjunto (por defecto val_old, val_new, test_old, test_new de shrimp_combined_v2):
  - métricas de Ultralytics (precisión, recall, mAP50, mAP50-95) con conf=0.001, como en el entrenamiento;
  - métricas en el punto de operación de la aplicación (--conf, 0.5 por defecto): TP/FP/FN con IoU >= 0.5,
    error de conteo por imagen y porcentaje de imágenes con el conteo exacto;
  - falsos positivos sobre superficies sin camarones: recortes de val/test que no tocan ningún cuadro anotado
    (con margen) ni el borde de la imagen. Se generan una sola vez en <dataset>/negatives_eval y se reutilizan,
    así todos los modelos se comparan con los mismos recortes.

Uso:
    python training/scripts/evaluate_detector.py --dataset C:\\ruta\\dataset\\shrimp_combined_v2 `
        --model actual=models/detector/best.pt --model candidato=training/runs/detector/<run>/weights/best.pt `
        --out training/runs/detector/eval/<nombre>
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

from data_paths import REPO_ROOT

SUBSETS = ["val_old", "val_new", "test_old", "test_new"]
IOU_MATCH = 0.5
NEG_SIZES = (320, 256, 192, 160)
NEG_MARGIN = 0.06   # fracción del lado de la imagen añadida alrededor de cada cuadro anotado
NEG_BORDER = 16     # píxeles libres respecto al borde (los fragmentos en el borde no siempre están anotados)


def resolve(path_value: str | Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def read_boxes(label: Path, width: int, height: int) -> list[tuple[float, float, float, float]]:
    boxes = []
    for line in label.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        x, y, w, h = (float(v) for v in parts[1:])
        boxes.append(((x - w / 2) * width, (y - h / 2) * height, (x + w / 2) * width, (y + h / 2) * height))
    return boxes


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def subset_images(dataset: Path, subset: str) -> list[Path]:
    return [(dataset / rel).resolve() for rel in (dataset / f"{subset}.txt").read_text(encoding="utf-8").split()]


def build_negatives(dataset: Path, pending: set[str]) -> Path:
    """Recorta, de cada imagen de val/test, el mayor cuadrado sin camarones anotados. Determinista."""
    from PIL import Image

    out = dataset / "negatives_eval"
    if (out / "index.csv").is_file():
        return out
    out.mkdir(exist_ok=True)
    rows = []
    for subset in SUBSETS:
        for image_path in subset_images(dataset, subset):
            if image_path.name in pending:
                continue
            with Image.open(image_path) as image:
                image = image.convert("RGB")
                width, height = image.size
                mx, my = NEG_MARGIN * width, NEG_MARGIN * height
                boxes = [(x0 - mx, y0 - my, x1 + mx, y1 + my)
                         for x0, y0, x1, y1 in read_boxes(dataset / "labels" / f"{image_path.stem}.txt", width, height)]
                found = None
                for size in NEG_SIZES:
                    for top in range(NEG_BORDER, height - NEG_BORDER - size + 1, 16):
                        for left in range(NEG_BORDER, width - NEG_BORDER - size + 1, 16):
                            crop = (left, top, left + size, top + size)
                            if all(crop[2] <= b[0] or crop[0] >= b[2] or crop[3] <= b[1] or crop[1] >= b[3]
                                   for b in boxes):
                                found = crop
                                break
                        if found:
                            break
                    if found:
                        break
                if not found:
                    continue
                name = f"{subset}__{image_path.stem}.png"
                image.crop(found).save(out / name)
                rows.append([name, subset, image_path.name, *found])
    with open(out / "index.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["crop", "subset", "image", "left", "top", "right", "bottom"])
        writer.writerows(rows)
    return out


def operating_point(model, images: list[Path], dataset: Path, conf: float, device) -> dict:
    tp = fp = fn = exact = 0
    abs_err = 0
    images_with_fp = 0
    for start in range(0, len(images), 16):
        batch = images[start:start + 16]
        results = model.predict([str(p) for p in batch], conf=conf, imgsz=640, device=device, verbose=False)
        for image_path, result in zip(batch, results):
            height, width = result.orig_shape
            gts = read_boxes(dataset / "labels" / f"{image_path.stem}.txt", width, height)
            preds = sorted(((float(b.conf[0]), [float(v) for v in b.xyxy[0].tolist()]) for b in result.boxes),
                           reverse=True)
            used = set()
            image_fp = 0
            for _, box in preds:
                best, best_iou = None, IOU_MATCH
                for k, gt in enumerate(gts):
                    if k not in used and iou(box, gt) >= best_iou:
                        best, best_iou = k, iou(box, gt)
                if best is None:
                    image_fp += 1
                else:
                    used.add(best)
            tp += len(used)
            fp += image_fp
            fn += len(gts) - len(used)
            images_with_fp += image_fp > 0
            abs_err += abs(len(preds) - len(gts))
            exact += len(preds) == len(gts)
    n = len(images)
    return {
        "images": n, "objects": tp + fn, "tp": tp, "fp": fp, "fn": fn,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "images_with_fp": images_with_fp,
        "count_mae": round(abs_err / n, 4) if n else None,
        "count_exact": round(exact / n, 4) if n else None,
    }


def negatives_check(model, negatives: Path, conf_levels, device, sheet_path: Path) -> dict:
    from PIL import Image, ImageDraw

    crops = sorted(p for p in negatives.glob("*.png"))
    by_subset: dict[str, dict] = {}
    flagged = []
    for crop in crops:
        subset = crop.name.split("__")[0]
        with Image.open(crop) as image:
            side = max(image.size)
        result = model.predict(str(crop), conf=min(conf_levels), imgsz=int(math.ceil(side / 32) * 32),
                               device=device, verbose=False)[0]
        scores = [float(b.conf[0]) for b in result.boxes]
        stats = by_subset.setdefault(subset, {"crops": 0, **{f"crops_with_fp@{c}": 0 for c in conf_levels},
                                              **{f"fp@{c}": 0 for c in conf_levels}})
        stats["crops"] += 1
        for c in conf_levels:
            hits = sum(s >= c for s in scores)
            stats[f"fp@{c}"] += hits
            stats[f"crops_with_fp@{c}"] += hits > 0
        if any(s >= max(conf_levels) for s in scores):
            flagged.append((crop, [(float(b.conf[0]), b.xyxy[0].tolist()) for b in result.boxes
                                   if float(b.conf[0]) >= max(conf_levels)]))
    if flagged:
        tile, cols = 200, 6
        rows = math.ceil(len(flagged) / cols)
        sheet = Image.new("RGB", (cols * tile, rows * (tile + 14)), "white")
        draw_sheet = ImageDraw.Draw(sheet)
        for k, (crop, boxes) in enumerate(flagged):
            with Image.open(crop) as image:
                image = image.convert("RGB")
                draw = ImageDraw.Draw(image)
                for score, box in boxes:
                    draw.rectangle(box, outline=(255, 0, 0), width=3)
                    draw.text((box[0] + 2, box[1] + 2), f"{score:.2f}", fill=(255, 0, 0))
                x, y = (k % cols) * tile, (k // cols) * (tile + 14)
                sheet.paste(image.resize((tile, tile)), (x, y))
                draw_sheet.text((x + 2, y + tile), crop.name[:34], fill="black")
        sheet.save(sheet_path, quality=90)
    return {"by_subset": by_subset, "flagged": [c.name for c, _ in flagged]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True, help="Carpeta shrimp_combined_v2.")
    parser.add_argument("--model", action="append", required=True, help="nombre=ruta/al/modelo.pt (repetible).")
    parser.add_argument("--subsets", nargs="+", default=SUBSETS)
    parser.add_argument("--conf", type=float, default=0.5, help="Confianza de operación (la de la aplicación).")
    parser.add_argument("--pending", type=Path, help="pending.csv del dataset anterior: se excluye de los negativos.")
    parser.add_argument("--device", default="0")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    from ultralytics import YOLO

    dataset = args.dataset.resolve()
    out = resolve(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pending = set()
    if args.pending and args.pending.is_file():
        with open(args.pending, encoding="utf-8") as handle:
            pending = {row["image"] for row in csv.DictReader(handle)}
    negatives = build_negatives(dataset, pending)
    conf_levels = sorted({0.25, args.conf})

    report = {"dataset": str(dataset), "conf": args.conf, "iou_match": IOU_MATCH, "models": {}}
    for spec in args.model:
        name, _, path = spec.partition("=")
        model_path = resolve(path)
        entry = {"path": str(model_path), "subsets": {}}
        for subset in args.subsets:
            yaml_path = dataset / f"data_{subset}.yaml"
            metrics = YOLO(str(model_path)).val(
                data=str(yaml_path), split="val", imgsz=640, batch=8, conf=0.001, iou=0.7, single_cls=True,
                device=args.device, plots=False, verbose=False, project=str(out / "ultralytics"),
                name=f"{name}_{subset}", exist_ok=True)
            entry["subsets"][subset] = {
                "precision": round(float(metrics.box.mp), 4), "recall": round(float(metrics.box.mr), 4),
                "mAP50": round(float(metrics.box.map50), 4), "mAP50_95": round(float(metrics.box.map), 4),
                f"at_conf_{args.conf}": operating_point(YOLO(str(model_path)), subset_images(dataset, subset),
                                                        dataset, args.conf, args.device),
            }
            print(name, subset, json.dumps(entry["subsets"][subset]))
        entry["negatives"] = negatives_check(YOLO(str(model_path)), negatives, conf_levels, args.device,
                                             out / f"false_positives_{name}.jpg")
        print(name, "negativos", json.dumps(entry["negatives"]["by_subset"]))
        report["models"][name] = entry
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Informe: {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
