"""Exporta un informe consolidado a CSV UTF-8."""

import csv
import io

from django.utils import timezone

from apps.analysis.models import _num
from apps.results.models import ShrimpRecord
from apps.results.services.presentation_service import _track_order, build_summary
from apps.results.services.report_service import VISUAL_DISCLAIMER, flow_rows


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
    for label, count in flow_rows(values):
        writer.writerow((label, count))
    writer.writerow(("Condición visual", values["visual_disclaimer"]))
    return output.getvalue().encode("utf-8-sig")


def export_analysis_csv(analysis) -> bytes:
    """Informe de un lote para Excel: secciones con títulos, nombres legibles y detalle por camarón.

    Separador «;» y coma decimal: así Excel en español lo abre directamente en columnas.
    """
    summary = build_summary(analysis)
    operator = analysis.operator.get_full_name() or analysis.operator.username
    is_lot = analysis.source == "video"
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow((f"Informe del lote {analysis.batch_code}",))
    writer.writerow(("Emitido", timezone.localtime().strftime("%d/%m/%Y %H:%M")))
    writer.writerow(())
    writer.writerow(("DATOS DEL ANÁLISIS",))
    writer.writerow(("Tipo de análisis", "Conteo de lote con cámara" if is_lot else "Foto de un camarón"))
    writer.writerow(("Estado", analysis.get_status_display()))
    writer.writerow(("Operador", operator))
    writer.writerow(("Fecha y hora", timezone.localtime(analysis.finished_at or analysis.created_at).strftime("%d/%m/%Y %H:%M")))
    writer.writerow(("Intento", analysis.current_attempt))
    writer.writerow(("Calibración", f"v{analysis.calibration.version} ({_num(analysis.calibration.reference_length_cm)} cm = "
                                    f"{analysis.calibration.reference_pixels} px)"))
    if summary["lot"]:
        writer.writerow(())
        writer.writerow(("DATOS DEL LOTE",))
        for row in summary["lot"]:
            writer.writerow((row["label"], row["value"]))
    writer.writerow(())
    writer.writerow(("RESUMEN",))
    writer.writerow(("Camarones contados" if is_lot else "Camarones detectados", summary["total"]))
    bands = {band["key"]: band["text"] for band in analysis.calibration.size_bands}
    for item in summary["counts"]:  # clasificación por talla: rango, cantidad y % del lote
        share = round(item["count"] * 100 / summary["total"]) if summary["total"] else 0
        name = f"{item['name']} ({bands[item['key']]})" if item["key"] in bands else item["name"]
        writer.writerow((name, item["count"], f"{share} %"))
    for label, key in (("Longitud promedio", "length_avg"), ("Longitud mínima", "length_min"), ("Longitud máxima", "length_max")):
        writer.writerow((label, summary[key] or "—"))
    if summary["rejected"]:
        writer.writerow(("Detecciones descartadas", summary["rejected"]))
    writer.writerow(())
    writer.writerow(("DETALLE POR CAMARÓN",))
    writer.writerow(("N.º", "Longitud (cm)", "Tamaño", "Observación"))
    # Mismo orden que el resumen (track-2 antes que track-10); la longitud va como número para poder sumar en Excel.
    records = sorted(ShrimpRecord.objects.of_current_attempt(analysis), key=lambda r: _track_order(r.track_id))
    for record, row in zip(records, summary["rows"]):
        length = record.length_cm
        writer.writerow((row["number"], _num(length) if length is not None else "Sin medida", row["size"],
                         "Primer plano: medida poco fiable" if row["close_up"] else ""))
    writer.writerow(())
    writer.writerow(("NOTAS",))
    writer.writerow(("Longitudes calculadas con la calibración indicada; el peso promedio por camarón es el peso del lote "
                     "dividido entre los camarones contados.",))
    writer.writerow((VISUAL_DISCLAIMER,))
    return output.getvalue().encode("utf-8-sig")

