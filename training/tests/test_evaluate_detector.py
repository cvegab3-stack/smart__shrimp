"""Pruebas de evaluate_detector.py con un dataset falso de pocas imágenes y un ultralytics simulado.

No necesitan el dataset real, GPU ni ultralytics instalado (solo Pillow):
    python -m pytest training/tests
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import evaluate_detector as ed  # noqa: E402

SIZE = 256
# Un camarón en la esquina inferior derecha: deja libre la esquina superior izquierda para el recorte negativo.
LABEL = "0 0.9 0.9 0.1 0.1\n"


def make_image(dataset: Path, name: str, color: tuple[int, int, int]) -> None:
    (dataset / "images").mkdir(parents=True, exist_ok=True)
    (dataset / "labels").mkdir(exist_ok=True)
    Image.new("RGB", (SIZE, SIZE), color).save(dataset / "images" / name)
    (dataset / "labels" / f"{Path(name).stem}.txt").write_text(LABEL, encoding="utf-8")


def write_list(dataset: Path, listing: str, names: list[str]) -> None:
    (dataset / listing).write_text("".join(f"./images/{n}\n" for n in names), encoding="utf-8")


def write_yamls(dataset: Path, subsets) -> None:
    for subset in subsets:
        (dataset / f"data_{subset}.yaml").write_text(f"# falso: {subset}\n", encoding="utf-8")


@pytest.fixture
def v3_dataset(tmp_path: Path) -> Path:
    """Estructura de shrimp_combined_v3: las listas heredadas de v2 llevan el prefijo v2_."""
    dataset = tmp_path / "shrimp_combined_v3"
    make_image(dataset, "a.jpg", (200, 30, 30))
    make_image(dataset, "b.jpg", (30, 200, 30))
    make_image(dataset, "c.jpg", (30, 30, 200))
    make_image(dataset, "nv2_video_de_camaron_1_0001.jpg", (120, 120, 120))
    write_list(dataset, "v2_test_new.txt", ["a.jpg", "b.jpg"])
    write_list(dataset, "test_baldosa.txt", ["nv2_video_de_camaron_1_0001.jpg"])
    write_list(dataset, "train.txt", ["c.jpg"])
    write_yamls(dataset, ["test_new", "test_baldosa"])
    return dataset


@pytest.fixture
def v2_dataset(tmp_path: Path) -> Path:
    """Estructura de shrimp_combined_v2: <s>.txt para los cuatro subconjuntos por defecto."""
    dataset = tmp_path / "shrimp_combined_v2"
    colors = [(200, 30, 30), (30, 200, 30), (30, 30, 200)]
    for k, color in enumerate(colors):
        make_image(dataset, f"img{k}.jpg", color)
    for subset in ed.SUBSETS:
        write_list(dataset, f"{subset}.txt", ["img0.jpg", "img1.jpg"])
    write_list(dataset, "train.txt", ["img2.jpg"])
    write_yamls(dataset, ed.SUBSETS)
    return dataset


@pytest.fixture
def model(tmp_path: Path) -> Path:
    path = tmp_path / "falso.pt"
    path.write_bytes(b"pesos falsos")
    return path


class FakeTensor(list):
    def tolist(self):
        return list(self)


class FakeBox:
    def __init__(self, xyxy):
        self.conf = [0.9]
        self.xyxy = [FakeTensor(xyxy)]


@pytest.fixture
def fake_yolo(monkeypatch):
    """ultralytics simulado: registra los iou usados y 'detecta' exactamente las cajas de cada etiqueta."""
    calls = {"val": [], "predict": []}

    class YOLO:
        def __init__(self, path):
            self.path = path

        def val(self, **kwargs):
            calls["val"].append(kwargs)
            box = types.SimpleNamespace(mp=1.0, mr=1.0, map50=1.0, map=0.9)
            return types.SimpleNamespace(box=box)

        def predict(self, sources, **kwargs):
            calls["predict"].append(kwargs)
            results = []
            for source in [sources] if isinstance(sources, str) else sources:
                path = Path(source)
                with Image.open(path) as image:
                    width, height = image.size
                label = path.parent.parent / "labels" / f"{path.stem}.txt"
                boxes = [FakeBox(b) for b in ed.read_boxes(label, width, height)] if label.is_file() else []
                results.append(types.SimpleNamespace(orig_shape=(height, width), boxes=boxes))
            return results

    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=YOLO))
    return calls


def run(dataset: Path, model: Path, out: Path, *extra: str) -> dict:
    assert ed.main(["--dataset", str(dataset), "--model", f"m={model}", "--device", "cpu", "--out", str(out),
                    *extra]) == 0
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def test_subset_list_falls_back_to_v2_prefix(v3_dataset: Path):
    assert ed.subset_list(v3_dataset, "test_new").name == "v2_test_new.txt"
    assert ed.subset_list(v3_dataset, "test_baldosa").name == "test_baldosa.txt"
    assert [p.name for p in ed.subset_images(v3_dataset, "test_new")] == ["a.jpg", "b.jpg"]


def test_subset_list_missing_stops_with_clear_message(v3_dataset: Path):
    with pytest.raises(SystemExit, match="v2_no_existe.txt"):
        ed.subset_list(v3_dataset, "no_existe")


def test_v3_report_with_chosen_subsets_and_nms(v3_dataset: Path, model: Path, tmp_path: Path, fake_yolo):
    report = run(v3_dataset, model, tmp_path / "eval", "--subsets", "test_new", "test_baldosa", "--nms-iou", "0.5")

    assert report["nms_iou"] == 0.5
    assert fake_yolo["val"] and all(call["iou"] == 0.5 for call in fake_yolo["val"])
    assert fake_yolo["predict"] and all(call["iou"] == 0.5 for call in fake_yolo["predict"])

    entry = report["models"]["m"]
    assert entry["sha256"] == hashlib.sha256(b"pesos falsos").hexdigest()
    assert set(entry["subsets"]) == {"test_new", "test_baldosa"}
    assert entry["subsets"]["test_new"]["at_conf_0.5"]["recall"] == 1.0

    info = report["subsets"]["test_new"]
    assert info["list"] == "v2_test_new.txt"
    assert (info["images"], info["objects"]) == (2, 2)
    assert len(info["fingerprint_sha256"]) == 64
    assert info["separation"]["checked"] and info["separation"]["ok"]
    assert info["separation"]["train_list"] == "train.txt"
    assert set(info["separation"]["shared_counts"].values()) == {0}

    # Negativos solo de los subconjuntos pedidos, en una carpeta propia: no toca negatives_eval.
    negatives = Path(report["negatives_dir"])
    assert negatives.name == "negatives_eval__test_baldosa_test_new"
    assert not (v3_dataset / "negatives_eval").exists()
    with open(negatives / "index.csv", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["subset"] for row in rows} == {"test_new", "test_baldosa"}
    assert len(rows) == 3


def test_fingerprint_changes_when_a_label_changes(v3_dataset: Path):
    images = ed.subset_images(v3_dataset, "test_new")
    before = ed.fingerprint(images, v3_dataset)["fingerprint_sha256"]
    (v3_dataset / "labels" / "a.txt").write_text("0 0.8 0.8 0.1 0.1\n", encoding="utf-8")
    assert ed.fingerprint(images, v3_dataset)["fingerprint_sha256"] != before


def test_separation_detects_image_shared_with_train(v3_dataset: Path, model: Path, tmp_path: Path, fake_yolo,
                                                    capsys):
    # La misma foto con otro nombre (contenido igual) y una repetición de train de otra (misma fuente).
    shutil.copy(v3_dataset / "images" / "a.jpg", v3_dataset / "images" / "copia.jpg")
    make_image(v3_dataset, "b_r1.jpg", (10, 10, 10))
    write_list(v3_dataset, "train.txt", ["c.jpg", "copia.jpg", "b_r1.jpg"])

    report = run(v3_dataset, model, tmp_path / "eval", "--subsets", "test_new")

    separation = report["subsets"]["test_new"]["separation"]
    assert separation["ok"] is False
    assert separation["shared_counts"] == {"train_name": 0, "train_source": 1, "train_sha256": 1}
    assert separation["examples"]["source"] == ["b"]
    assert "AVISO: test_new comparte imágenes con train" in capsys.readouterr().err
    assert "m" in report["models"]  # avisa, pero evalúa igual


def test_without_train_list_separation_is_not_checked(v3_dataset: Path, model: Path, tmp_path: Path, fake_yolo):
    (v3_dataset / "train.txt").unlink()
    report = run(v3_dataset, model, tmp_path / "eval", "--subsets", "test_baldosa")
    assert report["subsets"]["test_baldosa"]["separation"] == {
        "checked": False, "ok": None, "reason": "el dataset no tiene train.txt"}


def test_require_separation_stops_before_evaluating(v3_dataset: Path, model: Path, tmp_path: Path, fake_yolo):
    shutil.copy(v3_dataset / "images" / "a.jpg", v3_dataset / "images" / "copia.jpg")
    write_list(v3_dataset, "train.txt", ["c.jpg", "copia.jpg"])
    out = tmp_path / "eval"

    with pytest.raises(SystemExit, match="test_new comparte imágenes con train") as stop:
        ed.main(["--dataset", str(v3_dataset), "--model", f"m={model}", "--device", "cpu", "--out", str(out),
                 "--subsets", "test_new", "test_baldosa", "--require-separation"])

    assert "test_baldosa" not in str(stop.value)  # solo nombra el subconjunto con el problema
    assert fake_yolo == {"val": [], "predict": []}  # no cargó ni evaluó ningún modelo
    assert not out.exists()  # no dejó un informe ni carpetas a medias
    assert not list(v3_dataset.glob("negatives_eval*"))


def test_require_separation_stops_when_it_cannot_check(v3_dataset: Path, model: Path, tmp_path: Path, fake_yolo):
    (v3_dataset / "train.txt").unlink()
    with pytest.raises(SystemExit, match="no se pudo comprobar la separación"):
        ed.main(["--dataset", str(v3_dataset), "--model", f"m={model}", "--device", "cpu",
                 "--out", str(tmp_path / "eval"), "--subsets", "test_baldosa", "--require-separation"])
    assert fake_yolo == {"val": [], "predict": []}


def test_require_separation_passes_when_separated(v3_dataset: Path, model: Path, tmp_path: Path, fake_yolo):
    report = run(v3_dataset, model, tmp_path / "eval", "--subsets", "test_new", "test_baldosa",
                 "--require-separation")
    assert report["require_separation"] is True
    assert all(info["separation"]["ok"] for info in report["subsets"].values())
    assert set(report["models"]["m"]["subsets"]) == {"test_new", "test_baldosa"}


def test_default_usage_is_unchanged(v2_dataset: Path, model: Path, tmp_path: Path, fake_yolo):
    """Sin las opciones nuevas: los cuatro subconjuntos de v2, NMS 0.7 y negatives_eval como antes."""
    report = run(v2_dataset, model, tmp_path / "eval")

    assert report["nms_iou"] == 0.7
    assert all(call["iou"] == 0.7 for call in fake_yolo["val"] + fake_yolo["predict"])
    assert list(report["models"]["m"]["subsets"]) == ed.SUBSETS
    assert Path(report["negatives_dir"]) == v2_dataset / "negatives_eval"
    with open(v2_dataset / "negatives_eval" / "index.csv", encoding="utf-8") as handle:
        assert {row["subset"] for row in csv.DictReader(handle)} == set(ed.SUBSETS)
