"""Exporta un informe consolidado a CSV UTF-8."""

import csv
import io

from apps.results.models import ShrimpRecord
from apps.results.services.report_service import VISUAL_DISCLAIMER


def export_report_csv(report) -> bytes:
    """Produce tabla métrica/valor, con etiquetas y advertencias obligatorias."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("Métrica", "Valor"))
    values = report.summary
    writer.writerow(("Análisis finalizados", values["analysis_count"]))
    writer.writerow(("Camarones analizados", values["shrimp_count"]))
    writer.writerow(("Peso promedio estimado (g) — valor estimado", values["average_estimated_weight_g"] if values["average_estimated_weight_g"] is not None else "No disponible"))
    for category, count in sorted(values["size_distribution"].items()):
        writer.writerow((f"Tamaño: {category}", count))
    for category, count in sorted(values["visual_condition_distribution"].items()):
        writer.writerow((f"Condición visual: {category}", count))
    writer.writerow(("Condición visual", values["visual_disclaimer"]))
    return output.getvalue().encode("utf-8-sig")


def export_analysis_csv(analysis) -> bytes:
    """Exporta resultados individuales con las mismas etiquetas de la interfaz."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("ID de seguimiento", "Integridad", "Presentación", "Condición visual", "Longitud (cm)", "Tamaño", "Peso estimado (g)", "Alcance"))
    rows = ShrimpRecord.objects.of_current_attempt(analysis)
    for row in rows:
        writer.writerow((row.track_id, row.integrity or "No disponible", row.presentation or "No disponible",
                         row.visual_condition, row.length_cm if row.length_cm is not None else "No disponible",
                         row.size_category or "No disponible",
                         f"{row.estimated_weight_g} · valor estimado" if row.estimated_weight_g is not None else "No disponible · valor estimado",
                         VISUAL_DISCLAIMER))
    return output.getvalue().encode("utf-8-sig")
