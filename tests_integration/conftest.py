"""Fixtures para pruebas que atraviesan varios módulos."""

import pytest


@pytest.fixture
def sample_analysis_summary():
    """Resumen de inferencia válido para el contrato del servicio."""
    return {
        "analysis_id": "integration-analysis", "attempt": 1, "shrimp": [],
        "shrimp_count": 0, "rejected_count": 0, "model_mode": "inference",
        "model_status": "configured",
        "totals": {"integrity": {}, "presentation": {}, "visual_condition": {}, "size_category": {}, "rejected": 0},
    }
