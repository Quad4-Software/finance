"""Draw a FinanceDocument as PDF bytes or a self-contained HTML page.

Both renderers walk the same block structure document_service produces,
so the two formats cannot disagree about content - only about medium.

The design system is the Quad4 monochrome palette: ink #0A0A0B, muted
#A1A1AA, hairlines #E9E9EC. Charts are vector primitives drawn inline
(reportlab Drawing on PDF, SVG in HTML): no image files, no webfonts, no
external assets, which keeps the HTML a single portable file and the PDF
free of binary dependencies.
"""
import io
from html import escape
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from reportlab.graphics.shapes import (
    Circle,
    Drawing,
    Line as ShapeLine,
    Polygon,
    PolyLine,
    Rect,
    String,
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.services.document_service import FinanceDocument

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 18 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

INK = colors.HexColor("#0A0A0B")
MUTED = colors.HexColor("#A1A1AA")
SOFT = colors.HexColor("#52525B")
RULE = colors.HexColor("#E9E9EC")
TRACK = colors.HexColor("#F4F4F5")

#: Monochrome series ramp for multi-line charts: darkest line first.
SERIES_COLORS = ["#0A0A0B", "#52525B", "#A1A1AA", "#D4D4D8"]

_CSS_INK = "#0A0A0B"
_CSS_MUTED = "#A1A1AA"
_CSS_SOFT = "#52525B"
_CSS_RULE = "#E9E9EC"
_CSS_TRACK = "#F4F4F5"

_TITLE = ParagraphStyle(
    "doc_title", fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=INK
)
_SUBTITLE = ParagraphStyle(
    "doc_subtitle", fontName="Helvetica", fontSize=10, leading=14, textColor=SOFT
)
_META = ParagraphStyle(
    "doc_meta", fontName="Helvetica", fontSize=8, leading=11, textColor=MUTED
)
_SECTION = ParagraphStyle(
    "section", fontName="Helvetica-Bold", fontSize=8, leading=11,
    textColor=MUTED, spaceBefore=10, keepWithNext=True,
)
_BODY = ParagraphStyle(
    "body", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK
)
_CELL = ParagraphStyle(
    "cell", fontName="Helvetica", fontSize=8.5, leading=12, textColor=INK
)
_CELL_RIGHT = ParagraphStyle(
    "cell_right", parent=_CELL, alignment=TA_RIGHT
)
_NOTE = ParagraphStyle(
    "note", fontName="Helvetica", fontSize=8, leading=11.5, textColor=SOFT, spaceBefore=2
)
_KPI_LABEL = ParagraphStyle(
    "kpi_label", fontName="Helvetica-Bold", fontSize=6.5, leading=9, textColor=MUTED
)
_KPI_VALUE = ParagraphStyle(
    "kpi_value", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=INK
)
_KPI_HINT = ParagraphStyle(
    "kpi_hint", fontName="Helvetica", fontSize=6.5, leading=9, textColor=MUTED
)
_BLOCK_LABEL = ParagraphStyle(
    "block_label", fontName="Helvetica-Bold", fontSize=7, leading=10,
    textColor=SOFT, spaceBefore=4, keepWithNext=True,
)


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    """Paragraph with user data escaped: reportlab reads its input as markup."""
    return Paragraph(xml_escape(text).replace("\n", "<br/>"), style)


def _header_label(text: str) -> Paragraph:
    return Paragraph(xml_escape(text.upper()), _SECTION)


def _short_labels(labels: list[str], count: int = 3) -> list[tuple[int, str]]:
    """Pick first/middle/last axis labels so crowded series stay readable."""
    if not labels:
        return []
    if len(labels) <= count:
        return list(enumerate(labels))
    middle = (len(labels) - 1) // 2
    return [(0, labels[0]), (middle, labels[middle]), (len(labels) - 1, labels[-1])]


def _line_layout(
    series: list[dict[str, Any]], width: float, height: float, pad_left: float
) -> tuple[list[list[tuple[float, float]]], float, float, list[str]]:
    """Scale every series to the plot box. Returns polylines, min, max, labels."""
    all_points = [p["value"] for s in series for p in s["points"]]
    labels = [p["label"] for p in series[0]["points"]] if series else []
    if not all_points:
        return [], 0.0, 0.0, labels
    low = min(all_points)
    high = max(all_points)
    if high == low:
        low -= 1.0
        high += 1.0
    pad = (high - low) * 0.08
    low -= pad
    high += pad

    plot_w = width - pad_left
    polylines: list[list[tuple[float, float]]] = []
    for s in series:
        points = s["points"]
        n = max(len(points) - 1, 1)
        polylines.append([
            (
                pad_left + (i / n) * plot_w,
                ((p["value"] - low) / (high - low)) * height,
            )
            for i, p in enumerate(points)
        ])
    return polylines, low, high, labels


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _pdf_line_chart(block: dict[str, Any]) -> Drawing:
    width = CONTENT_WIDTH
    height = 46 * mm
    pad_left = 14 * mm
    pad_bottom = 7 * mm
    drawing = Drawing(width, height + pad_bottom)

    series = block["series"]
    plot_h = height
    polylines, low, high, labels = _line_layout(series, width, height, pad_left)

    # Baseline + two hairlines, min/mid/max ticks on the left.
    for i, frac in enumerate((0.0, 0.5, 1.0)):
        y = frac * plot_h + pad_bottom
        value = low + (high - low) * frac
        drawing.add(ShapeLine(pad_left, y, width, y, strokeColor=RULE, strokeWidth=0.5))
        drawing.add(String(
            0, y - 2, f"{value:,.0f}", fontName="Helvetica", fontSize=6,
            fillColor=MUTED,
        ))

    single = len(polylines) == 1
    for index, points in enumerate(polylines):
        color = colors.HexColor(SERIES_COLORS[index % len(SERIES_COLORS)])
        flat = [v for x, y in points for v in (x, y + pad_bottom)]
        if single:
            area = [pad_left, pad_bottom] + flat + [width, pad_bottom]
            drawing.add(Polygon(
                area, fillColor=TRACK, strokeColor=None,
            ))
        drawing.add(PolyLine(
            flat, strokeColor=color, strokeWidth=1.4, strokeLineJoin=1,
        ))
        if single:
            for x, y in points:
                drawing.add(Circle(x, y + pad_bottom, 1.4, fillColor=color, strokeColor=None))

    for i, label in _short_labels(labels):
        n = max(len(labels) - 1, 1)
        x = pad_left + (i / n) * (width - pad_left)
        anchor = "start" if i == 0 else "end" if i == len(labels) - 1 else "middle"
        drawing.add(String(
            x, 1, label, fontName="Helvetica", fontSize=6, fillColor=MUTED,
            textAnchor=anchor,
        ))

    if not single:
        # Legend: one swatch per series, top right, in plot order.
        legend_x = width
        for index, s in reversed(list(enumerate(series))):
            name = s["name"]
            text_w = len(name) * 3.4 + 10
            legend_x -= text_w
            drawing.add(Rect(legend_x, height + pad_bottom - 5, 5, 5,
                             fillColor=colors.HexColor(SERIES_COLORS[index % len(SERIES_COLORS)]),
                             strokeColor=None))
            drawing.add(String(legend_x + 7, height + pad_bottom - 4, name,
                               fontName="Helvetica", fontSize=6, fillColor=SOFT))
    return drawing


def _pdf_bars(block: dict[str, Any]) -> Drawing:
    items = block["items"]
    row_h = 5.6 * mm
    width = CONTENT_WIDTH
    label_w = 52 * mm
    value_w = 30 * mm
    bar_w = width - label_w - value_w
    height = row_h * len(items)
    drawing = Drawing(width, height)
    top = max((item["value"] for item in items), default=1.0) or 1.0
    for index, item in enumerate(items):
        y = height - row_h * (index + 1) + 1.4 * mm
        drawing.add(String(
            0, y, item["label"][:38], fontName="Helvetica", fontSize=7.5, fillColor=INK,
        ))
        bar_x = label_w
        drawing.add(Rect(bar_x, y - 0.4 * mm, bar_w, 2.6 * mm, fillColor=TRACK, strokeColor=None))
        fill_w = max(bar_w * (item["value"] / top), 0.8 * mm) if item["value"] > 0 else 0
        if fill_w:
            drawing.add(Rect(bar_x, y - 0.4 * mm, fill_w, 2.6 * mm, fillColor=INK, strokeColor=None))
        drawing.add(String(
            width, y, item["display"], fontName="Helvetica", fontSize=7.5,
            fillColor=SOFT, textAnchor="end",
        ))
    return drawing


def _pdf_kpis(block: dict[str, Any]) -> Table:
    items = block["items"]
    cells = []
    for item in items:
        cell = [_para(item["label"].upper(), _KPI_LABEL), _para(item["value"], _KPI_VALUE)]
        cell.append(_para(item["hint"] or " ", _KPI_HINT))
        cells.append(cell)
    table = Table([cells], colWidths=[CONTENT_WIDTH / len(cells)] * len(cells))
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
        ("LINEBEFORE", (1, 0), (-1, 0), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _pdf_table(block: dict[str, Any]) -> Table:
    columns = block["columns"]
    header = [
        _para(col["label"].upper(), ParagraphStyle(
            "th", parent=_CELL_RIGHT if col["align"] == "right" else _CELL,
            fontName="Helvetica-Bold", fontSize=6.5, textColor=MUTED,
        ))
        for col in columns
    ]
    rows = [header]
    for row in block["rows"]:
        rows.append([
            _para(str(cell), _CELL_RIGHT if col["align"] == "right" else _CELL)
            for cell, col in zip(row, columns)
        ])
    count = len(columns)
    widths = [CONTENT_WIDTH / count] * count
    # Give the first column extra room: it carries names and descriptions.
    if count >= 3:
        widths = [CONTENT_WIDTH * 0.34] + [
            (CONTENT_WIDTH * 0.66) / (count - 1)
        ] * (count - 1)
    table = Table(rows, colWidths=widths, repeatRows=1, splitInRow=1)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _pdf_block_flowables(block: dict[str, Any]) -> list:
    kind = block["type"]
    if kind == "kpis":
        return [_pdf_kpis(block)]
    if kind == "line":
        return [_pdf_line_chart(block)]
    if kind == "bars":
        flowables = []
        if block.get("label"):
            flowables.append(_para(block["label"].upper(), _BLOCK_LABEL))
        flowables.append(_pdf_bars(block))
        return flowables
    if kind == "table":
        return [_pdf_table(block)]
    if kind == "note":
        return [_para(block["text"], _NOTE)]
    return []


def _pdf_footer(canvas, document: FinanceDocument) -> None:
    canvas.saveState()
    y = MARGIN - 4 * mm
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, y + 3.5 * mm, PAGE_WIDTH - MARGIN, y + 3.5 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        MARGIN, y, f"Generated {document.generated_on.isoformat()} - Quad4 Finance"
    )
    canvas.drawRightString(
        PAGE_WIDTH - MARGIN, y, f"Page {canvas.getPageNumber()}"
    )
    canvas.restoreState()


def render_pdf(document: FinanceDocument) -> bytes:
    """The document as PDF bytes. Pure layout: no data fetching here."""
    buffer = io.BytesIO()
    frame = Frame(
        MARGIN, MARGIN + 6 * mm, CONTENT_WIDTH, PAGE_HEIGHT - 2 * MARGIN - 6 * mm,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    template = PageTemplate(
        id="page", frames=[frame],
        onPage=lambda canvas, doc: _pdf_footer(canvas, document),
    )
    doc = BaseDocTemplate(
        buffer, pagesize=A4, pageTemplates=[template],
        title=document.title, author="Quad4 Finance",
    )

    story: list = [
        _para(document.title, _TITLE),
        Spacer(1, 1.5 * mm),
        _para(document.subtitle, _SUBTITLE),
        Spacer(1, 1 * mm),
        _para(
            f"{document.period_label}  |  All amounts in {document.currency}",
            _META,
        ),
        Spacer(1, 3 * mm),
        HRFlowable(width="100%", thickness=1.6, color=INK),
        Spacer(1, 2 * mm),
    ]

    for section in document.sections:
        story.append(_header_label(section.title))
        story.append(Spacer(1, 1.5 * mm))
        for block in section.blocks:
            story.extend(_pdf_block_flowables(block))
            story.append(Spacer(1, 2.5 * mm))

    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def _html_line_chart(block: dict[str, Any]) -> str:
    width = 720.0
    height = 170.0
    pad_left = 52.0
    pad_bottom = 20.0
    series = block["series"]
    polylines, low, high, labels = _line_layout(
        series, width, height - pad_bottom, pad_left
    )

    parts = [
        f'<svg viewBox="0 0 {width:.0f} {height:.0f}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img">'
    ]
    plot_h = height - pad_bottom

    def flip(y: float) -> float:
        return plot_h - y

    for frac in (0.0, 0.5, 1.0):
        y = flip(frac * plot_h)
        value = low + (high - low) * frac
        parts.append(
            f'<line x1="{pad_left:.1f}" y1="{y:.1f}" x2="{width:.0f}" y2="{y:.1f}" '
            f'stroke="{_CSS_RULE}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="0" y="{y + 2:.1f}" font-size="8" fill="{_CSS_MUTED}">'
            f"{value:,.0f}</text>"
        )

    single = len(polylines) == 1
    for index, points in enumerate(polylines):
        color = SERIES_COLORS[index % len(SERIES_COLORS)]
        coords = " ".join(f"{x:.1f},{flip(y):.1f}" for x, y in points)
        if single:
            area = f"{pad_left:.1f},{plot_h:.1f} " + coords + f" {width:.0f},{plot_h:.1f}"
            parts.append(f'<polygon points="{area}" fill="{_CSS_TRACK}"/>')
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="{color}" '
            f'stroke-width="1.6" stroke-linejoin="round"/>'
        )
        if single:
            for x, y in points:
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{flip(y):.1f}" r="2" fill="{color}"/>'
                )

    for i, label in _short_labels(labels):
        n = max(len(labels) - 1, 1)
        x = pad_left + (i / n) * (width - pad_left)
        anchor = "start" if i == 0 else "end" if i == len(labels) - 1 else "middle"
        parts.append(
            f'<text x="{x:.1f}" y="{height - 4:.0f}" font-size="8" '
            f'fill="{_CSS_MUTED}" text-anchor="{anchor}">{escape(label)}</text>'
        )

    if not single:
        legend_x = width
        for index, s in reversed(list(enumerate(series))):
            name = s["name"]
            legend_x -= len(name) * 4.6 + 16
            parts.append(
                f'<rect x="{legend_x:.0f}" y="2" width="7" height="7" '
                f'fill="{SERIES_COLORS[index % len(SERIES_COLORS)]}"/>'
                f'<text x="{legend_x + 10:.0f}" y="8" font-size="8" '
                f'fill="{_CSS_SOFT}">{escape(name)}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _html_bars(block: dict[str, Any]) -> str:
    items = block["items"]
    top = max((item["value"] for item in items), default=1.0) or 1.0
    rows = []
    for item in items:
        pct = max(item["value"] / top * 100, 0.0)
        rows.append(
            '<div class="bar-row">'
            f'<span class="bar-label">{escape(item["label"])}</span>'
            '<span class="bar-track">'
            f'<span class="bar-fill" style="width:{pct:.1f}%"></span>'
            "</span>"
            f'<span class="bar-value">{escape(item["display"])}</span>'
            "</div>"
        )
    label = (
        f'<p class="block-label">{escape(block["label"].upper())}</p>'
        if block.get("label") else ""
    )
    return label + '<div class="bars">' + "".join(rows) + "</div>"


def _html_block(block: dict[str, Any]) -> str:
    kind = block["type"]
    if kind == "kpis":
        cards = "".join(
            '<div class="kpi">'
            f'<p class="kpi-label">{escape(item["label"].upper())}</p>'
            f'<p class="kpi-value">{escape(item["value"])}</p>'
            f'<p class="kpi-hint">{escape(item["hint"] or "")}</p>'
            "</div>"
            for item in block["items"]
        )
        return f'<div class="kpis">{cards}</div>'
    if kind == "line":
        return f'<div class="chart">{_html_line_chart(block)}</div>'
    if kind == "bars":
        return _html_bars(block)
    if kind == "table":
        head = "".join(
            f'<th class="{escape(col["align"])}">{escape(col["label"].upper())}</th>'
            for col in block["columns"]
        )
        body = "".join(
            "<tr>" + "".join(
                f'<td class="{escape(col["align"])}">{escape(str(cell))}</td>'
                for cell, col in zip(row, block["columns"])
            ) + "</tr>"
            for row in block["rows"]
        )
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    if kind == "note":
        return f'<p class="note">{escape(block["text"])}</p>'
    return ""


_HTML_STYLE = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: Helvetica, Arial, sans-serif;
  color: {_CSS_INK};
  background: #ffffff;
  font-size: 13px;
  line-height: 1.5;
}}
.page {{ max-width: 780px; margin: 0 auto; padding: 48px 40px 64px; }}
h1 {{ font-size: 26px; letter-spacing: -0.01em; }}
.subtitle {{ color: {_CSS_SOFT}; margin-top: 4px; }}
.meta {{ color: {_CSS_MUTED}; font-size: 11px; margin-top: 6px; }}
.title-rule {{ border: 0; border-top: 2px solid {_CSS_INK}; margin: 14px 0 8px; }}
section {{ margin-top: 30px; }}
h2 {{
  font-size: 10px; letter-spacing: 0.12em; color: {_CSS_MUTED};
  border-bottom: 1px solid {_CSS_RULE}; padding-bottom: 6px; margin-bottom: 14px;
}}
.kpis {{
  display: grid; grid-auto-flow: column; grid-auto-columns: 1fr;
  border: 1px solid {_CSS_RULE}; margin-bottom: 14px;
}}
.kpi {{ padding: 12px 14px; }}
.kpi + .kpi {{ border-left: 1px solid {_CSS_RULE}; }}
.kpi-label {{ font-size: 8px; letter-spacing: 0.08em; color: {_CSS_MUTED}; font-weight: 700; }}
.kpi-value {{ font-size: 17px; font-weight: 700; margin-top: 3px; }}
.kpi-hint {{ font-size: 9px; color: {_CSS_MUTED}; margin-top: 2px; min-height: 11px; }}
.chart {{ margin-bottom: 14px; }}
.chart svg {{ width: 100%; height: auto; display: block; }}
.block-label {{
  font-size: 9px; letter-spacing: 0.1em; color: {_CSS_SOFT};
  font-weight: 700; margin-bottom: 8px;
}}
.bars {{ margin-bottom: 14px; }}
.bar-row {{ display: flex; align-items: center; gap: 12px; padding: 3px 0; }}
.bar-label {{ flex: 0 0 200px; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.bar-track {{ flex: 1; height: 9px; background: {_CSS_TRACK}; }}
.bar-fill {{ display: block; height: 100%; background: {_CSS_INK}; }}
.bar-value {{ flex: 0 0 120px; text-align: right; font-size: 11px; color: {_CSS_SOFT}; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 12px; }}
th {{
  font-size: 8px; letter-spacing: 0.08em; color: {_CSS_MUTED};
  text-align: left; font-weight: 700; padding: 6px 0;
  border-bottom: 1px solid {_CSS_RULE};
}}
td {{ font-size: 11px; padding: 6px 0; border-bottom: 1px solid {_CSS_RULE}; }}
th.right, td.right {{ text-align: right; }}
tr:last-child td {{ border-bottom: 0; }}
.note {{ font-size: 10px; color: {_CSS_SOFT}; margin-bottom: 10px; }}
footer {{
  margin-top: 40px; padding-top: 10px; border-top: 1px solid {_CSS_RULE};
  color: {_CSS_MUTED}; font-size: 10px;
  display: flex; justify-content: space-between;
}}
@media print {{
  .page {{ padding: 0; max-width: none; }}
  section {{ break-inside: avoid-page; }}
}}
"""


def render_html(document: FinanceDocument) -> str:
    """The document as a single self-contained HTML file."""
    sections = []
    for section in document.sections:
        blocks = "".join(_html_block(b) for b in section.blocks)
        sections.append(
            f'<section><h2>{escape(section.title.upper())}</h2>{blocks}</section>'
        )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(document.title)}</title>\n"
        f"<style>{_HTML_STYLE}</style>\n"
        "</head>\n<body>\n<div class=\"page\">\n"
        f"<h1>{escape(document.title)}</h1>\n"
        f'<p class="subtitle">{escape(document.subtitle)}</p>\n'
        f'<p class="meta">{escape(document.period_label)}  |  '
        f"All amounts in {escape(document.currency)}</p>\n"
        '<hr class="title-rule">\n'
        + "".join(sections)
        + f'<footer><span>Generated {document.generated_on.isoformat()}</span>'
        "<span>Quad4 Finance</span></footer>\n"
        "</div>\n</body>\n</html>\n"
    )
