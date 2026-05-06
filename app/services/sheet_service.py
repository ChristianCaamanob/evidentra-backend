"""
Evidentra — Generador de hoja de respuesta PDF
Integrado al backend FastAPI. Devuelve el PDF como StreamingResponse.
"""
import io, json, math, hashlib
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm

W, H = A4

NAVY  = colors.HexColor('#08101D')
TEAL  = colors.HexColor('#0F8B8D')
TEAL2 = colors.HexColor('#1AA39E')
LGRAY = colors.HexColor('#CCCCCC')
BGRAY = colors.HexColor('#F7F5F2')
MGRAY = colors.HexColor('#888888')
WHITE = colors.white
BLACK = colors.black


def _fiducial(c, x, y, s=8*mm):
    c.setFillColor(BLACK); c.rect(x, y, s, s, fill=1, stroke=0)
    i = s * .38; o = (s - i) / 2
    c.setFillColor(WHITE); c.rect(x+o, y+o, i, i, fill=1, stroke=0)
    i2 = s * .16; o2 = (s - i2) / 2
    c.setFillColor(BLACK); c.rect(x+o2, y+o2, i2, i2, fill=1, stroke=0)


def _qr_matrix(data: str) -> list:
    SIZE = 25
    mat = [[False]*SIZE for _ in range(SIZE)]
    finder = [
        [1,1,1,1,1,1,1],[1,0,0,0,0,0,1],[1,0,1,1,1,0,1],
        [1,0,1,1,1,0,1],[1,0,1,1,1,0,1],[1,0,0,0,0,0,1],[1,1,1,1,1,1,1]
    ]
    def sb(r, c, p):
        for dr, row in enumerate(p):
            for dc, v in enumerate(row):
                if 0 <= r+dr < SIZE and 0 <= c+dc < SIZE:
                    mat[r+dr][c+dc] = bool(v)
    sb(0, 0, finder); sb(0, SIZE-7, finder); sb(SIZE-7, 0, finder)
    for i in range(8, SIZE-8):
        mat[6][i] = (i % 2 == 0)
        mat[i][6] = (i % 2 == 0)
    mat[SIZE-8][8] = True
    h = hashlib.md5(data.encode()).digest()
    idx = 0
    for r in range(SIZE):
        for c in range(SIZE):
            if not any([r < 8 and c < 8, r < 8 and c >= SIZE-7,
                        r >= SIZE-7 and c < 8, r == 6, c == 6]):
                mat[r][c] = bool(h[idx % 16] & (1 << (idx % 8)))
                idx += 1
    return mat


def _draw_qr(c, mat, x, y, size):
    n = len(mat); ms = size / n
    c.setFillColor(WHITE)
    c.rect(x-ms, y-ms, size+2*ms, size+2*ms, fill=1, stroke=0)
    for r in range(n):
        for col in range(n):
            if mat[r][col]:
                c.setFillColor(BLACK)
                c.rect(x+col*ms, y+(n-1-r)*ms, ms, ms, fill=1, stroke=0)


def _bubble(c, cx, cy, r, label, color=None):
    color = color or NAVY
    c.setLineWidth(0.9); c.setStrokeColor(color)
    c.setFillColor(WHITE); c.circle(cx, cy, r, fill=1, stroke=1)
    c.setFillColor(color)
    c.setFont('Helvetica-Bold', r * 1.55)
    c.drawCentredString(cx, cy - r * 0.52, label)


def generate_answer_sheet_pdf(
    assessment_id: str,
    course_id: str,
    course_name: str,
    assessment_name: str,
    n_questions: int,
    version: str,
    date: str = "2026",
    scale_min: float = 1.0,
    scale_max: float = 7.0,
    passing: float = 4.0,
    threshold_pct: int = 60,
) -> bytes:
    """Genera la hoja de respuesta y devuelve los bytes del PDF."""

    assert n_questions % 2 == 0, "n_questions debe ser par"
    N_PER_COL = n_questions // 2

    qr_mat = _qr_matrix(json.dumps(
        {'ev': '1', 'aid': assessment_id[:12], 'cid': course_id[:12],
         'nq': n_questions, 'ver': version},
        separators=(',', ':')))

    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    cv.setTitle(f'Evidentra — {assessment_name} V{version}')

    MX = 12*mm; MY = 10*mm

    # FIDUCIALES
    fs = 8*mm; fm = 6*mm
    _fiducial(cv, fm, fm, fs)
    _fiducial(cv, W-fm-fs, fm, fs)
    _fiducial(cv, fm, H-fm-fs, fs)
    _fiducial(cv, W-fm-fs, H-fm-fs, fs)

    # ENCABEZADO
    HDR_H = 10*mm
    hdr_y = H - MY - HDR_H
    cv.setFillColor(NAVY)
    cv.rect(MX, hdr_y, W-2*MX, HDR_H, fill=1, stroke=0)
    cv.setFillColor(TEAL)
    cv.rect(MX, hdr_y, 3*mm, HDR_H, fill=1, stroke=0)
    cv.setFillColor(WHITE); cv.setFont('Helvetica-Bold', 9)
    cv.drawString(MX+5*mm, hdr_y+3.8*mm, 'Evidentra')
    cv.setFillColor(TEAL2); cv.setFont('Helvetica', 4.5)
    cv.drawString(MX+5*mm, hdr_y+1.5*mm, 'INTELIGENCIA ACADEMICA')
    cv.setFillColor(WHITE); cv.setFont('Helvetica-Bold', 8)
    cv.drawCentredString(W/2, hdr_y+4*mm, assessment_name.upper())
    cv.setFillColor(LGRAY); cv.setFont('Helvetica', 6)
    cv.drawCentredString(W/2, hdr_y+1.5*mm,
        f'{course_name}  ·  {n_questions} preguntas  ·  Versión {version}')
    cv.setFillColor(TEAL); cv.setFont('Helvetica-Bold', 14)
    cv.drawRightString(W-MX-3*mm, hdr_y+3*mm, f'VER.{version}')

    # ZONA SUPERIOR
    top_zone_y = hdr_y - 2*mm
    if N_PER_COL <= 20:
        top_zone_h = 80*mm
        RUT_R = 2.6*mm; RUT_GX = 7.0*mm; RUT_GY = 6.2*mm
        RUT_HDR_H = 6*mm
    elif N_PER_COL <= 25:
        top_zone_h = 62*mm
        RUT_R = 2.2*mm; RUT_GX = 6.4*mm; RUT_GY = 5.0*mm
        RUT_HDR_H = 5*mm
    else:
        top_zone_h = 60*mm
        RUT_R = 2.1*mm; RUT_GX = 6.0*mm; RUT_GY = 4.8*mm
        RUT_HDR_H = 5*mm

    # RUT (9 columnas: 8 dígitos + DV)
    RUT_R = 2.6*mm; RUT_GX = 7.0*mm; RUT_GY = 6.2*mm
    N_DCOLS = 9; RUT_HDR_H = 6*mm
    rut_x0 = MX + 2*mm
    rut_block_w = (N_DCOLS-1)*RUT_GX + RUT_R*2 + 4*mm

    cv.setFillColor(BGRAY); cv.setStrokeColor(LGRAY); cv.setLineWidth(0.4)
    cv.roundRect(MX, top_zone_y-top_zone_h, rut_block_w, top_zone_h, 2*mm, fill=1, stroke=1)

    cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 6.5)
    cv.drawString(MX+3*mm, top_zone_y-5*mm, 'RUT')
    cv.setFillColor(MGRAY); cv.setFont('Helvetica', 5.5)
    cv.drawString(MX+3*mm, top_zone_y-8.5*mm, 'Sin puntos · con guion · dígito verificador')

    for i in range(N_DCOLS):
        cx = rut_x0 + i*RUT_GX
        cv.setFillColor(TEAL if i == 7 else NAVY)
        cv.setFont('Helvetica-Bold', 6)
        cv.drawCentredString(cx, top_zone_y-RUT_HDR_H-1*mm,
            str(i+1) if i < 8 else 'DV')

    cv.setStrokeColor(TEAL); cv.setLineWidth(1.0)
    sv = rut_x0 + 7.5*RUT_GX
    cv.line(sv, top_zone_y-RUT_HDR_H-3.5*mm, sv, top_zone_y-top_zone_h+2*mm)

    digits_dv = list(range(10)) + ['K']
    for i in range(N_DCOLS):
        cx = rut_x0 + i*RUT_GX
        rows = digits_dv if i == 8 else list(range(10))
        for j, d in enumerate(rows):
            cy = top_zone_y - RUT_HDR_H - (j+1)*RUT_GY
            if cy - RUT_R >= top_zone_y - top_zone_h + 1.5*mm:
                _bubble(cv, cx, cy, RUT_R, str(d),
                        color=TEAL if str(d) == 'K' else NAVY)

    # QR
    QR_SIZE = 22*mm
    qr_x = W - MX - QR_SIZE - 2*mm
    qr_y = top_zone_y - top_zone_h + 4*mm
    _draw_qr(cv, qr_mat, qr_x, qr_y, QR_SIZE)
    cv.setFillColor(MGRAY); cv.setFont('Helvetica', 4.5)
    cv.drawCentredString(qr_x+QR_SIZE/2, qr_y-3*mm, f'ID: {assessment_id}')
    cv.setFont('Helvetica', 4)
    cv.drawCentredString(qr_x+QR_SIZE/2, qr_y-5*mm, 'NO MARCAR ESTA ZONA')

    # DATOS ESTUDIANTE
    dat_x = MX + rut_block_w + 3*mm
    dat_w = qr_x - dat_x - 3*mm
    dat_y = top_zone_y - top_zone_h
    dat_h = top_zone_h

    cv.setFillColor(BGRAY); cv.setStrokeColor(LGRAY); cv.setLineWidth(0.4)
    cv.roundRect(dat_x, dat_y, dat_w, dat_h, 2*mm, fill=1, stroke=1)

    fields = [
        ('APELLIDOS Y NOMBRE', dat_h-6*mm, dat_h-10*mm),
        ('ASIGNATURA / CARRERA', dat_h-15*mm, dat_h-19*mm),
        ('SECCIÓN', dat_h-24*mm, dat_h-28*mm),
        ('FECHA', dat_h-33*mm, dat_h-37*mm),
        ('DOCENTE', dat_h-42*mm, dat_h-46*mm),
        ('EVALUACIÓN', dat_h-51*mm, dat_h-55*mm),
    ]
    for label, lbl_off, line_off in fields:
        cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 5.5)
        cv.drawString(dat_x+3*mm, dat_y+lbl_off, label)
        cv.setStrokeColor(LGRAY); cv.setLineWidth(0.5)
        cv.line(dat_x+3*mm, dat_y+line_off, dat_x+dat_w-3*mm, dat_y+line_off)

    cv.setFillColor(TEAL); cv.setFont('Helvetica-Bold', 5.5)
    cv.drawString(dat_x+3*mm, dat_y+2*mm,
        f'Escala {scale_min}–{scale_max}  ·  Aprobación {threshold_pct}%  ·  Nota mín. {passing}')

    # INSTRUCCIÓN
    INST_Y = top_zone_y - top_zone_h - 2*mm
    INST_H = 5.5*mm
    cv.setFillColor(NAVY)
    cv.rect(MX, INST_Y-INST_H, W-2*MX, INST_H, fill=1, stroke=0)
    cv.setFillColor(WHITE); cv.setFont('Helvetica-Bold', 6)
    cv.drawCentredString(W/2, INST_Y-INST_H+2*mm,
        'Rellene completamente la burbuja de su alternativa  ·  '
        'UNA respuesta por pregunta  ·  No use corrector líquido')

    # GRILLA
    GRID_TOP = INST_Y - INST_H - 3*mm
    PIE_H = 7*mm
    GRID_BOT = MY + PIE_H
    HDR_Q = 6*mm
    ROW_H = (GRID_TOP - GRID_BOT - HDR_Q) / N_PER_COL
    ROW_H = max(6.5*mm, min(ROW_H, 11*mm))

    BUB_R = 3.4*mm; BUB_GAP = 8.5*mm
    CHOICES = ['A','B','C','D','E']
    NUM_W = 10*mm; COL_GAP = 6*mm
    COL_W = (W - 2*MX - COL_GAP) / 2
    BUB_AREA = len(CHOICES) * BUB_GAP

    for col_idx in range(2):
        col_x = MX + col_idx*(COL_W + COL_GAP)
        q_start = col_idx*N_PER_COL + 1
        q_end = min(q_start+N_PER_COL-1, n_questions)
        bub_x0 = col_x + NUM_W + 2*mm

        cv.setFillColor(NAVY)
        cv.rect(col_x, GRID_TOP-HDR_Q, NUM_W+BUB_AREA+2*mm, HDR_Q, fill=1, stroke=0)
        cv.setFillColor(WHITE); cv.setFont('Helvetica-Bold', 7)
        cv.drawCentredString(col_x+NUM_W/2, GRID_TOP-HDR_Q+2*mm, 'N°')
        for i, l in enumerate(CHOICES):
            cv.drawCentredString(bub_x0+i*BUB_GAP, GRID_TOP-HDR_Q+2*mm, l)

        for q_idx, q_num in enumerate(range(q_start, q_end+1)):
            row_top = GRID_TOP - HDR_Q - (q_idx+1)*ROW_H
            row_ctr = row_top + ROW_H/2

            if q_idx % 2 == 0:
                cv.setFillColor(BGRAY)
                cv.rect(col_x, row_top, NUM_W+BUB_AREA+2*mm, ROW_H, fill=1, stroke=0)

            if q_idx % 5 == 0 and q_idx > 0:
                cv.setStrokeColor(LGRAY); cv.setLineWidth(0.8)
                cv.line(col_x, row_top+ROW_H, col_x+NUM_W+BUB_AREA+2*mm, row_top+ROW_H)

            cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 10)
            cv.drawRightString(col_x+NUM_W-1*mm, row_ctr-3.5*mm, f'{q_num}.')

            for i, l in enumerate(CHOICES):
                _bubble(cv, bub_x0+i*BUB_GAP, row_ctr, BUB_R, l)

    # PIE
    cv.setStrokeColor(LGRAY); cv.setLineWidth(0.4)
    cv.line(MX, MY+5*mm, W-MX, MY+5*mm)
    cv.setFillColor(MGRAY); cv.setFont('Helvetica', 5)
    cv.drawString(MX, MY+2*mm,
        f'Evidentra — Plataforma de Inteligencia Academica  |  '
        f'{assessment_name}  |  ID: {assessment_id}')
    cv.setFont('Helvetica-Bold', 5)
    cv.drawRightString(W-MX, MY+2*mm, f'Ver.{version}  ·  {n_questions}P  ·  {date}')

    cv.save()
    return buf.getvalue()
