"""Carga el catálogo de clases compartido por backend y servicio de visión."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CATALOG_PATH = Path(__file__).with_name("class_catalog.yaml")
GROUPS = ("deteccion", "integridad", "presentacion", "condicion_visual")


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """Lee y valida la estructura mínima del catálogo YAML."""
    with CATALOG_PATH.open(encoding="utf-8") as catalog_file:
        catalog = yaml.safe_load(catalog_file)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("version"), int):
        raise ValueError("El catálogo debe declarar una versión entera.")
    for group in GROUPS:
        if not isinstance(catalog.get(group), dict) or not catalog[group]:
            raise ValueError(f"El catálogo debe definir el grupo {group}.")
    return catalog


def classes_for(group: str) -> tuple[str, ...]:
    """Devuelve los identificadores de clase de un grupo conocido."""
    if group not in GROUPS:
        raise ValueError(f"Grupo de clases desconocido: {group}")
    return tuple(load_catalog()[group])
