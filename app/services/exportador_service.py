"""Infraestructura de exportación GENÉRICA y transversal: DOCX · PDF · XLSX.

Complementa a export_service (que es específico del curso). Cualquier módulo arma su contenido
y llama a `exportar(formato, payload)`. Formato por contenido (lo más riguroso):
  · DOCX  → documentos narrativos (manuscrito, informe): Word editable.
  · PDF   → entregable de layout fijo (impresión del informe/manuscrito).
  · XLSX  → datos tabulares (corpus, efectos, ítems, referencias, notas).

Documento narrativo (docx/pdf):
  {"titulo": str, "secciones": [{"heading": str|None, "nivel": 1|2, "texto": str}],
   "tablas": [{"titulo": str, "headers": [...], "rows": [[...]]}]}
Libro tabular (xlsx):
  {"hojas": [{"nombre": str, "headers": [...], "rows": [[...]]}]}

El texto admite **negrita** con markdown simple. Dependencias: reportlab, openpyxl, python-docx.
"""
from __future__ import annotations

import io
import re


def _split_bold(texto: str):
    partes, i = [], 0
    for m in re.finditer(r"\*\*(.+?)\*\*", texto or ""):
        if m.start() > i:
            partes.append((texto[i:m.start()], False))
        partes.append((m.group(1), True))
        i = m.end()
    if i < len(texto or ""):
        partes.append((texto[i:], False))
    return partes or [("", False)]


# ───────────────────────────── XLSX (openpyxl)
def to_xlsx(hojas: list[dict]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()
    wb.remove(wb.active)
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="4B3F72")
    for h in (hojas or [{"nombre": "Datos", "headers": [], "rows": []}]):
        ws = wb.create_sheet((h.get("nombre") or "Hoja")[:31])
        headers = h.get("headers") or []
        if headers:
            ws.append([str(x) for x in headers])
            for c in ws[1]:
                c.font = hdr_font
                c.fill = hdr_fill
                c.alignment = Alignment(vertical="center")
        for row in (h.get("rows") or []):
            ws.append(["" if v is None else v for v in row])
        for col in ws.columns:
            largo = max((len(str(c.value)) for c in col if c.value is not None), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max(largo + 2, 10), 60)
        if headers:
            ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ───────────────────────────── DOCX (python-docx)
def to_docx(doc: dict) -> bytes:
    from docx import Document
    from docx.shared import Pt

    d = Document()
    if doc.get("titulo"):
        d.add_heading(doc["titulo"], level=0)
    for sec in (doc.get("secciones") or []):
        if sec.get("heading"):
            d.add_heading(sec["heading"], level=int(sec.get("nivel", 1)))
        if sec.get("texto"):
            for parrafo in str(sec["texto"]).split("\n"):
                p = d.add_paragraph()
                for seg, bold in _split_bold(parrafo):
                    run = p.add_run(seg)
                    run.bold = bold
                    run.font.size = Pt(11)
    for t in (doc.get("tablas") or []):
        if t.get("titulo"):
            d.add_heading(t["titulo"], level=2)
        headers = t.get("headers") or []
        tbl = d.add_table(rows=1, cols=max(1, len(headers)))
        try:
            tbl.style = "Light Grid Accent 1"
        except Exception:
            pass
        for j, hcell in enumerate(headers):
            tbl.rows[0].cells[j].paragraphs[0].add_run(str(hcell)).bold = True
        for row in (t.get("rows") or []):
            cells = tbl.add_row().cells
            for j, v in enumerate(row[:len(headers)] if headers else row):
                cells[j].text = "" if v is None else str(v)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ───────────────────────────── PDF (reportlab)
def to_pdf(doc: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    h0 = ParagraphStyle("H0", parent=ss["Title"], fontSize=16, leading=20, spaceAfter=10)
    h1 = ParagraphStyle("H1", parent=ss["Heading2"], fontSize=12,
                        textColor=colors.HexColor("#4B3F72"), spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("B", parent=ss["BodyText"], fontSize=10, leading=15, spaceAfter=6, alignment=4)

    def esc(s):
        s = (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)

    story = []
    if doc.get("titulo"):
        story.append(Paragraph(esc(doc["titulo"]), h0))
    for sec in (doc.get("secciones") or []):
        if sec.get("heading"):
            story.append(Paragraph(esc(sec["heading"]), h1))
        if sec.get("texto"):
            for parrafo in str(sec["texto"]).split("\n"):
                if parrafo.strip():
                    story.append(Paragraph(esc(parrafo), body))
    for t in (doc.get("tablas") or []):
        if t.get("titulo"):
            story.append(Paragraph(esc(t["titulo"]), h1))
        headers = [str(x) for x in (t.get("headers") or [])]
        data = [headers] + [["" if v is None else str(v) for v in row] for row in (t.get("rows") or [])]
        if len(data) > 1:
            tbl = Table(data, hAlign="LEFT")
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4B3F72")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f1f8")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            story.append(Spacer(1, 4))
            story.append(tbl)
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm,
                      leftMargin=2 * cm, rightMargin=2 * cm).build(story)
    return buf.getvalue()


MEDIA = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


def exportar(formato: str, payload: dict) -> tuple[bytes, str]:
    if formato == "xlsx":
        return to_xlsx(payload.get("hojas") or []), MEDIA["xlsx"]
    if formato == "docx":
        return to_docx(payload), MEDIA["docx"]
    if formato == "pdf":
        return to_pdf(payload), MEDIA["pdf"]
    raise ValueError("formato no soportado")
