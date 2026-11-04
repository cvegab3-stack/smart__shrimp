"""Verifica el resumen compartido y la independencia de categorías."""

from shrimp_contracts import SessionSummary, ShrimpResult, classes_for


def test_summary_preserves_separate_class_groups(sample_analysis_summary):
    row = ShrimpResult("track-1", "sin_cabeza", "pelado", "no_concluyente", None, None, None, None)
    summary = SessionSummary("a1", 1, (row,), 1).to_dict()
    assert summary["shrimp"][0]["integrity"] == "sin_cabeza"
    assert summary["shrimp"][0]["presentation"] == "pelado"
    assert summary["shrimp"][0]["visual_condition"] == "no_concluyente"
    assert "pelado" not in classes_for("condicion_visual")
    assert sample_analysis_summary["model_mode"] == "inference"


def test_empty_inference_summary_is_explicit(sample_analysis_summary):
    assert sample_analysis_summary["shrimp_count"] == 0
    assert sample_analysis_summary["totals"]["rejected"] == 0
