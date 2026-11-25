"""Exporta un informe consolidado a PDF."""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.results.services.lot_pdf import export_lot_pdf
from apps.results.services.report_service import flow_rows

HEADER_BLUE = colors.HexColor("#0B2A4A")
GRID_COLOR = colors.HexColor("#B8C8D2")
ROW_TINT = colors.HexColor("#EAF6FB")


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
    data.extend([[label, str(count)] for label, count in flow_rows(report.summary)])
    table = Table(data, repeatRows=1, colWidths=(250, 250))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_TINT]),
    ]))
    styles = getSampleStyleSheet()
    elements = [Paragraph("Reporte de producción SMART SHRIMP", styles["Title"]), Spacer(1, 14), table, Spacer(1, 12),
                Paragraph(report.summary["visual_disclaimer"], styles["BodyText"])]
    document.build(elements)
    return buffer.getvalue()


def export_analysis_pdf(analysis) -> bytes:
    """Informe de un lote (diseño en lot_pdf.py)."""
    return export_lot_pdf(analysis)
