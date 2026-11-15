"""Prepara fotos y videos nuevos sin etiquetar para corregirlos a mano y entrenar el detector.

Qué hace (no modifica el ZIP ni el dataset existente):
1. Lee las fotos y los videos de un ZIP o de una carpeta. Descarta fotos repetidas byte a byte.
2. De cada video saca un fotograma por segundo (--fps) y descarta los casi iguales al anterior (cámara quieta).
3. Pre-etiqueta todo con el detector actual en formato YOLO, para que quien etiqueta solo corrija.
   Por defecto analiza a 1280 px: con camarones amontonados detecta muchos más que a 640.
4. Escribe la carpeta lista para importar en Roboflow, CVAT o LabelImg:
     images/   fotos y fotogramas (JPEG)
     labels/   una línea por camarón: "0 x_centro y_centro ancho alto" (normalizado 0-1)
     preview/  las mismas imágenes con los recuadros dibujados, para revisar de un vistazo
     classes.txt, data.yaml, manifest.csv (origen de cada imagen y grupo de escena sugerido), LEEME.md

Las pre-etiquetas NO son etiquetas buenas: faltan camarones, hay recuadros repetidos o que cubren dos.
Hay que revisarlas todas antes de entrenar.

Ejemplo (desde la raíz del proyecto):
    .venv312\\Scripts\\python.exe training\\scripts\\prelabel_images.py ^
        --zip "..\\dataset\\fotos.zip" --output "..\\dataset\\camarones_nuevos_v1"
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import shutil
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = PROJECT_ROOT / "models" / "detector" / "best.pt"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".3gp"}


def slug(text: str) -> str:
    """Nombre de archivo seguro: sin tildes, espacios ni símbolos ("video de camarón 1" -> "video_de_camaron_1")."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "archivo"


def dhash(image: Image.Image, side: int = 16) -> int:
    """Huella de 256 bits: dos imágenes parecidas difieren en pocos bits."""
    gray = np.asarray(image.convert("L").resize((side + 1, side)), dtype=np.int16)
    bits = (gray[:, 1:] > gray[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def read_sources(source: Path, workdir: Path) -> tuple[list[tuple[str, Image.Image, str]], list[tuple[str, Path]]]:
    """Devuelve (fotos, videos). Las fotos ya giradas según EXIF; los videos copiados a una carpeta temporal."""
    photos, videos, seen = [], [], set()

    def add_photo(name: str, data: bytes):
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            print(f"  repetida, se omite: {name}")
            return
        seen.add(digest)
        try:
            image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        except Exception as error:  # noqa: BLE001 - archivo dañado: se informa y se sigue
            print(f"  no se pudo abrir {name}: {error}")
            return
        photos.append((name, image, digest))

    if source.is_file() and source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            for info in sorted(archive.infolist(), key=lambda i: i.filename):
                name = Path(info.filename).name
                ext = Path(name).suffix.lower()
                if info.is_dir() or name.startswith("."):
                    continue
                if ext in IMAGE_EXT:
                    add_photo(name, archive.read(info))
                elif ext in VIDEO_EXT:
                    target = workdir / f"{len(videos)}{ext}"  # nombre propio: nunca se usa la ruta del ZIP
                    with archive.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    videos.append((name, target))
    elif source.is_dir():
        for path in sorted(source.rglob("*")):
            ext = path.suffix.lower()
            if ext in IMAGE_EXT:
                add_photo(path.name, path.read_bytes())
            elif ext in VIDEO_EXT:
                videos.append((path.name, path))
    else:
        sys.exit(f"No existe o no es ZIP/carpeta: {source}")
    return photos, videos


def video_frames(path: Path, fps: float, min_change_bits: int):
    """Fotogramas a `fps` por segundo, omitiendo los casi iguales al último guardado."""
    capture = cv2.VideoCapture(str(path))
    native = capture.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, round(native / fps))
    last_hash = None
    for index in range(0, total, step):
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if not ok:
            continue
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        current = dhash(image)
        if last_hash is not None and hamming(current, last_hash) < min_change_bits:
            continue
        last_hash = current
        yield index / native, image
    capture.release()


def scene_groups(hashes: dict[str, int], threshold: int) -> dict[str, str]:
    """Agrupa fotos parecidas (enlace simple por distancia de dhash). Es solo una sugerencia para separar train/test."""
    parent = {key: key for key in hashes}

    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    keys = list(hashes)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if hamming(hashes[a], hashes[b]) <= threshold:
                parent[root(a)] = root(b)
    roots = sorted({root(k) for k in keys}, key=lambda r: min(k for k in keys if root(k) == r))
    names = {r: f"fotos_{n + 1:02d}" for n, r in enumerate(roots)}
    return {k: names[root(k)] for k in keys}


def readme_text(args, rows: list[dict], groups: dict[str, list[int]]) -> str:
    """Instrucciones para quien corrige las etiquetas, con los números de esta carpeta."""
    photos = sum(r["origen"] == "foto" for r in rows)
    frames = len(rows) - photos
    total = sum(r["preetiquetas"] for r in rows)
    doubtful = sum(r["dudosas_conf_menor_0_5"] for r in rows)
    table = "\n".join(f"| {name} | {n} | {labels} |" for name, (n, labels) in sorted(groups.items()))
    source = args.zip or args.input_dir
    return f"""# Fotos nuevas para corregir y entrenar

Generado con `training/scripts/prelabel_images.py` a partir de `{source.name}`.

- {photos} fotos y {frames} fotogramas de video (1 por segundo, sin los casi iguales).
- {total} pre-etiquetas del modelo actual (analizado a {args.imgsz} px, confianza ≥ {args.conf}); {doubtful} son dudosas.

**Las pre-etiquetas no están listas para entrenar.** Faltan camarones (sobre todo en los montones y en los videos),
hay recuadros repetidos y otros que cubren dos camarones. Hay que revisar las {len(rows)} imágenes.

## Qué hay en la carpeta

| Carpeta o archivo | Contenido |
|---|---|
| `images/` | Las imágenes a etiquetar |
| `labels/` | Una línea por camarón en formato YOLO: `0 x_centro y_centro ancho alto` (valores de 0 a 1) |
| `preview/` | Las imágenes con las pre-etiquetas dibujadas: verde = confianza ≥ 0,5, naranja = dudosa |
| `manifest.csv` | De dónde sale cada imagen (foto o segundo del video) y su grupo de escena sugerido |
| `data.yaml`, `classes.txt` | Una sola clase: `camaron` |

## Cómo etiquetar

Criterio, igual que el dataset actual:

- Un recuadro por camarón, de la punta de la cabeza al final de la cola, **sin las antenas largas**.
- Marca también los camarones tapados en parte o cortados por el borde, siempre que se reconozcan.
- Si dos camarones se tocan, dos recuadros (aunque se solapen). Nunca uno que cubra varios.
- Manos, sombras, agua o antenas sueltas no se marcan. Una imagen sin camarones queda con su `.txt` vacío.

Herramientas (cualquiera sirve):

- **Roboflow** (en el navegador): crea un proyecto de detección de objetos, arrastra la carpeta completa
  (`images/`, `labels/` y `data.yaml`) y revisa imagen por imagen. Al terminar, exporta en formato **YOLOv8**.
- **LabelImg** (sin internet): `pip install labelImg`, abre `images/` como carpeta, elige `labels/` como carpeta de
  guardado y el formato **YOLO**. Atajos: `W` nuevo recuadro, `D` siguiente imagen, `Supr` borrar recuadro.

## Antes de entrenar

Separar entrenamiento, validación y prueba **por grupo** (columna `grupo_sugerido`), nunca imagen por imagen:
las fotos de una misma escena son casi iguales y, mezcladas, darían métricas falsamente buenas. Los grupos se
calcularon por parecido de imagen; revísalos a ojo. Sugerencia: dejar `video_video_de_camaron_2` solo para prueba.

| Grupo sugerido | Imágenes | Pre-etiquetas |
|---|---|---|
{table}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--zip", type=Path, help="ZIP con fotos y/o videos")
    source.add_argument("--input-dir", type=Path, help="carpeta con fotos y/o videos")
    parser.add_argument("--output", type=Path, required=True, help="carpeta nueva de salida (dentro de dataset)")
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--imgsz", type=int, default=1280, help="tamaño de análisis; 1280 detecta más camarones juntos")
    parser.add_argument("--conf", type=float, default=0.25, help="confianza mínima de las pre-etiquetas")
    parser.add_argument("--max-area", type=float, default=0.45, help="descarta recuadros mayores a esta fracción de la imagen")
    # En videos de baja resolución el modelo actual dibuja muchos recuadros enormes sobre grupos o sobre el fondo; un
    # camarón suelto ocupa ~4-8 % del fotograma. Mejor dejar esos para dibujar a mano que corregir recuadros falsos.
    parser.add_argument("--video-max-area", type=float, default=0.12, help="límite de --max-area para fotogramas de video")
    parser.add_argument("--fps", type=float, default=1.0, help="fotogramas por segundo extraídos de cada video")
    parser.add_argument("--min-change-bits", type=int, default=8, help="diferencia mínima (dhash) entre fotogramas guardados")
    parser.add_argument("--group-threshold", type=int, default=80, help="parecido (dhash) para sugerir la misma escena")
    parser.add_argument("--device", default=None, help="0 para GPU, cpu para CPU (por defecto, automático)")
    parser.add_argument("--overwrite", action="store_true", help="reemplazar la carpeta de salida si ya existe")
    args = parser.parse_args()

    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        if not args.overwrite:
            sys.exit(f"La carpeta de salida ya existe y no está vacía: {out}\nUsa --overwrite para reemplazarla.")
        shutil.rmtree(out)
    for sub in ("images", "labels", "preview"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    from ultralytics import YOLO
    model = YOLO(str(args.weights))

    with tempfile.TemporaryDirectory() as tmp:
        photos, videos = read_sources(args.zip or args.input_dir, Path(tmp))
        print(f"Fotos únicas: {len(photos)} · videos: {len(videos)}")

        items = []  # (nombre_salida, imagen, origen, archivo_original, segundo, grupo, sha256)
        hashes = {}
        for name, image, digest in photos:
            stem = f"foto_{slug(Path(name).stem)}"
            hashes[stem] = dhash(image)
            items.append([stem, image, "foto", name, "", None, digest])
        groups = scene_groups(hashes, args.group_threshold)
        for item in items:
            item[5] = groups[item[0]]
        for name, path in videos:
            vslug = slug(Path(name).stem)
            count = 0
            for second, image in video_frames(path, args.fps, args.min_change_bits):
                items.append([f"{vslug}_t{second:05.1f}s".replace(".", "_"), image, "video", name, f"{second:.1f}",
                              f"video_{vslug}", ""])
                count += 1
            print(f"  {name}: {count} fotogramas")

        rows = []
        for stem, image, origin, original, second, group, digest in items:
            image_path = out / "images" / f"{stem}.jpg"
            image.save(image_path, quality=95)
            result = model.predict(np.asarray(image)[:, :, ::-1], imgsz=args.imgsz, conf=args.conf,
                                   device=args.device, verbose=False)[0]
            lines, confs = [], []
            max_area = args.video_max_area if origin == "video" else args.max_area
            for (x, y, w, h), conf in zip(result.boxes.xywhn.tolist(), result.boxes.conf.tolist()):
                if w * h > max_area:
                    continue
                lines.append(f"0 {x:.6f} {y:.6f} {w:.6f} {h:.6f}")
                confs.append(conf)
            (out / "labels" / f"{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            preview = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
            H, W = preview.shape[:2]
            for line, conf in zip(lines, confs):
                _, x, y, w, h = map(float, line.split())
                p1 = (int((x - w / 2) * W), int((y - h / 2) * H))
                p2 = (int((x + w / 2) * W), int((y + h / 2) * H))
                color = (0, 200, 0) if conf >= 0.5 else (0, 165, 255)  # verde: seguro · naranja: dudoso
                cv2.rectangle(preview, p1, p2, color, max(2, W // 400))
                cv2.putText(preview, f"{conf:.2f}", (p1[0], max(15, p1[1] - 5)), cv2.FONT_HERSHEY_SIMPLEX,
                            max(0.5, W / 1600), color, max(1, W // 800))
            cv2.imwrite(str(out / "preview" / f"{stem}.jpg"), preview, [cv2.IMWRITE_JPEG_QUALITY, 85])
            rows.append({"imagen": f"images/{stem}.jpg", "origen": origin, "archivo_original": original,
                         "segundo_video": second, "grupo_sugerido": group, "ancho": W, "alto": H,
                         "preetiquetas": len(lines), "dudosas_conf_menor_0_5": sum(c < 0.5 for c in confs),
                         "sha256_original": digest})

    with open(out / "manifest.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out / "classes.txt").write_text("camaron\n", encoding="utf-8")
    (out / "labels" / "classes.txt").write_text("camaron\n", encoding="utf-8")  # LabelImg la busca junto a las etiquetas
    groups_summary = {}
    for r in rows:
        g = groups_summary.setdefault(r["grupo_sugerido"], [0, 0])
        g[0] += 1
        g[1] += r["preetiquetas"]
    (out / "LEEME.md").write_text(readme_text(args, rows, groups_summary), encoding="utf-8")
    (out / "data.yaml").write_text(
        "# Solo para importar/revisar. Antes de entrenar: corregir etiquetas y separar train/val/test por grupo.\n"
        "path: .\ntrain: images\nval: images\nnc: 1\nnames:\n  0: camaron\n", encoding="utf-8")
    total = sum(r["preetiquetas"] for r in rows)
    print(f"Listo: {len(rows)} imágenes, {total} pre-etiquetas -> {out}")


if __name__ == "__main__":
    main()
