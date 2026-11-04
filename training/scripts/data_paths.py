"""Ubicación del dataset de entrenamiento, separado del código de la aplicación.

Orden de búsqueda de la carpeta de datos:
    1. --data-dir en la línea de comandos;
    2. variable de entorno SMART_SHRIMP_DATA_DIR;
    3. la carpeta dataset/ junto al proyecto (..\\dataset), fuera del código;
    4. datasets/ dentro del proyecto (ubicación anterior).
La aplicación (vision_service) nunca usa este módulo: solo lo necesitan los scripts de training/.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR_ENV = "SMART_SHRIMP_DATA_DIR"
DEFAULT_DATA_DIR = REPO_ROOT.parent / "dataset"
LEGACY_DATA_DIR = REPO_ROOT / "datasets"


def configured_data_dir(explicit: str | Path | None = None) -> Path | None:
    """Carpeta indicada por el usuario (--data-dir o SMART_SHRIMP_DATA_DIR), sin comprobar que exista."""
    value = explicit or os.getenv(DATA_DIR_ENV)
    return Path(value).expanduser() if value else None


def candidate_data_dirs(explicit: str | Path | None = None) -> list[Path]:
    configured = configured_data_dir(explicit)
    return [configured] if configured else [DEFAULT_DATA_DIR, LEGACY_DATA_DIR]


def output_data_dir(explicit: str | Path | None = None) -> Path:
    """Carpeta donde se escribe un dataset nuevo: la configurada o ..\\dataset junto al proyecto."""
    return configured_data_dir(explicit) or DEFAULT_DATA_DIR


def find_in_data_dir(relative: str | Path, explicit: str | Path | None = None) -> Path:
    """Devuelve la primera carpeta de datos que contiene `relative`, o termina con un error claro."""
    relative = Path(relative)
    if relative.is_absolute():
        candidates = [relative]
    else:
        candidates = [base / relative for base in candidate_data_dirs(explicit)]
    for path in candidates:
        if path.exists():
            return path.resolve()
    tried = "\n".join(f"  - {path}" for path in candidates)
    raise SystemExit(
        f"No se encontró el dataset de entrenamiento '{relative}'. Rutas comprobadas:\n{tried}\n"
        f"Conecte el disco o la carpeta del dataset, o indique su ubicación con --data-dir o con la variable "
        f"{DATA_DIR_ENV}. El dataset solo es necesario para entrenar; la aplicación funciona sin él."
    )
