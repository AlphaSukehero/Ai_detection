"""ReportLab document assembly for the three PDF reports.

Split out of app.py: this is a document renderer, not application logic. It
knows nothing about MRI, ECG or EEG -- callers hand it a title,
an accent colour, a metadata block and a list of (kind, heading, payload)
sections.
"""
import io
from html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from webapp.metadata import NOT_PROVIDED, metadata_rows
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    ListFlowable, ListItem, Image, KeepTogether,
)


REPORT_STYLES = getSampleStyleSheet()
REPORT_STYLES.add(ParagraphStyle(
    name="ReportTitle", parent=REPORT_STYLES["Title"],
    fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=4,
    textColor=colors.black, alignment=0
))
REPORT_STYLES.add(ParagraphStyle(
    name="ReportSubtitle", parent=REPORT_STYLES["Normal"],
    fontSize=9, leading=12, textColor=colors.HexColor("#333333"), alignment=0
))
REPORT_STYLES.add(ParagraphStyle(
    name="SectionHeading", parent=REPORT_STYLES["Heading3"],
    fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=10, spaceAfter=5,
    textColor=colors.black
))
REPORT_STYLES.add(ParagraphStyle(
    name="ReportBody", parent=REPORT_STYLES["BodyText"],
    fontSize=9.5, leading=13
))
REPORT_STYLES.add(ParagraphStyle(
    name="Cell", parent=REPORT_STYLES["BodyText"],
    fontSize=9, leading=11.5, spaceBefore=0, spaceAfter=0
))
REPORT_STYLES.add(ParagraphStyle(
    name="Disclaimer", parent=REPORT_STYLES["Italic"],
    fontSize=8.5, leading=11.5, textColor=colors.HexColor("#64748b")
))

TABLE_WIDTHS = [200, 323]


def verdict_section(title, verdict):
    """The headline result table every clinical report opens with."""
    return ("table", title, [("Result", "Assessment"),
                             (verdict["label"], verdict["detail"])])


def clinician_signoff():
    """Blank sign-off block for the reviewing clinician."""
    return ("table", "Reporting Clinician", [
        ("Field", "To be completed by the reviewing clinician"),
        ("Name & Qualification", " "),
        ("Registration No.", " "),
        ("Signature", " "),
        ("Date of Review", " "),
    ])


def doctor_sections(notes, concise=False):
    """Recommendations, with optional concise layout for clinical reports."""
    recommendations = notes.get("recommendations") or []
    sections = [("bullets", "Recommendations", recommendations)] if recommendations else []
    if not concise:
        precautions = notes.get("precautions") or []
        if precautions:
            sections.append(("bullets", "Precautions", precautions))
        sections.append(clinician_signoff())
    return sections


def _cell(text, bold=False):
    """Escape a value and wrap it in a Paragraph so long text wraps in-cell."""
    safe = escape(str(text if text not in (None, "") else NOT_PROVIDED))
    if bold:
        safe = f"<b>{safe}</b>"
    return Paragraph(safe, REPORT_STYLES["Cell"])


def _data_table(rows, accent=None):
    """Build a two-column clinical table with restrained grey headings."""
    data = [[_cell(rows[0][0], bold=True), _cell(rows[0][1], bold=True)]]
    data += [[_cell(label), _cell(value)] for label, value in rows[1:]]

    table = Table(data, colWidths=TABLE_WIDTHS, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8b8b8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _header_footer(canvas, doc, accent, footer_text):
    """Draw a neutral rule and consistent page number on every page."""
    canvas.saveState()
    width, _ = A4

    canvas.setStrokeColor(colors.HexColor("#999999"))
    canvas.setLineWidth(0.6)
    canvas.line(36, doc.pagesize[1] - 30, width - 36, doc.pagesize[1] - 30)

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#333333"))
    if footer_text:
        canvas.drawString(36, 24, footer_text)
    canvas.drawRightString(width - 36, 24, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


CONTENT_WIDTH = sum(TABLE_WIDTHS)
MAX_IMAGE_HEIGHT = 300


def _image(path, caption):
    """A picture scaled to the content width, or a stated absence."""
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as im:
            w, h = im.size
    except Exception:
        return Paragraph(escape(f"{caption}: image unavailable."),
                         REPORT_STYLES["ReportBody"])
    scale = min(CONTENT_WIDTH / w, MAX_IMAGE_HEIGHT / h)
    return Image(path, width=w * scale, height=h * scale, hAlign="LEFT")


def section_flowables(sections, accent):
    """Flowables for a list of (kind, heading, payload) sections.

    kind: "table"   -> [(label, value), ...] with a header row
          "text"    -> a paragraph
          "bullets" -> [item, ...]
          "image"   -> a file path (PNG/JPEG)
    """
    story = []
    for kind, heading, body in sections:
        head = Paragraph(escape(heading), REPORT_STYLES["SectionHeading"])
        if kind == "table":
            story += [head, _data_table(body, accent)]
        elif kind == "bullets":
            story += [head, ListFlowable(
                [ListItem(Paragraph(escape(str(item)), REPORT_STYLES["ReportBody"]),
                          leftIndent=12) for item in body],
                bulletType="bullet", start="•", leftIndent=12)]
        elif kind == "image":
            story.append(KeepTogether([head, _image(body, heading)]))
        else:
            story += [head, Paragraph(escape(str(body)), REPORT_STYLES["ReportBody"])]
        story.append(Spacer(1, 14))
    return story


def report_story(title, subtitle, accent, meta, meta_fields, meta_heading,
                 sections, disclaimer):
    """The flowables of one complete report, for embedding or building."""
    story = [
        Paragraph(escape(title), REPORT_STYLES["ReportTitle"]),
        Paragraph(escape(subtitle), REPORT_STYLES["ReportSubtitle"]),
        Spacer(1, 6),
        Paragraph(
            f"Report ID: <b>{escape(meta.get('report_id', NOT_PROVIDED))}</b> &nbsp;|&nbsp; "
            f"Generated: <b>{escape(meta.get('generated_at', NOT_PROVIDED))}</b>",
            REPORT_STYLES["ReportSubtitle"]
        ),
        Spacer(1, 16),
        Paragraph(escape(meta_heading), REPORT_STYLES["SectionHeading"]),
        _data_table([("Field", "Details")] + metadata_rows(meta, meta_fields), accent),
        Spacer(1, 16),
    ]
    story += section_flowables(sections, accent)
    if disclaimer:
        story.append(Spacer(1, 6))
        story.append(Paragraph(escape(disclaimer), REPORT_STYLES["Disclaimer"]))
    return story


def build_pdf_report(title, subtitle, accent, meta, meta_fields,
                     meta_heading, sections, disclaimer, footer_text):
    """Assemble a consistently styled PDF and return it as a BytesIO buffer.

    sections: see section_flowables.
    """
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=36, leftMargin=36, topMargin=48, bottomMargin=42,
        title=title, author="Unified AI Diagnostic Platform"
    )
    story = report_story(title, subtitle, accent, meta, meta_fields,
                         meta_heading, sections, disclaimer)

    def _decorate(canvas, doc):
        _header_footer(canvas, doc, accent, footer_text)

    document.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    buffer.seek(0)
    return buffer
