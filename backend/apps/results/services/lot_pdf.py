"""Informe PDF de un lote (lo descarga el supervisor desde el detalle del lote).

Diseño: encabezado de marca, tarjetas con los indicadores principales, clasificación por talla (pequeño, mediano,
grande: cantidad, %, longitudes), datos del lote y del análisis, notas, firmas y «Página X de Y». Sin fotos ni
listado camarón por camarón: ocupa lo mismo con 2 camarones que con 300.
Usa solo las fuentes estándar de PDF (Helvetica), que se ven igual en cualquier equipo e impresora.
"""

import io

from django.utils import timezone
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from apps.analysis.models import AnalysisSession, _num
from apps.results.models import ShrimpRecord
from apps.results.services.presentation_service import SIZE_NAMES, build_summary
from apps.results.services.report_service import VISUAL_DISCLAIMER

# Paleta de la aplicación (static/css/main.css y los colores de tamaño de la cámara).
NAVY = colors.HexColor("#0B2A4A")
NAVY_2 = colors.HexColor("#123B60")
TEAL = colors.HexColor("#0B7F8C")
CYAN = colors.HexColor("#12B5C4")
INK = colors.HexColor("#0F2A43")
MUTED = colors.HexColor("#5B7085")
LINE = colors.HexColor("#D6E6EC")
SKY = colors.HexColor("#EEF7FA")
TRACK = colors.HexColor("#E3EEF2")
GREEN_BG, GREEN = colors.HexColor("#DCF2E5"), colors.HexColor("#0A6532")
AMBER_BG, AMBER = colors.HexColor("#FFF4DB"), colors.HexColor("#8A5A00")
SIZE_COLORS = {"pequeno": colors.HexColor("#12B5C4"), "mediano": colors.HexColor("#D69A17"),
               "grande": colors.HexColor("#7C4DFF"), "fuera": colors.HexColor("#8B9AA8"),
               "sin_medida": colors.HexColor("#B4C0CA"), "otro": colors.HexColor("#8B9AA8")}

PAGE_W, PAGE_H = letter
MARGIN = 42
CONTENT_W = PAGE_W - 2 * MARGIN
FIRST_HEADER_H = 100
LATER_HEADER_H = 46
FOOTER_H = 38


def _style(name, **kw) -> ParagraphStyle:
    base = {"fontName": "Helvetica", "fontSize": 9.5, "leading": 13, "textColor": INK}
    return ParagraphStyle(name, **{**base, **kw})


S = {
    "section": _style("section", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=NAVY, spaceBefore=4),
    "section_note": _style("section_note", fontSize=8.5, leading=11, textColor=MUTED),
    "kpi_label": _style("kpi_label", fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=MUTED),
    "kpi_value": _style("kpi_value", fontName="Helvetica-Bold", fontSize=21, leading=24, textColor=NAVY),
    "kpi_sub": _style("kpi_sub", fontSize=7.8, leading=10, textColor=MUTED),
    "label": _style("label", fontSize=8.8, leading=12, textColor=MUTED),
    "value": _style("value", fontName="Helvetica-Bold", fontSize=9.2, leading=12, textColor=INK),
    "meta": _style("meta", fontSize=9, leading=12, textColor=MUTED),
    "chip": _style("chip", fontName="Helvetica-Bold", fontSize=8, leading=10, alignment=TA_CENTER),
    "cell": _style("cell", fontSize=8.6, leading=11),
    "cell_head": _style("cell_head", fontName="Helvetica-Bold", fontSize=7.6, leading=10, textColor=colors.white),
    "note": _style("note", fontSize=7.8, leading=10.5, textColor=MUTED),
    "warn": _style("warn", fontSize=8.8, leading=12, textColor=AMBER),
    "sign": _style("sign", fontSize=8.2, leading=11, textColor=MUTED, alignment=TA_CENTER),
    "stat_value": _style("stat_value", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=NAVY,
                         alignment=TA_RIGHT),
}


def _esc(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _p(text, style) -> Paragraph:
    return Paragraph(_esc(text), S[style] if isinstance(style, str) else style)


# ---------------------------------------------------------------- Página: encabezado, pie y «Página X de Y»

class _NumberedCanvas(pdf_canvas.Canvas):
    """Guarda las páginas para escribir «Página X de Y» cuando ya se sabe el total."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(MUTED)
            self.drawRightString(PAGE_W - MARGIN, 22, f"Página {self._pageNumber} de {total}")
            super().showPage()
        super().save()


def _brand_mark(c, x, y, size):
    """Marca de la aplicación: cuadro turquesa con una media luna blanca (como el logo de la web)."""
    c.setFillColor(TEAL)
    c.roundRect(x, y, size, size, size * 0.26, stroke=0, fill=1)
    c.setFillColor(colors.white)
    r = size * 0.27
    c.wedge(x + size * 0.52 - r, y + size / 2 - r, x + size * 0.52 + r, y + size / 2 + r, 90, 180, stroke=0, fill=1)


def _draw_footer(c, info):
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(MARGIN, 34, PAGE_W - MARGIN, 34)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawString(MARGIN, 22, f"SMART SHRIMP · Informe del lote {info['code']} · Documento de uso interno")


def _first_page(c, doc):
    info = doc.report_info
    c.saveState()
    top = PAGE_H - FIRST_HEADER_H
    c.setFillColor(NAVY)
    c.rect(0, top, PAGE_W, FIRST_HEADER_H, stroke=0, fill=1)
    c.setFillColor(NAVY_2)  # franja diagonal decorativa
    path = c.beginPath()
    path.moveTo(PAGE_W * 0.62, PAGE_H)
    path.lineTo(PAGE_W, PAGE_H)
    path.lineTo(PAGE_W, top)
    path.lineTo(PAGE_W * 0.70, top)
    path.close()
    c.drawPath(path, stroke=0, fill=1)
    c.setFillColor(CYAN)
    c.rect(0, top - 4, PAGE_W, 4, stroke=0, fill=1)

    _brand_mark(c, MARGIN, top + 46, 32)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(MARGIN + 42, top + 63, "SMART")
    c.setFillColor(CYAN)
    c.drawString(MARGIN + 42 + c.stringWidth("SMART ", "Helvetica-Bold", 15), top + 63, "SHRIMP")
    c.setFillColor(colors.HexColor("#A9C6D6"))
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN + 42, top + 50, "Análisis visual inteligente")

    c.setFillColor(CYAN)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(MARGIN, top + 27, info["kind"].upper())
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(MARGIN, top + 9, info["code"])

    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#A9C6D6"))
    c.drawRightString(PAGE_W - MARGIN, top + 66, "FECHA DE EMISIÓN")
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(PAGE_W - MARGIN, top + 53, info["issued"])
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#A9C6D6"))
    c.drawRightString(PAGE_W - MARGIN, top + 27, "N.º DE ANÁLISIS")
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawRightString(PAGE_W - MARGIN, top + 14, info["short_id"])
    _draw_footer(c, info)
    c.restoreState()


def _later_pages(c, doc):
    info = doc.report_info
    c.saveState()
    _brand_mark(c, MARGIN, PAGE_H - 38, 16)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(NAVY)
    c.drawString(MARGIN + 22, PAGE_H - 33, "SMART SHRIMP")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 33, f"{info['kind']} · {info['code']}")
    c.setStrokeColor(CYAN)
    c.setLineWidth(1.2)
    c.line(MARGIN, PAGE_H - 44, PAGE_W - MARGIN, PAGE_H - 44)
    _draw_footer(c, info)
    c.restoreState()


# ---------------------------------------------------------------- Bloques del contenido

def _section(title, note=None):
    parts = [_p(title, "section")]
    if note:
        parts.append(_p(note, "section_note"))
    return KeepTogether(parts + [Spacer(1, 7)])


def _status_bar(analysis, operator, counted_at):
    finished = analysis.status == AnalysisSession.Status.FINISHED
    chip = Table([[_p(analysis.get_status_display().upper(), _style("c", parent=S["chip"],
                                                                     textColor=GREEN if finished else AMBER))]],
                 colWidths=[78], rowHeights=[18])
    chip.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREEN_BG if finished else AMBER_BG),
        ("ROUNDEDCORNERS", [9, 9, 9, 9]), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    meta = Paragraph(f"Operador <b>{_esc(operator)}</b>  ·  Fecha del análisis <b>{_esc(counted_at)}</b>  ·  "
                     f"Calibración <b>v{analysis.calibration.version}</b>", S["meta"])
    bar = Table([[chip, meta]], colWidths=[90, CONTENT_W - 90])
    bar.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return bar


def _kpi_cards(cards):
    """Fila de tarjetas: la primera destacada en turquesa."""
    gap = 10
    width = (CONTENT_W - gap * (len(cards) - 1)) / len(cards)
    light = colors.HexColor("#CDEFF2")
    row, widths = [], []
    for index, (label, value, sub) in enumerate(cards):
        highlight = index == 0
        content = [
            _p(label.upper(), _style(f"kl{index}", parent=S["kpi_label"], textColor=light) if highlight else "kpi_label"),
            Spacer(1, 3),
            _p(value, _style(f"kv{index}", parent=S["kpi_value"], textColor=colors.white) if highlight else "kpi_value"),
            _p(sub, _style(f"ks{index}", parent=S["kpi_sub"], textColor=light) if highlight else "kpi_sub"),
        ]
        card = Table([[content]], colWidths=[width], rowHeights=[60])  # cada tarjeta, su propio recuadro redondeado
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TEAL if highlight else SKY), ("ROUNDEDCORNERS", [8, 8, 8, 8]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        row.append(card)
        widths.append(width)
        if index < len(cards) - 1:
            row.append("")
            widths.append(gap)
    table = Table([row], colWidths=widths)
    table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return table


def _key_values(rows, width):
    """Lista «dato · valor» con líneas finas (sin cuadrícula)."""
    if not rows:
        rows = [("Sin datos", "—")]
    table = Table([[_p(label, "label"), _p(value, "value")] for label, value in rows],
                  colWidths=[width * 0.46, width * 0.54])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.6, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _two_columns(left_title, left, right_title, right):
    gap = 24
    col = (CONTENT_W - gap) / 2
    table = Table([[_p(left_title, "section"), "", _p(right_title, "section")],
                   [_key_values(left, col), "", _key_values(right, col)]],
                  colWidths=[col, gap, col])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, 0), 6)]))
    return table


def _share_bar(share, color, width):
    """Barrita de proporción para una celda de la tabla."""
    drawing = Drawing(width, 10)
    drawing.add(Rect(0, 1, width, 8, fillColor=TRACK, strokeColor=None, rx=4, ry=4))
    if share > 0:
        drawing.add(Rect(0, 1, max(width * share, 8), 8, fillColor=color, strokeColor=None, rx=4, ry=4))
    return drawing


def _size_classification(analysis, summary):
    """Clasificación por talla: una fila por tamaño (rango de la calibración, cantidad, %, longitudes) y el total.

    Ocupa lo mismo con 2 camarones que con 300: no se listan los camarones uno por uno.
    """
    records = list(ShrimpRecord.objects.of_current_attempt(analysis))
    total = len(records) or 1
    band_text = {band["key"]: band["text"] for band in analysis.calibration.size_bands}

    def key_of(record):
        if record.size_category in SIZE_NAMES:
            return record.size_category
        return "fuera" if record.length_cm is not None else "sin_medida"

    def lengths_text(values):
        if not values:
            return "—", "—"
        avg = f"{_num(sum(values) / len(values))} cm"
        spread = f"{_num(min(values))} – {_num(max(values))} cm" if len(values) > 1 else f"{_num(values[0])} cm"
        return avg, spread

    head = ["", "Talla", "Rango", "Camarones", "% del lote", "Proporción", "Promedio", "Mín. – máx."]
    widths = [5, 70, 88, 60, 52, 80, 70, CONTENT_W - 5 - 70 - 88 - 60 - 52 - 80 - 70]
    data = [[_p(text, "cell_head") for text in head]]
    style = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
             ("LEFTPADDING", (0, 0), (-1, -1), 7), ("LEFTPADDING", (0, 0), (0, -1), 0),
             ("RIGHTPADDING", (0, 0), (0, -1), 0), ("LINEBELOW", (0, 1), (-1, -2), 0.5, LINE)]
    for item in summary["counts"]:
        key = item["key"]
        values = [r.length_cm for r in records if key_of(r) == key and r.length_cm is not None]
        share = item["count"] / total
        avg, spread = lengths_text(values)
        color = SIZE_COLORS.get(key, SIZE_COLORS["otro"])
        data.append(["", _p(item["name"], "value"), _p(band_text.get(key, "fuera de los rangos"), "cell"),
                     _p(str(item["count"]), _style(f"n{key}", parent=S["value"], fontSize=11)),
                     _p(f"{round(share * 100)} %", "cell"), _share_bar(share, color, widths[5] - 14),
                     _p(avg, "cell"), _p(spread, "cell")])
        style.append(("BACKGROUND", (0, len(data) - 1), (0, len(data) - 1), color))
    all_values = [r.length_cm for r in records if r.length_cm is not None]
    avg, spread = lengths_text(all_values)
    data.append(["", _p("Total", "value"), "", _p(str(len(records)), _style("ntot", parent=S["value"], fontSize=11)),
                 _p("100 %", "value"), "", _p(avg, "value"), _p(spread, "value")])
    style += [("BACKGROUND", (0, -1), (-1, -1), SKY), ("LINEABOVE", (0, -1), (-1, -1), 1, NAVY)]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(style))
    return table


def _signatures(operator):
    col = (CONTENT_W - 60) / 2
    line = Table([[""]], colWidths=[col], rowHeights=[22])
    line.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.8, INK)]))
    table = Table([[line, "", line],
                   [_p(f"Operador responsable: {operator}", "sign"), "", _p("Revisado por (supervisor)", "sign")]],
                  colWidths=[col, 60, col])
    table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return table


def _notice(text):
    box = Table([[_p(text, "warn")]], colWidths=[CONTENT_W])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AMBER_BG), ("ROUNDEDCORNERS", [8, 8, 8, 8]),
                             ("LEFTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 6),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return box


# ---------------------------------------------------------------- Informe

# Peso promedio por camarón fuera de lo creíble: casi siempre el peso del lote o el conteo están mal.
PLAUSIBLE_AVG_G = (1, 150)


def export_lot_pdf(analysis) -> bytes:
    summary = build_summary(analysis)
    is_lot = analysis.source == AnalysisSession.Source.VIDEO
    operator = analysis.operator.get_full_name() or analysis.operator.username
    counted_at = timezone.localtime(analysis.finished_at or analysis.created_at).strftime("%d/%m/%Y %H:%M")
    total = summary["total"]

    buffer = io.BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=letter, title=f"Informe del lote {analysis.batch_code}",
                          author="SMART SHRIMP", subject="Informe de conteo de lote",
                          leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=FOOTER_H + 12)
    doc.report_info = {
        "code": analysis.batch_code, "kind": "Informe de conteo de lote" if is_lot else "Informe de medición",
        "issued": timezone.localtime().strftime("%d/%m/%Y %H:%M"), "short_id": str(analysis.pk)[:8].upper(),
    }
    body_h = lambda header: PAGE_H - header - 18 - (FOOTER_H + 12)  # noqa: E731
    doc.addPageTemplates([
        PageTemplate("first", [Frame(MARGIN, FOOTER_H + 12, CONTENT_W, body_h(FIRST_HEADER_H), id="f1",
                                     leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)],
                     onPage=_first_page),
        PageTemplate("later", [Frame(MARGIN, FOOTER_H + 12, CONTENT_W, body_h(LATER_HEADER_H), id="f2",
                                     leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)],
                     onPage=_later_pages),
    ])

    weight = analysis.lot_weight_kg
    avg_g = weight * 1000 / total if weight and total else None
    if is_lot:
        cards = [("Camarones contados", str(total), "al cruzar la línea de conteo"),
                 ("Peso del lote", f"{_num(weight)} kg" if weight else "—", "registrado por el operador"),
                 ("Peso promedio", f"{_num(avg_g)} g" if avg_g else "—", "por camarón (calculado)"),
                 ("Camarones por kilo", _num(total / weight) if weight and total else "—", "calculado")]
    else:
        cards = [("Camarones detectados", str(total), "en la foto"),
                 ("Longitud promedio", summary["length_avg"] or "—", "según la calibración"),
                 ("Longitud mínima", summary["length_min"] or "—", ""),
                 ("Longitud máxima", summary["length_max"] or "—", "")]

    story = [NextPageTemplate("later"), _status_bar(analysis, operator, counted_at), Spacer(1, 14),
             _kpi_cards(cards), Spacer(1, 10)]
    if avg_g is not None and not PLAUSIBLE_AVG_G[0] <= avg_g <= PLAUSIBLE_AVG_G[1]:
        story += [_notice(f"Revisar: el peso promedio calculado ({_num(avg_g)} g por camarón) no es realista para "
                          f"camarón. Comprueba el peso del lote ({_num(weight)} kg) y el conteo ({total})."),
                  Spacer(1, 10)]
    if analysis.expected_count is not None and is_lot:
        difference = total - analysis.expected_count
        text = ("El conteo coincide con la cantidad esperada." if not difference else
                f"Diferencia con la cantidad esperada ({analysis.expected_count}): {difference:+d} camarones.")
        story += [_notice(text) if difference else _p(text, "meta"), Spacer(1, 8)]

    # Clasificación por talla (reemplaza el listado camarón por camarón)
    story += [_section("Clasificación por talla",
                       f"Rangos de longitud de la calibración v{analysis.calibration.version}. "
                       "Porcentaje sobre el total de camarones" + (" contados." if is_lot else " detectados.")),
              _size_classification(analysis, summary)]
    if summary["rejected"]:
        story += [Spacer(1, 5), _p(f"Detecciones descartadas (manos u objetos muy cerca de la cámara): "
                                   f"{summary['rejected']}.", "note")]
    story.append(Spacer(1, 12))

    # Datos del lote y del análisis
    lot_rows = [(row["label"], row["value"]) for row in analysis.lot_rows]
    analysis_rows = [
        ("Tipo de análisis", "Conteo de lote con cámara" if is_lot else "Foto de un camarón"),
        ("Operador", operator), ("Fecha y hora", counted_at), ("Intento", str(analysis.current_attempt)),
        ("Calibración", f"v{analysis.calibration.version} · {_num(analysis.calibration.reference_length_cm)} cm = "
                        f"{analysis.calibration.reference_pixels} px"),
    ]
    if is_lot:
        story += [_two_columns("Datos del lote", lot_rows, "Datos del análisis", analysis_rows), Spacer(1, 13)]
    else:
        story += [_section("Datos del análisis"), _key_values(analysis_rows, CONTENT_W), Spacer(1, 13)]

    notes = ["Longitudes calculadas con la calibración indicada. Peso promedio por camarón = peso del lote ÷ camarones "
             "contados. Condición visual y peso individual aún no disponibles (modelos en entrenamiento).",
             VISUAL_DISCLAIMER]
    story += [KeepTogether([_p("NOTAS", _style("nt", parent=S["kpi_label"], textColor=NAVY)), Spacer(1, 4)]
                           + [_p(f"•  {text}", "note") for text in notes]
                           + [Spacer(1, 10), _signatures(operator)])]
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()
