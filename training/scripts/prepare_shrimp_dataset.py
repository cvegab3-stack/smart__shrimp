"""Valida y prepara el ZIP YOLOv8 de Roboflow "shrimp-object-tracking-and-counting v4" para SMART SHRIMP.

El ZIP de entrada solo se lee. Se generan, dentro de la carpeta de salida:

- audit/: informe de auditoría (Markdown y JSON), inventarios CSV y mapa de las 12 clases originales.
- detect/: conjunto de detección de una sola clase "camaron" con listas de partición original y agrupada.
- segment/: conjunto de segmentación con imágenes cuyos objetos tienen todos polígonos válidos.

No se inventan etiquetas ni máscaras: una imagen con cualquier anotación inválida se excluye completa.

Uso (por defecto escribe en ..\\dataset\\shrimp_roboflow_v4, junto al proyecto y fuera del código; ver data_paths.py):
    python training/scripts/prepare_shrimp_dataset.py --zip RUTA.zip
    python training/scripts/prepare_shrimp_dataset.py --zip RUTA.zip --output D:/datos/shrimp_roboflow_v4
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import itertools
import json
import math
import os
import random
import re
import shutil
import stat
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import numpy as np
import yaml
from PIL import Image, ImageDraw

from data_paths import DATA_DIR_ENV, output_data_dir

SCRIPT_VERSION = "1.0.0"
DATASET_ID = "shrimp_roboflow_v4"
TARGET_CLASS = "camaron"
SPLITS = ("train", "valid", "test")
YOLO_SPLIT_NAMES = {"train": "train", "valid": "val", "test": "test"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
COORD_TOLERANCE = 1e-3
MIN_BOX_PX = 1.0
TINY_BOX_PX = 4.0
MIN_POLYGON_AREA_PX = 1.0
OVERLAP_IOU = 0.9
DHASH_SIDE = 16

NAME_RE = re.compile(
    r"^(?P<source>WIN_(?P<ts>\d{8}_\d{2}_\d{2}_\d{2})_Pro(?:-\d+-)?(?:_mp4-(?P<frame>\d+))?)"
    r"_(?P<ext>jpe?g|png)\.rf\.(?P<rf>[0-9a-f]+)\.(?:jpe?g|png)$",
    re.IGNORECASE,
)
CLASS_RE = re.compile(r"^camaron-(?P<size>grande|mediano|pequeno)-(?P<head>con|sin)cabeza-(?P<tail>con|sin)cola$")
INTEGRITY_CANDIDATE = {
    (True, True): ["completo"],
    (False, True): ["sin_cabeza"],
    (True, False): ["sin_cola"],
    (False, False): ["sin_cabeza", "sin_cola"],
}


# --------------------------------------------------------------------------- estructuras


@dataclass
class LabelObject:
    line: int
    class_id: int | None
    geometry: str  # polygon | box | invalid
    points: list[tuple[float, float]] = field(default_factory=list)
    box: tuple[float, float, float, float] | None = None  # cx, cy, w, h normalizados y recortados
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    clipped: bool = False
    polygon_valid: bool = False

    @property
    def valid(self) -> bool:
        return self.geometry != "invalid" and not self.issues


@dataclass
class ImageRecord:
    split: str
    name: str
    image_member: str
    label_member: str | None
    source: str = ""
    timestamp: dt.datetime | None = None
    video_id: str | None = None
    video_frame: int | None = None
    width: int = 0
    height: int = 0
    image_format: str = ""
    image_mode: str = ""
    sha256: str = ""
    image_issues: list[str] = field(default_factory=list)
    label_status: str = ""  # ok | empty | missing | invalid
    label_issues: list[str] = field(default_factory=list)
    label_sha256: str = ""
    objects: list[LabelObject] = field(default_factory=list)
    dhash: np.ndarray | None = None  # 8 orientaciones x 4 uint64 (256 bits)
    group: str = ""
    grouped_split: str = ""
    in_detect: bool = False
    in_segment: bool = False
    segment_status: str = ""
    grouped_lists: set[str] = field(default_factory=set)

    @property
    def kind(self) -> str:
        return "video_frame" if self.video_id else "photo"

    @property
    def detect_ready(self) -> bool:
        return not self.image_issues and self.label_status == "ok"


# --------------------------------------------------------------------------- utilidades


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def member_path_issues(info: zipfile.ZipInfo) -> list[str]:
    """Detecta rutas peligrosas o ambiguas dentro del ZIP."""
    name = info.filename
    issues = []
    if "\\" in name:
        issues.append("barra_invertida")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        issues.append("ruta_absoluta")
    parts = PurePosixPath(name).parts
    if any(part == ".." for part in parts):
        issues.append("recorrido_padre")
    if any(ord(ch) < 32 for ch in name):
        issues.append("caracter_control")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        issues.append("enlace_simbolico")
    if info.flag_bits & 0x1:
        issues.append("cifrado")
    if info.file_size > 50 * 1024 * 1024 and info.compress_size and info.file_size / info.compress_size > 100:
        issues.append("ratio_compresion_sospechoso")
    return issues


def parse_class_name(name: str) -> dict:
    match = CLASS_RE.match(name)
    if not match:
        return {"name": name, "parsed": False}
    has_head = match["head"] == "con"
    has_tail = match["tail"] == "con"
    return {
        "name": name,
        "parsed": True,
        "size_label": match["size"],
        "has_head": has_head,
        "has_tail": has_tail,
        "catalog_integridad_candidates": INTEGRITY_CANDIDATE[(has_head, has_tail)],
    }


def polygon_area(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def polygon_self_intersects(points: np.ndarray) -> bool:
    """Comprueba cruces propios entre aristas no adyacentes (vectorizado)."""
    n = len(points)
    if n < 4:
        return False
    p = points
    q = np.roll(points, -1, axis=0)
    r = q - p

    def cross(a, b):
        return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]

    pi, ri = p[:, None, :], r[:, None, :]
    pj, qj, rj = p[None, :, :], q[None, :, :], r[None, :, :]
    d1 = cross(ri, pj - pi)
    d2 = cross(ri, qj - pi)
    d3 = cross(rj, pi - pj)
    d4 = cross(rj, (pi + ri) - pj)
    hit = (d1 * d2 < 0) & (d3 * d4 < 0)
    idx = np.arange(n)
    diff = np.abs(idx[:, None] - idx[None, :])
    mask = (diff > 1) & (diff != n - 1)
    return bool(np.any(hit & mask))


def dhash_orientations(image: Image.Image) -> np.ndarray:
    """dHash de 256 bits (16x16) para las 8 orientaciones diédricas; devuelve (8, 4) uint64.

    Con 64 bits el fondo oscuro uniforme hace que escenas distintas parezcan iguales; 256 bits sí las separa.
    """
    side = DHASH_SIDE
    small = np.asarray(image.convert("L").resize((side + 1, side + 1), Image.Resampling.BOX), dtype=np.int16)
    hashes = []
    for k in range(4):
        rotated = np.rot90(small, k)
        for variant in (rotated, rotated[:, ::-1]):
            bits = (variant[:side, 1:] > variant[:side, :-1]).flatten()
            hashes.append(np.packbits(bits).view(">u8").astype(np.uint64))
    return np.stack(hashes)


def box_iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


class UnionFind:
    def __init__(self, items):
        self.parent = {item: item for item in items}

    def find(self, item):
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def quantiles(values, qs=(0.0, 0.05, 0.5, 0.95, 1.0)) -> dict:
    if not values:
        return {}
    arr = np.asarray(values, dtype=float)
    return {f"p{int(q * 100)}": round(float(np.quantile(arr, q)), 4) for q in qs}


# --------------------------------------------------------------------------- lectura y validación


def parse_label(text: str, num_classes: int, width: int, height: int) -> tuple[list[LabelObject], list[str]]:
    objects: list[LabelObject] = []
    file_issues: list[str] = []
    seen_lines: Counter = Counter()
    for line_no, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line:
            continue
        seen_lines[line] += 1
        tokens = line.split()
        obj = LabelObject(line=line_no, class_id=None, geometry="invalid")
        objects.append(obj)
        try:
            class_value = float(tokens[0])
            if not class_value.is_integer():
                raise ValueError
            obj.class_id = int(class_value)
        except ValueError:
            obj.issues.append("clase_no_entera")
            continue
        if not 0 <= obj.class_id < num_classes:
            obj.issues.append("clase_fuera_de_rango")
        try:
            coords = [float(token) for token in tokens[1:]]
        except ValueError:
            obj.issues.append("coordenada_no_numerica")
            continue
        if not all(math.isfinite(value) for value in coords):
            obj.issues.append("coordenada_no_finita")
            continue
        if any(value < -COORD_TOLERANCE or value > 1 + COORD_TOLERANCE for value in coords):
            obj.issues.append("coordenada_fuera_de_imagen")
            continue
        if any(value < 0 or value > 1 for value in coords):
            obj.clipped = True
            obj.warnings.append("coordenada_recortada_por_tolerancia")
        if len(coords) == 4:
            obj.geometry = "box"
            cx, cy, w, h = coords
            x1, y1 = max(0.0, cx - w / 2), max(0.0, cy - h / 2)
            x2, y2 = min(1.0, cx + w / 2), min(1.0, cy + h / 2)
            if (x1, y1, x2, y2) != (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2):
                obj.clipped = True
        elif len(coords) >= 6 and len(coords) % 2 == 0:
            obj.geometry = "polygon"
            pts = np.clip(np.array(coords, dtype=float).reshape(-1, 2), 0.0, 1.0)
            obj.points = [tuple(map(float, pt)) for pt in pts]
            x1, y1 = float(pts[:, 0].min()), float(pts[:, 1].min())
            x2, y2 = float(pts[:, 0].max()), float(pts[:, 1].max())
        else:
            obj.issues.append(f"numero_de_valores_invalido_{len(coords)}")
            continue
        w_px, h_px = (x2 - x1) * width, (y2 - y1) * height
        if w_px < MIN_BOX_PX or h_px < MIN_BOX_PX:
            obj.issues.append("cuadro_degenerado")
            continue
        if w_px < TINY_BOX_PX or h_px < TINY_BOX_PX:
            obj.warnings.append("cuadro_diminuto")
        obj.box = ((x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1)
        if obj.geometry == "polygon":
            pts_px = np.array(obj.points) * np.array([width, height])
            unique_pts = np.unique(np.round(pts_px, 3), axis=0)
            if len(unique_pts) < 3:
                obj.warnings.append("poligono_con_menos_de_3_puntos_distintos")
            elif polygon_area(pts_px) < MIN_POLYGON_AREA_PX:
                obj.warnings.append("poligono_area_nula")
            elif polygon_self_intersects(pts_px):
                obj.warnings.append("poligono_autointersectado")
            else:
                obj.polygon_valid = True
    duplicates = sum(count - 1 for count in seen_lines.values() if count > 1)
    if duplicates:
        file_issues.append(f"lineas_duplicadas_{duplicates}")
    return objects, file_issues


def audit_zip(zip_path: Path) -> tuple[dict, list[ImageRecord], dict]:
    """Recorre el ZIP una vez y devuelve hallazgos globales, registros por imagen y data.yaml."""
    findings: dict = {"zip": {}, "structure": {}, "unexpected_members": []}
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        print(f"[1/6] Verificando CRC de {len(infos)} entradas...", flush=True)
        first_bad = archive.testzip()
        names = [info.filename for info in infos]
        unsafe = {info.filename: member_path_issues(info) for info in infos if member_path_issues(info)}
        lower = Counter(name.lower() for name in names)
        findings["zip"] = {
            "entries": len(infos),
            "crc_ok": first_bad is None,
            "first_bad_member": first_bad,
            "unsafe_members": unsafe,
            "duplicate_member_names": [n for n, c in Counter(names).items() if c > 1],
            "case_insensitive_collisions": [n for n, c in lower.items() if c > 1],
            "uncompressed_bytes": sum(info.file_size for info in infos),
        }
        if first_bad is not None or unsafe:
            raise SystemExit(f"ZIP no confiable: CRC={first_bad!r}, rutas inseguras={list(unsafe)[:5]}")

        if "data.yaml" not in names:
            raise SystemExit("El ZIP no contiene data.yaml en la raíz.")
        data_yaml = yaml.safe_load(archive.read("data.yaml").decode("utf-8"))
        class_names = list(data_yaml.get("names") or [])
        nc = int(data_yaml.get("nc", -1))
        findings["structure"]["data_yaml"] = {
            "nc": nc,
            "names_count": len(class_names),
            "nc_matches_names": nc == len(class_names),
            "names_unique": len(set(class_names)) == len(class_names),
            "all_names_parse": all(CLASS_RE.match(n) for n in class_names),
            "declared_splits": {k: data_yaml.get(k) for k in ("train", "val", "test")},
            "roboflow": data_yaml.get("roboflow", {}),
        }
        for readme in ("README.dataset.txt", "README.roboflow.txt"):
            if readme in names:
                findings["structure"][readme] = archive.read(readme).decode("utf-8", errors="replace")

        images: dict[tuple[str, str], str] = {}
        labels: dict[tuple[str, str], str] = {}
        for name in names:
            if name.endswith("/") or name in ("data.yaml", "README.dataset.txt", "README.roboflow.txt"):
                continue
            parts = name.split("/")
            if len(parts) == 3 and parts[0] in SPLITS and parts[1] == "images" and \
                    Path(parts[2]).suffix.lower() in IMAGE_EXTS:
                images[(parts[0], Path(parts[2]).stem)] = name
            elif len(parts) == 3 and parts[0] in SPLITS and parts[1] == "labels" and parts[2].endswith(".txt"):
                labels[(parts[0], Path(parts[2]).stem)] = name
            else:
                findings["unexpected_members"].append(name)
        findings["structure"]["images_per_split"] = dict(Counter(s for s, _ in images))
        findings["structure"]["labels_per_split"] = dict(Counter(s for s, _ in labels))
        findings["structure"]["labels_without_image"] = sorted(labels[k] for k in set(labels) - set(images))
        stems = Counter(stem for _, stem in images)
        findings["structure"]["basename_collisions_across_splits"] = sorted(s for s, c in stems.items() if c > 1)

        records: list[ImageRecord] = []
        print(f"[2/6] Decodificando {len(images)} imágenes y etiquetas...", flush=True)
        for index, key in enumerate(sorted(images)):
            split, stem = key
            member = images[key]
            rec = ImageRecord(split=split, name=PurePosixPath(member).name, image_member=member,
                              label_member=labels.get(key))
            match = NAME_RE.match(rec.name)
            if match:
                rec.source = match["source"]
                rec.timestamp = dt.datetime.strptime(match["ts"], "%Y%m%d_%H_%M_%S")
                if match["frame"] is not None:
                    rec.video_id = f"WIN_{match['ts']}_Pro.mp4"
                    rec.video_frame = int(match["frame"])
            else:
                rec.source = stem.split(".rf.")[0]
                rec.image_issues.append("nombre_sin_patron_reconocido")
            raw = archive.read(member)
            rec.sha256 = hashlib.sha256(raw).hexdigest()
            if not raw:
                rec.image_issues.append("imagen_vacia")
            else:
                try:
                    with Image.open(io.BytesIO(raw)) as probe:
                        probe.verify()
                    with Image.open(io.BytesIO(raw)) as img:
                        img.load()
                        rec.width, rec.height = img.size
                        rec.image_format, rec.image_mode = img.format or "", img.mode
                        rec.dhash = dhash_orientations(img)
                except Exception as exc:  # noqa: BLE001 - cualquier fallo de decodificación invalida la imagen
                    rec.image_issues.append(f"imagen_no_decodificable:{type(exc).__name__}")
            if rec.label_member is None:
                rec.label_status = "missing"
            elif not rec.image_issues:
                text_raw = archive.read(rec.label_member)
                rec.label_sha256 = hashlib.sha256(text_raw).hexdigest()
                try:
                    text = text_raw.decode("utf-8")
                except UnicodeDecodeError:
                    rec.label_status = "invalid"
                    rec.label_issues.append("etiqueta_no_utf8")
                    text = ""
                if not rec.label_status:
                    rec.objects, rec.label_issues = parse_label(text, len(class_names), rec.width, rec.height)
                    if not rec.objects:
                        rec.label_status = "empty"
                    elif rec.label_issues or any(not obj.valid for obj in rec.objects):
                        rec.label_status = "invalid"
                    else:
                        rec.label_status = "ok"
            records.append(rec)
            if (index + 1) % 1000 == 0:
                print(f"      {index + 1}/{len(images)}", flush=True)
    return findings, records, data_yaml


# --------------------------------------------------------------------------- duplicados y fuga


def near_duplicate_pairs(records: list[ImageRecord], max_bits: int) -> list[tuple[int, int, int]]:
    """Pares (i, j, distancia) de imágenes de fuentes distintas con dHash diédrico cercano."""
    idx = [i for i, rec in enumerate(records) if rec.dhash is not None]
    if not idx:
        return []
    all_hashes = np.stack([records[i].dhash for i in idx])  # (N, 8, 4)
    canonical = all_hashes[:, 0, :]
    pairs = []
    chunk = 32
    for start in range(0, len(idx), chunk):
        block = canonical[start:start + chunk]
        xor = block[:, None, None, :] ^ all_hashes[None, :, :, :]
        dist = np.bitwise_count(xor).sum(axis=3, dtype=np.int32).min(axis=2)
        rows, cols = np.nonzero(dist <= max_bits)
        for r, c in zip(rows.tolist(), cols.tolist()):
            a, b = idx[start + r], idx[c]
            if a < b and records[a].source != records[b].source:
                pairs.append((a, b, int(dist[r, c])))
    return pairs


def source_intervals(records: list[ImageRecord], video_span: float) -> dict[str, tuple[float, float]]:
    """Intervalo temporal conservador por fuente: foto = instante; fotograma de vídeo = [inicio, inicio+span]."""
    intervals = {}
    for rec in records:
        if rec.timestamp is None:
            continue
        start = rec.timestamp.timestamp()
        end = start + (video_span if rec.video_id else 0.0)
        old = intervals.get(rec.source)
        intervals[rec.source] = (start, end) if old is None else (min(old[0], start), max(old[1], end))
    return intervals


def temporal_clusters(intervals: dict[str, tuple[float, float]], gap: float) -> list[list[str]]:
    ordered = sorted(intervals.items(), key=lambda kv: (kv[1][0], kv[0]))
    clusters: list[list[str]] = []
    current_end = None
    for source, (start, end) in ordered:
        if current_end is None or start - current_end > gap:
            clusters.append([])
            current_end = end
        clusters[-1].append(source)
        current_end = max(current_end, end)
    return clusters


def min_gap_between(intervals_a: list[tuple[float, float]], intervals_b: list[tuple[float, float]]) -> float | None:
    if not intervals_a or not intervals_b:
        return None
    best = math.inf
    for s1, e1 in intervals_a:
        for s2, e2 in intervals_b:
            best = min(best, max(0.0, s2 - e1, s1 - e2))
    return best


def analyze_original_leakage(records, intervals, near_pairs, gap) -> dict:
    by_source_splits = defaultdict(set)
    by_second = defaultdict(set)
    video_splits = defaultdict(Counter)
    for rec in records:
        by_source_splits[rec.source].add(rec.split)
        if rec.timestamp:
            by_second[rec.timestamp].add(rec.split)
        if rec.video_id:
            video_splits[rec.video_id][rec.split] += 1
    sha_splits = defaultdict(set)
    for rec in records:
        sha_splits[rec.sha256].add(rec.split)

    source_split = {s: sorted(v)[0] for s, v in by_source_splits.items()}
    split_intervals = defaultdict(list)
    for source, interval in intervals.items():
        split_intervals[source_split[source]].append(interval)
    pair_gaps = {}
    for a, b in itertools.combinations(SPLITS, 2):
        value = min_gap_between(split_intervals[a], split_intervals[b])
        pair_gaps[f"{a}-{b}"] = value

    # Fuentes de valid/test con alguna fuente de train a <= N segundos (solo fotos, sin span de vídeo).
    train_times = np.array(sorted(i[0] for s, i in intervals.items() if source_split[s] == "train"))
    neighbours = {}
    for split in ("valid", "test"):
        times = [i[0] for s, i in intervals.items() if source_split[s] == split]
        counts = {}
        for window in (1, 2, 5, gap):
            hits = 0
            for t in times:
                pos = np.searchsorted(train_times, t)
                near = [abs(train_times[p] - t) for p in (pos - 1, pos) if 0 <= p < len(train_times)]
                hits += bool(near and min(near) <= window)
            counts[f"<= {int(window)} s"] = hits
        neighbours[split] = {"sources": len(times), "with_train_source_within": counts}

    cross_near = Counter()
    for a, b, _ in near_pairs:
        sa, sb = records[a].split, records[b].split
        if sa != sb:
            cross_near["-".join(sorted((sa, sb)))] += 1
    return {
        "sources_in_multiple_splits": sum(1 for v in by_source_splits.values() if len(v) > 1),
        "exact_duplicate_hashes_across_splits": sum(1 for v in sha_splits.values() if len(v) > 1),
        "seconds_shared_between_splits": sum(1 for v in by_second.values() if len(v) > 1),
        "seconds_total": len(by_second),
        "videos": {vid: dict(c) for vid, c in sorted(video_splits.items())},
        "videos_split_across_partitions": sum(1 for c in video_splits.values() if len(c) > 1),
        "min_time_gap_seconds_between_splits": pair_gaps,
        "eval_sources_with_nearby_train_source": neighbours,
        "near_duplicate_pairs_across_splits": dict(cross_near),
    }


def coverage(attrs: list[Counter], min_objects: int) -> tuple[int, int]:
    """Nº de tamaños y de combinaciones cabeza/cola con al menos min_objects objetos en la unión de grupos."""
    total = sum(attrs, Counter())
    sizes = sum(1 for key, n in total.items() if key.startswith("size:") and n >= min_objects)
    head_tail = sum(1 for key, n in total.items() if key.startswith("ht:") and n >= min_objects)
    return sizes, head_tail


def subset_best(sizes: dict[str, int], attrs: dict[str, Counter], target: int, low: int, high: int,
                min_objects: int) -> list[str] | None:
    """Subconjunto de grupos con tamaño en [low, high] que maximiza la cobertura de atributos y luego
    se acerca al objetivo. Búsqueda exhaustiva y determinista (hasta 20 grupos)."""
    keys = sorted(sizes, key=lambda k: (-sizes[k], k))
    if len(keys) > 20:
        raise SystemExit("Demasiados grupos para la búsqueda exhaustiva; aumente --gap-seconds.")
    best: tuple | None = None
    for r in range(1, len(keys)):
        for combo in itertools.combinations(keys, r):
            total = sum(sizes[k] for k in combo)
            if not low <= total <= high:
                continue
            size_cov, ht_cov = coverage([attrs[k] for k in combo], min_objects)
            score = (-size_cov, -ht_cov, abs(total - target), r, sorted(combo))
            if best is None or score < best[0]:
                best = (score, list(combo))
    return best[1] if best else None


def build_grouped_split(records, intervals, near_pairs, class_info, args) -> dict:
    sources = sorted({rec.source for rec in records})
    uf = UnionFind(sources)
    edges = Counter()
    by_video = defaultdict(list)
    by_sha = defaultdict(list)
    for rec in records:
        if rec.video_id:
            by_video[rec.video_id].append(rec.source)
        by_sha[rec.sha256].append(rec.source)
    for members in by_video.values():
        for other in members[1:]:
            uf.union(members[0], other)
            edges["mismo_video"] += 1
    for members in by_sha.values():
        for other in members[1:]:
            if other != members[0]:
                uf.union(members[0], other)
                edges["hash_exacto"] += 1
    clusters = temporal_clusters(intervals, args.gap_seconds)
    for cluster in clusters:
        for other in cluster[1:]:
            uf.union(cluster[0], other)
    edges["agrupaciones_temporales"] = len(clusters)
    union_pairs = [(a, b, d) for a, b, d in near_pairs if d <= args.near_dup_union_bits]
    for a, b, _ in union_pairs:
        if uf.find(records[a].source) != uf.find(records[b].source):
            edges["casi_duplicado_union_nueva"] += 1
        uf.union(records[a].source, records[b].source)

    groups = defaultdict(list)
    for source in sources:
        groups[uf.find(source)].append(source)
    ordered = sorted(groups.values(), key=lambda members: min(intervals.get(m, (math.inf,))[0] for m in members))
    group_name = {}
    group_sources = {}
    for index, members in enumerate(ordered, start=1):
        first = min(intervals.get(m, (0.0, 0.0))[0] for m in members)
        name = f"g{index:02d}_{dt.datetime.fromtimestamp(first).strftime('%Y%m%d_%H%M%S')}"
        group_sources[name] = sorted(members)
        for member in members:
            group_name[member] = name
    sizes = {name: len(members) for name, members in group_sources.items()}
    attrs: dict[str, Counter] = defaultdict(Counter)
    classes: dict[str, Counter] = defaultdict(Counter)
    for rec in records:
        for obj in rec.objects:
            if obj.class_id is not None and 0 <= obj.class_id < len(class_info):
                info = class_info[obj.class_id]
                attrs[group_name[rec.source]][f"size:{info['size_label']}"] += 1
                attrs[group_name[rec.source]][f"ht:{info['has_head']}-{info['has_tail']}"] += 1
                classes[group_name[rec.source]][info["name"]] += 1
    dominant = {}
    for name, counter in classes.items():
        top, count = counter.most_common(1)[0]
        dominant[name] = {"clase": top, "proporcion": round(count / sum(counter.values()), 2)}
    total = len(sources)
    largest = max(sizes.values())
    result = {
        "parameters": {
            "gap_seconds": args.gap_seconds,
            "video_span_seconds": args.video_span_seconds,
            "near_duplicate_report_bits": args.near_dup_bits,
            "near_duplicate_union_bits": args.near_dup_union_bits,
            "valid_fraction": args.valid_fraction,
            "test_fraction": args.test_fraction,
        },
        "union_edges": dict(edges),
        "groups": len(group_sources),
        "group_sizes_sources": sizes,
        "group_dominant_class_share": dominant,
        "largest_group_share": largest / total,
        "group_of_source": group_name,
        "reliable": False,
        "reasons": [],
    }
    if len(group_sources) < args.min_groups:
        result["reasons"].append(f"solo {len(group_sources)} grupos (< {args.min_groups})")
    if largest / total > args.max_group_share:
        result["reasons"].append(f"el grupo mayor contiene {largest / total:.1%} de las fuentes "
                                 f"(> {args.max_group_share:.0%})")
    assignment = {}
    if not result["reasons"]:
        remaining = dict(sizes)
        for split, fraction in (("test", args.test_fraction), ("valid", args.valid_fraction)):
            target = round(total * fraction)
            chosen = subset_best(remaining, attrs, target, int(target * 0.5), int(target * 2.0),
                                 args.min_attribute_objects)
            if not chosen or len(chosen) == len(remaining):
                result["reasons"].append(f"no hay combinación de grupos completos para {split} "
                                         f"cerca de {fraction:.0%}")
                break
            for name in chosen:
                assignment[name] = split
                remaining.pop(name)
        for name in remaining:
            assignment.setdefault(name, "train")
    if result["reasons"]:
        return result

    split_of_source = {s: assignment[group_name[s]] for s in sources}
    # Verificación independiente de la separación obtenida.
    split_intervals = defaultdict(list)
    for source, interval in intervals.items():
        split_intervals[split_of_source[source]].append(interval)
    gaps = {f"{a}-{b}": min_gap_between(split_intervals[a], split_intervals[b])
            for a, b in itertools.combinations(SPLITS, 2)}
    video_mix = sum(1 for members in by_video.values() if len({split_of_source[m] for m in members}) > 1)
    sha_mix = sum(1 for members in by_sha.values() if len({split_of_source[m] for m in members}) > 1)
    near_mix = sum(1 for a, b, _ in union_pairs
                   if split_of_source[records[a].source] != split_of_source[records[b].source])
    near_mix_report = sum(1 for a, b, _ in near_pairs
                          if split_of_source[records[a].source] != split_of_source[records[b].source])
    checks = {
        "min_time_gap_seconds_between_splits": gaps,
        "videos_split_across_partitions": video_mix,
        "exact_duplicates_across_partitions": sha_mix,
        f"near_duplicate_pairs_across_partitions_le_{args.near_dup_union_bits}_bits": near_mix,
        f"near_duplicate_pairs_across_partitions_le_{args.near_dup_bits}_bits_informativo": near_mix_report,
    }
    result["verification"] = checks
    if any(v is not None and v <= args.gap_seconds for v in gaps.values()) or video_mix or sha_mix or near_mix:
        result["reasons"].append("la verificación posterior encontró proximidad entre particiones")
        return result
    result["reliable"] = True
    result["assignment"] = assignment
    result["split_of_source"] = split_of_source
    return result


# --------------------------------------------------------------------------- escritura


def prepare_output_dir(output: Path, overwrite: bool, zip_path: Path) -> None:
    output = output.resolve()
    if output == zip_path.parent.resolve() or zip_path.resolve().is_relative_to(output):
        raise SystemExit("La carpeta de salida no puede contener el ZIP original.")
    if output.exists() and any(output.iterdir()):
        manifest = output / "manifest.json"
        if not overwrite:
            raise SystemExit(f"{output} ya existe y no está vacía; use --overwrite para regenerarla.")
        if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8")).get("dataset_id") != DATASET_ID:
            raise SystemExit(f"{output} no parece una salida de este script (falta manifest.json); no se borra.")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)


def link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def fmt(value: float) -> str:
    return f"{value:.6f}"


def write_lists(root: Path, prefix: str, split_records: dict[str, list[ImageRecord]]) -> dict[str, int]:
    counts = {}
    for split, recs in split_records.items():
        path = root / f"{prefix}_{YOLO_SPLIT_NAMES[split]}.txt"
        lines = [f"./images/{rec.name}" for rec in sorted(recs, key=lambda r: r.name)]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        counts[split] = len(lines)
    return counts


def write_data_yaml(path: Path, prefix: str, comment: str) -> None:
    content = (
        f"# {comment}\n"
        "# 'path' se omite a propósito: Ultralytics usa la carpeta de este archivo.\n"
        f"train: {prefix}_train.txt\n"
        f"val: {prefix}_val.txt\n"
        f"test: {prefix}_test.txt\n"
        "nc: 1\n"
        f"names:\n  0: {TARGET_CLASS}\n"
    )
    path.write_text(content, encoding="utf-8")


def choose_eval_variant(recs: list[ImageRecord], mode: str) -> list[ImageRecord]:
    if mode == "all":
        return recs
    by_source = defaultdict(list)
    for rec in recs:
        by_source[rec.source].append(rec)
    return [sorted(items, key=lambda r: r.name)[0] for items in by_source.values()]


def write_review_sheets(zip_path: Path, records: list[ImageRecord], review_dir: Path, samples: int,
                        overlap_names: set[str]) -> dict[str, int]:
    """Hojas 4x5 con cuadros (verde) y polígonos (cian) para la revisión visual manual."""
    review_dir.mkdir(parents=True, exist_ok=True)
    ready = [r for r in records if r.detect_ready]
    selections = {
        "muestra_aleatoria": random.Random(0).sample(ready, min(samples, len(ready))),
        "etiqueta_vacia": [r for r in records if r.label_status == "empty"],
        "etiqueta_invalida": [r for r in records if r.label_status == "invalid"],
        "objetos_superpuestos": [r for r in records if r.name in overlap_names],
        "segmentacion_mixta": [r for r in records if r.segment_status == "mixta"],
    }
    cols, rows, tile = 4, 5, (320, 180)
    index_rows = []
    written = {}
    with zipfile.ZipFile(zip_path) as archive:
        for label, recs in selections.items():
            for sheet_no in range(math.ceil(len(recs) / (cols * rows))):
                chunk = recs[sheet_no * cols * rows:(sheet_no + 1) * cols * rows]
                sheet = Image.new("RGB", (cols * tile[0], rows * tile[1]), "white")
                sheet_name = f"{label}_{sheet_no + 1:02d}.jpg"
                for pos, rec in enumerate(chunk):
                    with Image.open(io.BytesIO(archive.read(rec.image_member))) as img:
                        canvas = img.convert("RGB")
                    draw = ImageDraw.Draw(canvas)
                    w, h = canvas.size
                    for obj in rec.objects:
                        if obj.points:
                            draw.polygon([(x * w, y * h) for x, y in obj.points], outline=(0, 255, 255))
                        if obj.box:
                            cx, cy, bw, bh = obj.box
                            draw.rectangle([(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w,
                                            (cy + bh / 2) * h], outline=(0, 255, 0), width=3)
                    draw.rectangle([0, 0, 34, 22], fill=(0, 0, 0))
                    draw.text((4, 4), str(pos), fill=(255, 255, 0))
                    sheet.paste(canvas.resize(tile), ((pos % cols) * tile[0], (pos // cols) * tile[1]))
                    index_rows.append([sheet_name, pos, rec.split, rec.name, rec.label_status, rec.segment_status])
                sheet.save(review_dir / sheet_name, quality=85)
                written[label] = written.get(label, 0) + len(chunk)
    write_csv(review_dir / "index.csv", ["sheet", "tile", "original_split", "image", "label_status",
                                         "segment_status"], index_rows)
    return written


def write_csv(path: Path, header: list[str], rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


# --------------------------------------------------------------------------- principal


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", required=True, type=Path, help="ZIP YOLOv8 exportado por Roboflow (solo lectura).")
    parser.add_argument("--output", type=Path, default=output_data_dir() / DATASET_ID,
                        help=f"Carpeta de salida (por defecto <{DATA_DIR_ENV} o ..\\dataset>/{DATASET_ID}).")
    parser.add_argument("--overwrite", action="store_true", help="Regenera una salida previa de este script.")
    parser.add_argument("--audit-only", action="store_true", help="Solo escribe audit/, sin copiar imágenes.")
    parser.add_argument("--include-empty", action="store_true",
                        help="Incluye imágenes con etiqueta vacía como negativas. NO usar con este ZIP: en la "
                             "revisión manual las 14 imágenes vacías contienen camarones sin anotar.")
    parser.add_argument("--gap-seconds", type=float, default=60.0,
                        help="Separación mínima entre particiones en la partición agrupada.")
    parser.add_argument("--video-span-seconds", type=float, default=180.0,
                        help="Duración supuesta de cada vídeo (la real no está en los nombres).")
    parser.add_argument("--near-dup-bits", type=int, default=16,
                        help="Distancia máxima (de 256 bits dHash) para listar casi-duplicados en el informe.")
    parser.add_argument("--near-dup-union-bits", type=int, default=8,
                        help="Distancia máxima para unir fuentes en un grupo. Más estricta porque el fondo fijo de "
                             "la plataforma acerca imágenes de camarones distintos (verificado visualmente).")
    parser.add_argument("--review-samples", type=int, default=60,
                        help="Imágenes aleatorias (semilla fija) dibujadas en audit/review/ para revisión visual.")
    parser.add_argument("--valid-fraction", type=float, default=0.10)
    parser.add_argument("--test-fraction", type=float, default=0.10)
    parser.add_argument("--min-groups", type=int, default=6)
    parser.add_argument("--max-group-share", type=float, default=0.40)
    parser.add_argument("--min-attribute-objects", type=int, default=20,
                        help="Objetos mínimos para contar un tamaño o estado cabeza/cola como cubierto en valid/test.")
    parser.add_argument("--eval-variants", choices=("one", "all"), default="one",
                        help="Variantes aumentadas por fuente en valid/test de la partición agrupada.")
    args = parser.parse_args(argv)

    zip_path = args.zip.resolve()
    if not zip_path.is_file():
        raise SystemExit(f"No existe el ZIP: {zip_path}")
    output = args.output if args.output.is_absolute() else (Path.cwd() / args.output)
    prepare_output_dir(output, args.overwrite, zip_path)
    audit_dir = output / "audit"
    audit_dir.mkdir()
    zip_stat_before = zip_path.stat()
    zip_sha = sha256_file(zip_path)

    findings, records, data_yaml = audit_zip(zip_path)
    class_names = list(data_yaml["names"])
    class_info = [dict(parse_class_name(n), id=i) for i, n in enumerate(class_names)]

    print("[3/6] Buscando duplicados exactos y casi-duplicados...", flush=True)
    near_pairs = near_duplicate_pairs(records, args.near_dup_bits)
    sha_groups = defaultdict(list)
    label_groups = defaultdict(list)
    for rec in records:
        sha_groups[rec.sha256].append(rec)
        if rec.label_sha256 and rec.label_status == "ok":
            label_groups[rec.label_sha256].append(rec)
    overlap_images = []
    for rec in records:
        boxes = [o.box for o in rec.objects if o.box]
        if any(box_iou(a, b) >= OVERLAP_IOU for a, b in itertools.combinations(boxes, 2)):
            overlap_images.append(rec.name)

    print("[4/6] Analizando fuga entre particiones...", flush=True)
    intervals = source_intervals(records, args.video_span_seconds)
    leakage = analyze_original_leakage(records, intervals, near_pairs, args.gap_seconds)
    grouped = build_grouped_split(records, intervals, near_pairs, class_info, args)

    # Estado por imagen.
    for rec in records:
        rec.in_detect = rec.detect_ready or (args.include_empty and rec.label_status == "empty" and not rec.image_issues)
        if not rec.detect_ready:
            rec.segment_status = "no_aplica"
        else:
            kinds = {o.geometry for o in rec.objects}
            if kinds == {"box"}:
                rec.segment_status = "solo_cuadros"
            elif kinds == {"polygon", "box"}:
                rec.segment_status = "mixta"
            elif all(o.polygon_valid for o in rec.objects):
                rec.segment_status = "poligonos_validos"
            else:
                rec.segment_status = "poligono_no_valido"
        rec.in_segment = rec.segment_status == "poligonos_validos"
        rec.group = grouped["group_of_source"].get(rec.source, "")
        if grouped["reliable"]:
            rec.grouped_split = grouped["split_of_source"][rec.source]

    outputs: dict = {}
    if not args.audit_only:
        print("[5/6] Escribiendo conjuntos de detección y segmentación...", flush=True)
        detect_dir, segment_dir = output / "detect", output / "segment"
        for folder in (detect_dir / "images", detect_dir / "labels", segment_dir / "images", segment_dir / "labels"):
            folder.mkdir(parents=True)
        with zipfile.ZipFile(zip_path) as archive:
            for rec in records:
                if not (rec.in_detect or rec.in_segment):
                    continue
                stem = Path(rec.name).stem
                image_dst = detect_dir / "images" / rec.name
                image_dst.write_bytes(archive.read(rec.image_member))
                lines = [f"0 {' '.join(fmt(v) for v in o.box)}" for o in rec.objects if o.box]
                (detect_dir / "labels" / f"{stem}.txt").write_text(
                    "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
                if rec.in_segment:
                    link_or_copy(image_dst, segment_dir / "images" / rec.name)
                    seg_lines = [f"0 {' '.join(fmt(v) for pt in o.points for v in pt)}" for o in rec.objects]
                    (segment_dir / "labels" / f"{stem}.txt").write_text("\n".join(seg_lines) + "\n", encoding="utf-8")

        def per_split(selector, split_attr):
            groups = {split: [] for split in SPLITS}
            for rec in records:
                if selector(rec) and getattr(rec, split_attr):
                    groups[getattr(rec, split_attr)].append(rec)
            return groups

        for name, root, selector in (("detect", detect_dir, lambda r: r.in_detect),
                                     ("segment", segment_dir, lambda r: r.in_segment)):
            original = per_split(selector, "split")
            outputs[f"{name}_original"] = write_lists(root, "original", original)
            write_data_yaml(root / "data_original_split.yaml", "original",
                            f"SMART SHRIMP {name}: partición ORIGINAL de Roboflow. Tiene fuga entre "
                            "particiones; usar solo para comparar, no para reportar métricas.")
            if grouped["reliable"]:
                split_groups = per_split(selector, "grouped_split")
                for split in ("valid", "test"):
                    split_groups[split] = choose_eval_variant(split_groups[split], args.eval_variants)
                outputs[f"{name}_grouped"] = write_lists(root, "grouped", split_groups)
                write_data_yaml(root / "data_grouped.yaml", "grouped",
                                f"SMART SHRIMP {name}: partición AGRUPADA por sesión temporal/vídeo "
                                f"(separación > {args.gap_seconds:g} s). Ver audit/audit_report.md.")
                for rec in itertools.chain.from_iterable(split_groups.values()):
                    rec.grouped_lists.add(name)

    print("[6/6] Escribiendo auditoría y hojas de revisión...", flush=True)
    outputs["review_sheets"] = write_review_sheets(zip_path, records, audit_dir / "review", args.review_samples,
                                                   set(overlap_images))
    # Mapa de clases.
    (audit_dir / "class_map.json").write_text(json.dumps({
        "target": {"0": TARGET_CLASS},
        "note": ("Todas las clases originales se fusionan en 'camaron'. El tamaño es una categoría visual "
                 "del anotador, no una longitud en cm. Cabeza/cola indican integridad visible."),
        "original_classes": class_info,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    write_csv(audit_dir / "images.csv", [
        "original_split", "image", "source", "kind", "timestamp", "video_id", "video_frame", "width", "height",
        "format", "sha256", "label_status", "image_issues", "label_issues", "objects", "polygons", "boxes",
        "segment_status", "in_detect", "in_segment", "group", "grouped_split", "in_grouped_list",
    ], ([
        r.split, r.name, r.source, r.kind, r.timestamp.isoformat() if r.timestamp else "", r.video_id or "",
        "" if r.video_frame is None else r.video_frame, r.width, r.height, r.image_format, r.sha256,
        r.label_status, ";".join(r.image_issues), ";".join(r.label_issues), len(r.objects),
        sum(o.geometry == "polygon" for o in r.objects), sum(o.geometry == "box" for o in r.objects),
        r.segment_status, int(r.in_detect), int(r.in_segment), r.group, r.grouped_split,
        ";".join(sorted(r.grouped_lists)),
    ] for r in records))

    def object_rows():
        for r in records:
            for o in r.objects:
                info = class_info[o.class_id] if o.class_id is not None and 0 <= o.class_id < len(class_info) else {}
                box = o.box or ("", "", "", "")
                yield [r.split, r.name, o.line, "" if o.class_id is None else o.class_id, info.get("name", ""),
                       info.get("size_label", ""), info.get("has_head", ""), info.get("has_tail", ""),
                       o.geometry, len(o.points), *[fmt(v) if v != "" else "" for v in box],
                       round(o.box[2] * r.width, 1) if o.box else "", round(o.box[3] * r.height, 1) if o.box else "",
                       int(o.polygon_valid), ";".join(o.issues), ";".join(o.warnings), int(r.in_detect),
                       int(r.in_segment)]

    write_csv(audit_dir / "objects.csv", [
        "original_split", "image", "label_line", "orig_class_id", "orig_class_name", "size_label", "has_head",
        "has_tail", "geometry", "polygon_points", "cx", "cy", "w", "h", "w_px", "h_px", "polygon_valid",
        "issues", "warnings", "image_in_detect", "image_in_segment",
    ], object_rows())

    write_csv(audit_dir / "near_duplicates.csv", ["image_a", "split_a", "image_b", "split_b", "dhash_bits"],
              ([records[a].name, records[a].split, records[b].name, records[b].split, d] for a, b, d in near_pairs))

    source_rows = defaultdict(lambda: {"splits": set(), "images": 0})
    for r in records:
        row = source_rows[r.source]
        row["splits"].add(r.split)
        row["images"] += 1
        row.update(kind=r.kind, timestamp=r.timestamp.isoformat() if r.timestamp else "", video=r.video_id or "",
                   group=r.group, grouped_split=r.grouped_split)
    write_csv(audit_dir / "sources_and_groups.csv",
              ["source", "kind", "timestamp", "video_id", "original_splits", "images", "group", "grouped_split"],
              ([s, v["kind"], v["timestamp"], v["video"], ";".join(sorted(v["splits"])), v["images"], v["group"],
                v["grouped_split"]] for s, v in sorted(source_rows.items())))

    # Estadísticas.
    stats = compute_stats(records, class_info, grouped)
    findings["duplicates"] = {
        "exact_image_duplicate_groups": sum(1 for v in sha_groups.values() if len(v) > 1),
        "exact_image_duplicate_images": sum(len(v) for v in sha_groups.values() if len(v) > 1),
        "identical_label_files_groups": sum(1 for v in label_groups.values() if len(v) > 1
                                            and len({r.source for r in v}) > 1),
        "near_duplicate_pairs_different_source": len(near_pairs),
        "near_duplicate_distance_histogram": dict(sorted(Counter(d for _, _, d in near_pairs).items())),
        "images_with_overlapping_objects_iou_ge_0_9": len(overlap_images),
        "overlapping_examples": overlap_images[:20],
    }
    summary = {
        "dataset_id": DATASET_ID,
        "script_version": SCRIPT_VERSION,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "zip": {"path": str(zip_path), "sha256": zip_sha, "bytes": zip_stat_before.st_size},
        "arguments": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "findings": findings,
        "stats": stats,
        "leakage_original": leakage,
        "grouped_split": {k: v for k, v in grouped.items() if k not in ("group_of_source", "split_of_source")},
        "outputs": outputs,
    }
    zip_stat_after = zip_path.stat()
    summary["zip"]["unchanged_after_run"] = (
        zip_stat_after.st_size == zip_stat_before.st_size and zip_stat_after.st_mtime == zip_stat_before.st_mtime
        and sha256_file(zip_path) == zip_sha
    )
    (audit_dir / "audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                                          encoding="utf-8")
    (audit_dir / "audit_report.md").write_text(render_report(summary, class_info), encoding="utf-8")
    (output / "README.md").write_text(render_dataset_readme(summary), encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps({
        "dataset_id": DATASET_ID, "script_version": SCRIPT_VERSION, "zip_sha256": zip_sha,
        "generated_at": summary["generated_at"], "outputs": outputs,
        "grouped_split_reliable": grouped["reliable"],
    }, indent=2), encoding="utf-8")
    print(f"Listo. Informe: {audit_dir / 'audit_report.md'}")
    return 0


def compute_stats(records: list[ImageRecord], class_info: list[dict], grouped: dict) -> dict:
    stats: dict = {}
    stats["images_total"] = len(records)
    stats["sources_total"] = len({r.source for r in records})
    stats["variants_per_source_by_split"] = {
        split: dict(Counter(Counter(r.source for r in records if r.split == split).values()))
        for split in SPLITS
    }
    stats["image_dimensions"] = {f"{w}x{h}": c for (w, h), c in Counter((r.width, r.height) for r in records).items()}
    stats["image_formats"] = dict(Counter(f"{r.image_format}/{r.image_mode}" for r in records))
    stats["image_issues"] = dict(Counter(i for r in records for i in r.image_issues))
    stats["label_status"] = {split: dict(Counter(r.label_status for r in records if r.split == split))
                             for split in SPLITS}
    stats["label_file_issues"] = dict(Counter(i for r in records for i in r.label_issues))
    objects = [(r, o) for r in records for o in r.objects]
    stats["objects_total"] = len(objects)
    stats["objects_by_geometry"] = dict(Counter(o.geometry for _, o in objects))
    stats["object_issues"] = dict(Counter(i for _, o in objects for i in o.issues))
    stats["object_warnings"] = dict(Counter(w for _, o in objects for w in o.warnings))
    stats["objects_clipped"] = sum(o.clipped for _, o in objects)
    stats["objects_by_class_and_split"] = {
        info["name"]: {split: sum(1 for r, o in objects if o.class_id == info["id"] and r.split == split)
                       for split in SPLITS}
        for info in class_info
    }
    stats["objects_per_image"] = dict(sorted(Counter(len(r.objects) for r in records).items()))
    stats["segment_status"] = dict(Counter(r.segment_status for r in records))
    stats["box_size_px"] = {
        "width": quantiles([o.box[2] * r.width for r, o in objects if o.box]),
        "height": quantiles([o.box[3] * r.height for r, o in objects if o.box]),
    }
    stats["detect_images"] = sum(r.in_detect for r in records)
    stats["segment_images"] = sum(r.in_segment for r in records)
    stats["detect_objects"] = sum(len(r.objects) for r in records if r.in_detect)
    stats["segment_objects"] = sum(len(r.objects) for r in records if r.in_segment)
    if grouped["reliable"]:
        listed = [r for r in records if "detect" in r.grouped_lists]
        by_split = defaultdict(Counter)
        attrs = defaultdict(lambda: defaultdict(Counter))
        for r in listed:
            by_split[r.grouped_split]["images"] += 1
            by_split[r.grouped_split]["objects"] += len(r.objects)
            for o in r.objects:
                info = class_info[o.class_id]
                attrs[r.grouped_split]["size_label"][info["size_label"]] += 1
                attrs[r.grouped_split]["head_tail"][
                    f"{'con' if info['has_head'] else 'sin'}cabeza-{'con' if info['has_tail'] else 'sin'}cola"] += 1
        stats["grouped_detect_lists"] = {s: dict(by_split[s]) for s in SPLITS}
        stats["grouped_detect_attributes"] = {s: {k: dict(v) for k, v in attrs[s].items()} for s in SPLITS}
        stats["grouped_sources_by_split"] = dict(Counter(grouped["split_of_source"].values()))
        stats["grouped_groups_by_split"] = {s: sorted(g for g, sp in grouped["assignment"].items() if sp == s)
                                            for s in SPLITS}
    return stats


# --------------------------------------------------------------------------- informes


def _yes(flag: bool) -> str:
    return "Sí" if flag else "No"


def render_report(s: dict, class_info: list[dict]) -> str:
    f, st, lk, gs = s["findings"], s["stats"], s["leakage_original"], s["grouped_split"]
    z = f["zip"]
    dy = f["structure"]["data_yaml"]
    rf = dy.get("roboflow", {})
    lines = [
        "# Auditoría del dataset `shrimp-object-tracking-and-counting` v4",
        "",
        f"Generado por `training/scripts/prepare_shrimp_dataset.py` v{s['script_version']} el {s['generated_at']}.",
        "",
        "> Este informe distingue lo **verificado automáticamente** de lo que **sigue pendiente de revisión visual**.",
        "> Ninguna verificación automática garantiza que las anotaciones sean correctas: solo que son coherentes.",
        "",
        "## 1. Origen, licencia y atribución",
        "",
        f"- Proyecto Roboflow: `{rf.get('workspace')}/{rf.get('project')}`, versión {rf.get('version')}.",
        f"- URL: {rf.get('url')}",
        f"- Licencia declarada en el ZIP: **{rf.get('license')}** (conservar esta atribución al redistribuir).",
        "- Exportado por Roboflow el 19-03-2023 (README del ZIP). Preprocesado: auto-orientación y redimensión a "
        "640x490 (fit within). Aumento: 3 versiones por imagen fuente (volteo horizontal, giros de 90°, "
        "rotación ±13°, desenfoque gaussiano).",
        f"- ZIP: `{s['zip']['path']}`",
        f"- SHA-256: `{s['zip']['sha256']}` ({s['zip']['bytes']:,} bytes). "
        f"Sin cambios tras la ejecución: **{_yes(s['zip']['unchanged_after_run'])}**.",
        "",
        "## 2. Verificaciones automáticas",
        "",
        "| Verificación | Resultado |",
        "|---|---|",
        f"| CRC de todas las entradas del ZIP | {'correcto' if z['crc_ok'] else 'FALLO: ' + str(z['first_bad_member'])} |",
        f"| Rutas seguras (sin absolutas, `..`, enlaces, cifrado, ratios sospechosos) | "
        f"{'sin problemas' if not z['unsafe_members'] else len(z['unsafe_members'])} |",
        f"| Nombres duplicados / colisiones por mayúsculas | {len(z['duplicate_member_names'])} / "
        f"{len(z['case_insensitive_collisions'])} |",
        f"| `data.yaml`: nc={dy['nc']}, nombres={dy['names_count']}, únicos, patrón tamaño-cabeza-cola | "
        f"{_yes(dy['nc_matches_names'])}, {_yes(dy['names_unique'])}, {_yes(dy['all_names_parse'])} |",
        f"| Archivos fuera de la estructura `split/images|labels` | {len(f['unexpected_members'])} |",
        f"| Etiquetas sin imagen | {len(f['structure']['labels_without_image'])} |",
        f"| Nombres de imagen repetidos entre particiones | "
        f"{len(f['structure']['basename_collisions_across_splits'])} |",
        f"| Imágenes decodificables (PIL verify + load) | {st['images_total'] - sum(st['image_issues'].values())}"
        f" de {st['images_total']} |",
        f"| Dimensiones | {st['image_dimensions']} |",
        f"| Formatos | {st['image_formats']} |",
        f"| Problemas en archivos de etiqueta | {st['label_file_issues'] or 'ninguno'} |",
        f"| Objetos con errores (clase, coordenadas, nº de valores, cuadro degenerado) | "
        f"{st['object_issues'] or 'ninguno'} |",
        f"| Avisos de objetos | {st['object_warnings'] or 'ninguno'} |",
        f"| Objetos recortados por tolerancia ±{COORD_TOLERANCE} | {st['objects_clipped']} |",
        f"| Imágenes con hash idéntico (grupos / imágenes) | {f['duplicates']['exact_image_duplicate_groups']} / "
        f"{f['duplicates']['exact_image_duplicate_images']} |",
        f"| Archivos de etiqueta idénticos entre fuentes distintas | "
        f"{f['duplicates']['identical_label_files_groups']} |",
        f"| Pares casi duplicados (dHash 256 bits ≤ {s['arguments']['near_dup_bits']}, invariante a volteos/90°, "
        "fuentes distintas; informativo, ver §6) | "
        f"{f['duplicates']['near_duplicate_pairs_different_source']} "
        f"(histograma: {f['duplicates']['near_duplicate_distance_histogram']}) |",
        f"| Imágenes con dos objetos de IoU ≥ {OVERLAP_IOU} (posible doble anotación) | "
        f"{f['duplicates']['images_with_overlapping_objects_iou_ge_0_9']} |",
        "",
        "## 3. Conteos",
        "",
        f"- Imágenes: **{st['images_total']}** ({f['structure']['images_per_split']}); "
        f"imágenes fuente distintas: **{st['sources_total']}**.",
        f"- Variantes por fuente (variantes: nº de fuentes): {st['variants_per_source_by_split']}. "
        "En train cada fuente aparece aumentada; valid/test tienen una imagen por fuente.",
        f"- Estado de etiquetas por partición: {st['label_status']}.",
        f"- Objetos anotados: **{st['objects_total']}**; por geometría: {st['objects_by_geometry']}.",
        f"- Objetos por imagen (objetos: imágenes): {st['objects_per_image']}.",
        f"- Tamaño de cuadros en píxeles: ancho {st['box_size_px']['width']}, alto {st['box_size_px']['height']}.",
        "",
        "### Objetos por clase original",
        "",
        "| id | clase | tamaño (visual) | cabeza | cola | train | valid | test |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for info in class_info:
        c = st["objects_by_class_and_split"][info["name"]]
        lines.append(f"| {info['id']} | `{info['name']}` | {info.get('size_label')} | {_yes(info.get('has_head'))} | "
                     f"{_yes(info.get('has_tail'))} | {c['train']} | {c['valid']} | {c['test']} |")
    lines += [
        "",
        "## 4. Geometría de las anotaciones y segmentación",
        "",
        f"Estado de segmentación por imagen: {st['segment_status']}.",
        "",
        "- `poligonos_validos`: todos los objetos tienen polígono válido (≥3 puntos distintos, área > 0, sin "
        "autointersección). Son las únicas imágenes del conjunto `segment/`.",
        "- `mixta`: combina polígonos y cuadros. Excluida de segmentación para no tratar como fondo a un camarón sin "
        "máscara. Sí se usa en detección.",
        "- `solo_cuadros`: sin máscaras. Solo detección.",
        "- `poligono_no_valido`: algún polígono degenerado o autointersectado. Solo detección (su cuadro sí es válido).",
        "- `no_aplica`: etiqueta vacía, ausente o inválida. Excluida de ambos conjuntos.",
        "",
        "Listado completo en `audit/images.csv` (columna `segment_status`) y por objeto en `audit/objects.csv`.",
        "",
        "## 5. Fuga en la partición original train/valid/test",
        "",
        f"- Misma imagen fuente en varias particiones: {lk['sources_in_multiple_splits']}.",
        f"- Imágenes idénticas (hash) en varias particiones: {lk['exact_duplicate_hashes_across_splits']}.",
        f"- Segundos de captura compartidos entre particiones: {lk['seconds_shared_between_splits']} de "
        f"{lk['seconds_total']}.",
        f"- Vídeos con fotogramas en más de una partición: **{lk['videos_split_across_partitions']} de "
        f"{len(lk['videos'])}**.",
        f"- Separación temporal mínima entre particiones (s): {lk['min_time_gap_seconds_between_splits']}.",
        f"- Fuentes de valid/test con una fuente de train cercana en el tiempo: "
        f"{lk['eval_sources_with_nearby_train_source']}.",
        f"- Pares casi duplicados entre particiones: {lk['near_duplicate_pairs_across_splits'] or 'ninguno'}.",
        "",
        "| vídeo | fotogramas por partición |",
        "|---|---|",
        *[f"| `{vid}` | {counts} |" for vid, counts in lk["videos"].items()],
        "",
        "**Conclusión:** la partición original mezcla fotogramas del mismo vídeo y fotos tomadas con segundos de "
        "diferencia entre train, valid y test. Las métricas obtenidas con ella estarán **sobreestimadas** y no "
        "deben reportarse como rendimiento esperado.",
        "",
        "## 6. Partición agrupada",
        "",
        f"Parámetros: {gs['parameters']}.",
        "",
        "Método: se unen en un mismo grupo (union-find) las fuentes del mismo vídeo, las imágenes con hash idéntico, "
        "las capturas separadas por ≤ `gap_seconds` en una línea de tiempo común (cada vídeo ocupa "
        "`[inicio, inicio + video_span_seconds]`, porque su duración real no está en los nombres) y los pares casi "
        f"duplicados con distancia ≤ {gs['parameters']['near_duplicate_union_bits']} bits. Luego se asignan "
        "grupos completos a test y valid (búsqueda exhaustiva determinista) entre las combinaciones con "
        "50–200 % de la fracción objetivo, maximizando primero la cobertura de tamaños y de estados "
        "cabeza/cola y después la cercanía a la fracción.",
        "",
        "Sobre los casi-duplicados: el fondo fijo (banda oscura y rieles metálicos) acerca en el hash imágenes de "
        "camarones distintos. En la inspección manual inicial, los pares que unían sesiones distintas "
        "(11–16 bits, separados 2–25 min) mostraban camarones diferentes, por eso para unir grupos se usa un umbral "
        f"más estricto que el de informe ({gs['parameters']['near_duplicate_report_bits']} bits). Los pares "
        "informativos están en `audit/near_duplicates.csv`.",
        "",
        f"- Uniones: {gs['union_edges']}.",
        f"- Grupos: **{gs['groups']}**; fuentes por grupo: {gs['group_sizes_sources']}; grupo mayor: "
        f"{gs['largest_group_share']:.1%}.",
    ]
    if gs["reliable"]:
        lines += [
            f"- Grupos por partición: {st['grouped_groups_by_split']}.",
            f"- Fuentes por partición: {st['grouped_sources_by_split']}.",
            f"- Listas de detección ({'una variante' if s['arguments']['eval_variants'] == 'one' else 'todas las variantes'}"
            f" por fuente en valid/test): {st['grouped_detect_lists']}.",
            f"- Atributos por partición (objetos): {st['grouped_detect_attributes']}.",
            f"- Verificación independiente: {gs['verification']}.",
            "",
            f"**Resultado:** partición agrupada generada. Ningún par de imágenes de particiones distintas está a "
            f"≤ {gs['parameters']['gap_seconds']:g} s (con el supuesto de duración de vídeo), ni comparte vídeo, hash o "
            "casi-duplicado. Limitaciones que siguen abiertas:",
            "",
            "- Solo hay 2 días de captura y pocas sesiones; con tan pocos grupos la varianza de las métricas es alta.",
            "- **Cada sesión se grabó casi con una sola clase** (ver `group_dominant_class_share` en `audit.json`). "
            "Por eso valid/test no pueden contener las 12 clases sin fuga: sirven para evaluar la detección de "
            "`camaron`, no para comparar métricas por tamaño o cabeza/cola.",
            "- No se puede verificar desde los metadatos si los **mismos camarones** se reutilizaron en sesiones "
            "distintas; eso requiere revisión visual.",
            "- Las imágenes de valid/test que provienen de la antigua train son variantes **aumentadas** (rotación, "
            "desenfoque); no hay copia sin aumentar en el ZIP.",
            "- La duración real de los vídeos es un supuesto (`video_span_seconds`).",
        ]
    else:
        lines += [
            "",
            "**Resultado:** NO se generó una partición agrupada porque no cumple los criterios de fiabilidad:",
            *[f"- {reason}" for reason in gs["reasons"]],
            "",
            "Solo existe la partición original, que tiene fuga. Hace falta información adicional (identificador de "
            "grabación, lote o ejemplar) o nuevas capturas independientes para evaluar de forma fiable.",
        ]
    lines += [
        "",
        "## 7. Conjuntos generados",
        "",
        f"- Detección (`detect/`, 1 clase `{TARGET_CLASS}`): {st['detect_images']} imágenes, "
        f"{st['detect_objects']} objetos. Polígonos → cuadro mínimo envolvente; cuadros originales conservados.",
        f"- Segmentación (`segment/`): {st['segment_images']} imágenes, {st['segment_objects']} objetos, todos con "
        "polígono original.",
        f"- Listas por partición: {s['outputs'] or 'no generadas (--audit-only)'}.",
        f"- Imágenes con etiqueta vacía incluidas como negativas: {_yes(s['arguments']['include_empty'])}.",
        "- Mapa de las 12 clases originales: `audit/class_map.json`; atributos por objeto: `audit/objects.csv` "
        "(`label_line` coincide con la línea del archivo de etiqueta generado).",
        "",
        "## 8. Pendiente de revisión visual",
        "",
        f"Hojas de revisión (cuadro verde, polígono cian) en `audit/review/` con índice en `index.csv`: "
        f"{s['outputs'].get('review_sheets')}. Los hallazgos de la inspección manual inicial están en "
        "`docs/dataset_shrimp_roboflow_v4.md`.",
        "",
        "- **Camarones visibles sin anotar**: en la muestra aleatoria inicial de 60 imágenes, ≈25 % (15/60) tiene "
        "al menos un camarón claramente visible sin anotar (hasta ≈37 % contando casos dudosos). Las 14 imágenes "
        "con etiqueta vacía también contienen camarones. Afecta al recall, al conteo y a las métricas (detecciones "
        "correctas contarán como falsos positivos). Reanotar al menos valid/test antes de confiar en las métricas.",
        "- **Imágenes compuestas** (recortes rectangulares de camarón pegados sobre el fondo): presentes en la "
        "muestra; no se detectan automáticamente.",
        "- **Objetos distractores** (memorias USB, anillos, cinta, tarjetas, tornillos) sin clase propia.",
        "- Que cada camarón visible esté anotado y que no haya cuadros sobre objetos que no son camarón.",
        "- Si las imágenes con etiqueta vacía son realmente negativas (sin camarones) o están sin anotar.",
        "- Calidad y ajuste de los polígonos (los avisos de polígonos degenerados/autointersectados se listan en "
        "`objects.csv`).",
        "- Imágenes con objetos superpuestos (IoU ≥ 0.9): ¿doble anotación o camarones apilados?",
        "- Coherencia de las etiquetas de tamaño y de cabeza/cola entre anotadores.",
        "- Superficies, iluminación y cámaras representadas. Las muestras sugieren principalmente una plataforma "
        "oscura y seca; **no** hay evidencia de generalización a otras superficies.",
        "- Reutilización de los mismos ejemplares entre sesiones (afecta a la independencia de la partición).",
        "",
        "## 9. Lo que este dataset no aporta",
        "",
        "- Longitud real en cm: no hay escala ni referencia métrica. El tamaño es una categoría visual.",
        "- Peso: no hay etiquetas de peso.",
        "- Frescura o condición visual (fresco/intermedio/deteriorado): no hay etiquetas.",
        "- Presentación (con cáscara/pelado): no hay etiquetas.",
        "- Camarones en agua u otras superficies: no representado.",
        "",
    ]
    return "\n".join(lines)


def render_dataset_readme(s: dict) -> str:
    rf = s["findings"]["structure"]["data_yaml"].get("roboflow", {})
    grouped = s["grouped_split"]["reliable"]
    return "\n".join([
        f"# {DATASET_ID} (generado, no versionar)",
        "",
        f"Derivado de {rf.get('url')} — licencia {rf.get('license')}. Atribución: Roboflow Universe, "
        f"workspace `{rf.get('workspace')}`.",
        "",
        "Generado por `training/scripts/prepare_shrimp_dataset.py`. Ver `audit/audit_report.md`.",
        "",
        "- `detect/data_grouped.yaml`: detección 1 clase, partición agrupada sin fuga temporal "
        + ("(usar esta)." if grouped else "(NO generada: ver informe)."),
        "- `detect/data_original_split.yaml`: partición original de Roboflow, con fuga; solo para comparar.",
        "- `segment/`: segmentación 1 clase, solo imágenes con todos los polígonos válidos.",
        "- `audit/`: informe, inventarios CSV y mapa de clases originales.",
        "",
    ])


if __name__ == "__main__":
    sys.exit(main())
