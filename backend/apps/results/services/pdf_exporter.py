"""Exporta un informe consolidado a PDF."""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.results.models import ShrimpRecord
from apps.results.services.report_service import VISUAL_DISCLAIMER


def export_report_pdf(report) -> bytes:
    """Renderiza métricas, distribuciones y leyendas obligatorias."""
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=letter, title="Reporte SMART SHRIMP")
    data = [["Métrica", "Valor"],
            ["Análisis finalizados", str(report.summary["analysis_count"])],
            ["Camarones analizados", str(report.summary["shrimp_count"])],
            ["Peso promedio estimado (g) — valor estimado", str(report.summary["average_estimated_weight_g"] if report.summary["average_estimated_weight_g"] is not None else "No disponible")]]
    data.extend([[f"Tamaño: {key}", str(value)] for key, value in sorted(report.summary["size_distribution"].items())])
    data.extend([[f"Condición visual: {key}", str(value)] for key, value in sorted(report.summary["visual_condition_distribution"].items())])
    table = Table(data, repeatRows=1, colWidths=(250, 250))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B2A4A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C8D2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EAF6FB")]),
    ]))
    styles = getSampleStyleSheet()
    elements = [Paragraph("Reporte de producción SMART SHRIMP", styles["Title"]), Spacer(1, 14), table, Spacer(1, 12),
                Paragraph(report.summary["visual_disclaimer"], styles["BodyText"])]
    document.build(elements)
    return buffer.getvalue()


def export_analysis_pdf(analysis) -> bytes:
    """Exporta resultados individuales con leyendas de estimación y alcance."""
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=letter, title=f"Resultados {analysis.batch_code}")
    rows = [["ID", "Integridad", "Presentación", "Condición visual", "Longitud", "Tamaño", "Peso estimado"]]
    records = ShrimpRecord.objects.of_current_attempt(analysis)
    for record in records:
        rows.append([
            record.track_id, record.integrity or "No disponible", record.presentation or "No disponible",
            record.visual_condition,
            f"{record.length_cm:.2f} cm" if record.length_cm is not None else "No disponible",
            record.size_category or "No disponible",
            f"{record.estimated_weight_g:.2f} g · valor estimado" if record.estimated_weight_g is not None else "No disponible · valor estimado",
        ])
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B2A4A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C8D2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    styles = getSampleStyleSheet()
    document.build([
        Paragraph(f"Resultados del lote {analysis.batch_code}", styles["Title"]),
        Spacer(1, 12), table, Spacer(1, 12), Paragraph(VISUAL_DISCLAIMER, styles["BodyText"]),
    ])
    return buffer.getvalue()
