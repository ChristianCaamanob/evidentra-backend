"""
Evidentra — Generador de hoja de respuesta PDF
Integrado al backend FastAPI. Devuelve el PDF como StreamingResponse.
"""
import io, json, math, hashlib
try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False
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
    # Halo blanco alrededor para aislar del header/pie u otros elementos negros
    halo = 3*mm
    c.setFillColor(WHITE); c.rect(x-halo, y-halo, s+2*halo, s+2*halo, fill=1, stroke=0)
    # Patron concentrico negro-blanco-negro
    c.setFillColor(BLACK); c.rect(x, y, s, s, fill=1, stroke=0)
    i = s * .38; o = (s - i) / 2
    c.setFillColor(WHITE); c.rect(x+o, y+o, i, i, fill=1, stroke=0)
    i2 = s * .16; o2 = (s - i2) / 2
    c.setFillColor(BLACK); c.rect(x+o2, y+o2, i2, i2, fill=1, stroke=0)


def _get_qr_matrix(data: str) -> list:
    """Genera matriz QR real usando qrcode, o simulada como fallback."""
    if HAS_QRCODE:
        qr = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=1, border=4)
        qr.add_data(data)
        qr.make(fit=True)
        mat = qr.get_matrix()
        return mat
    # Fallback: matriz simulada
    SIZE = 25
    mat = [[False]*SIZE for _ in range(SIZE)]
    h = hashlib.md5(data.encode()).digest()
    idx = 0
    for r in range(SIZE):
        for col in range(SIZE):
            mat[r][col] = bool(h[idx % 16] & (1 << (idx % 8)))
            idx += 1
    return mat


def _draw_qr(c, mat, x, y, size):
    n = len(mat); ms = size / n
    c.setFillColor(WHITE)
    c.rect(x-4*ms, y-4*ms, size+8*ms, size+8*ms, fill=1, stroke=0)
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
    """Hoja Evalys v6: tres recuadros separados, sin QR.
    Layout estilo GradeCam con identidad Evalys."""
    assert n_questions % 2 == 0, "n_questions debe ser par"
    N_PER_COL = n_questions // 2

    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    cv.setTitle(f'Evalys - {assessment_name} V{version}')

    # ====== MARGENES Y FIDUCIALES ======
    MX = 16*mm  # margen horizontal del papel (deja espacio a los fiduciales)
    MY = 16*mm  # margen vertical del papel (deja espacio a los fiduciales)
    fs = 10*mm; fm = 3*mm
    _fiducial(cv, fm, fm, fs)
    _fiducial(cv, W-fm-fs, fm, fs)
    _fiducial(cv, fm, H-fm-fs, fs)
    _fiducial(cv, W-fm-fs, H-fm-fs, fs)

    # ====== HEADER NAVY CON FRANJA TEAL ======
    HDR_H = 12*mm
    hdr_y = H - MY - HDR_H
    cv.setFillColor(NAVY)
    cv.rect(MX, hdr_y, W-2*MX, HDR_H, fill=1, stroke=0)
    cv.setFillColor(TEAL)
    cv.rect(MX, hdr_y, 1.5*mm, HDR_H, fill=1, stroke=0)
    cv.setFillColor(WHITE); cv.setFont('Helvetica-Bold', 11)
    cv.drawString(MX+5*mm, hdr_y+6.5*mm, 'Evalys')
    cv.setFillColor(TEAL2); cv.setFont('Helvetica', 5.5)
    cv.drawString(MX+5*mm, hdr_y+2.5*mm, 'INTELIGENCIA ACADEMICA')
    cv.setFillColor(WHITE); cv.setFont('Helvetica-Bold', 10)
    cv.drawCentredString(W/2, hdr_y+7*mm, assessment_name.upper())
    cv.setFillColor(LGRAY); cv.setFont('Helvetica', 7)
    cv.drawCentredString(W/2, hdr_y+2.5*mm,
        f'{course_name} . {n_questions} preguntas . Version {version}')
    cv.setFillColor(TEAL2); cv.setFont('Helvetica-Bold', 14)
    cv.drawRightString(W-MX-3*mm, hdr_y+4*mm, f'VER.{version}')

    # ====== DATOS DEL ESTUDIANTE (lineas, sin recuadro) ======
    DAT_Y = hdr_y - 6*mm
    cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 7)
    cv.drawString(MX+2*mm, DAT_Y, 'APELLIDOS Y NOMBRE')
    cv.setStrokeColor(MGRAY); cv.setLineWidth(0.5)
    cv.line(MX+2*mm, DAT_Y-3*mm, MX+95*mm, DAT_Y-3*mm)
    cv.drawString(MX+102*mm, DAT_Y, 'ASIGNATURA / CARRERA')
    cv.line(MX+102*mm, DAT_Y-3*mm, W-MX-2*mm, DAT_Y-3*mm)

    DAT_Y2 = DAT_Y - 10*mm
    cv.drawString(MX+2*mm, DAT_Y2, 'SECCION')
    cv.line(MX+2*mm, DAT_Y2-3*mm, MX+45*mm, DAT_Y2-3*mm)
    cv.drawString(MX+50*mm, DAT_Y2, 'FECHA')
    cv.line(MX+50*mm, DAT_Y2-3*mm, MX+95*mm, DAT_Y2-3*mm)
    cv.drawString(MX+102*mm, DAT_Y2, 'DOCENTE')
    cv.line(MX+102*mm, DAT_Y2-3*mm, W-MX-2*mm, DAT_Y2-3*mm)

    # ====== TOP DE LOS RECUADROS PRINCIPALES ======
    BOXES_TOP = DAT_Y2 - 10*mm

    # ====== RECUADRO RUT (arriba derecha) ======
    # Geometria: 8 columnas de burbujas + texto auxiliar
    RUT_BUB_R = 2.6*mm
    RUT_BUB_GX = 7.5*mm  # mas aire horizontal entre burbujas
    RUT_BUB_GY = 6.5*mm  # mas aire vertical entre filas
    N_DIGS = 8
    RUT_INNER_PAD = 4*mm
    RUT_BUB_AREA_W = (N_DIGS-1)*RUT_BUB_GX + 2*RUT_BUB_R
    RUT_BUB_AREA_H = 10*RUT_BUB_GY + 2*RUT_BUB_R - RUT_BUB_GY
    RUT_TITULO_H = 10*mm   # titulo + subtitulo
    RUT_CASILLAS_H = 8*mm  # casillas para escribir RUT
    RUT_W = RUT_BUB_AREA_W + 2*RUT_INNER_PAD + 18*mm  # extra para "DV auto"
    RUT_H = RUT_TITULO_H + RUT_CASILLAS_H + RUT_BUB_AREA_H + 2*RUT_INNER_PAD

    rut_x = W - MX - RUT_W
    rut_y = BOXES_TOP - RUT_H

    cv.setStrokeColor(BLACK); cv.setLineWidth(2)
    cv.setFillColor(WHITE)
    cv.rect(rut_x, rut_y, RUT_W, RUT_H, fill=1, stroke=1)

    cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 8)
    cv.drawString(rut_x + RUT_INNER_PAD, rut_y + RUT_H - 6*mm, 'RUT')
    cv.setFillColor(MGRAY); cv.setFont('Helvetica', 5.5)
    cv.drawString(rut_x + RUT_INNER_PAD, rut_y + RUT_H - 9.5*mm,
        'Escriba arriba y rellene las burbujas')

    # Casillas para escribir el RUT (8 cajas separadas)
    cas_w = 6*mm; cas_h = 6.5*mm
    cas_gap = RUT_BUB_GX - cas_w  # mismo gap que las burbujas
    cas_x0 = rut_x + RUT_INNER_PAD + (RUT_BUB_R - cas_w/2)
    cas_y = rut_y + RUT_H - RUT_TITULO_H - cas_h
    cv.setStrokeColor(BLACK); cv.setLineWidth(0.6)
    for i in range(N_DIGS):
        cx = cas_x0 + i*RUT_BUB_GX - (RUT_BUB_R - cas_w/2)
        cv.rect(cx, cas_y, cas_w, cas_h, fill=0, stroke=1)
    # "DV auto" a la derecha
    dv_text_x = cas_x0 + (N_DIGS-1)*RUT_BUB_GX + cas_w + 2*mm
    cv.setFillColor(MGRAY); cv.setFont('Helvetica-Oblique', 6)
    cv.drawString(dv_text_x, cas_y + cas_h/2 - 1*mm, '- DV auto')

    # Burbujas del RUT (8 columnas x 10 filas)
    bub_x0 = rut_x + RUT_INNER_PAD + RUT_BUB_R
    bub_y0_top = cas_y - RUT_BUB_R - 1.5*mm  # primera fila empieza aqui
    for i in range(N_DIGS):
        cx = bub_x0 + i*RUT_BUB_GX
        for j in range(10):
            cy = bub_y0_top - j*RUT_BUB_GY
            _bubble(cv, cx, cy, RUT_BUB_R, str(j), color=NAVY)

    # ====== RECUADRO FORM IDENTIFIER (debajo del RUT) ======
    FID_H = 22*mm
    FID_GAP = 4*mm
    fid_x = rut_x
    fid_w = RUT_W
    fid_y = rut_y - FID_GAP - FID_H

    cv.setStrokeColor(BLACK); cv.setLineWidth(2)
    cv.setFillColor(WHITE)
    cv.rect(fid_x, fid_y, fid_w, FID_H, fill=1, stroke=1)

    cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 8)
    cv.drawString(fid_x + 4*mm, fid_y + FID_H - 5*mm, 'FORM IDENTIFIER')
    cv.setFillColor(MGRAY); cv.setFont('Helvetica-Oblique', 5.5)
    cv.drawString(fid_x + 4*mm, fid_y + FID_H - 9*mm, 'No marcar - uso del sistema')

    # Patron fijo de prueba: 2 filas x 13 burbujas, 3 estados (0=vacia,1=rellena,2=rayada)
    FID_PATTERN = [
        [2,1,0,2,1,1,2,2,0,1,2,0,2],
        [1,2,0,1,1,2,1,0,1,2,0,1,1],
    ]
    fid_bub_r = 2.0*mm
    fid_bub_gap = (fid_w - 8*mm) / 13.0
    fid_row_gap = 5.5*mm
    fid_bub_y0 = fid_y + 3.5*mm  # fila inferior
    for row_idx, row in enumerate(FID_PATTERN):
        by = fid_bub_y0 + (1-row_idx)*fid_row_gap
        for col_idx, state in enumerate(row):
            bx = fid_x + 4*mm + col_idx*fid_bub_gap + fid_bub_gap/2
            cv.setStrokeColor(BLACK); cv.setLineWidth(0.6)
            if state == 1:
                cv.setFillColor(BLACK)
                cv.circle(bx, by, fid_bub_r, fill=1, stroke=1)
            elif state == 2:
                cv.setFillColor(WHITE)
                cv.circle(bx, by, fid_bub_r, fill=1, stroke=1)
                cv.line(bx-fid_bub_r*0.7, by-fid_bub_r*0.35, bx+fid_bub_r*0.7, by-fid_bub_r*0.35)
                cv.line(bx-fid_bub_r*0.8, by, bx+fid_bub_r*0.8, by)
                cv.line(bx-fid_bub_r*0.7, by+fid_bub_r*0.35, bx+fid_bub_r*0.7, by+fid_bub_r*0.35)
            else:
                cv.setFillColor(WHITE)
                cv.circle(bx, by, fid_bub_r, fill=1, stroke=1)

    # ====== RECUADRO ALTERNATIVAS (izquierda, alto) ======
    BUB_R = 2.8*mm
    CHOICES = ['A','B','C','D','E']
    BUB_GAP = 6*mm  # ajustado para que 2 columnas + gap quepan en alt_w
    NUM_W = 11*mm  # mas aire entre numero de pregunta y burbuja A
    COL_INNER_GAP = 8*mm  # aire entre columna 1-15 y columna 16-30
    INNER_PAD_X = 3*mm  # corre el bloque hacia la izquierda
    INNER_PAD_TOP = 10*mm
    INNER_PAD_BOTTOM = 4*mm
    ROW_H = 6.8*mm

    col_w = NUM_W + len(CHOICES)*BUB_GAP
    alt_w = rut_x - MX - 4*mm  # ancho del recuadro alternativas
    alt_y = MY + 18*mm  # deja espacio abajo para pie
    alt_h = BOXES_TOP - alt_y
    alt_x = MX

    cv.setStrokeColor(BLACK); cv.setLineWidth(2)
    cv.setFillColor(WHITE)
    cv.rect(alt_x, alt_y, alt_w, alt_h, fill=1, stroke=1)

    cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 8)
    cv.drawString(alt_x + 4*mm, alt_y + alt_h - 5*mm, 'ALTERNATIVAS')
    cv.setFillColor(MGRAY); cv.setFont('Helvetica-Oblique', 5.5)
    cv.drawString(alt_x + 4*mm, alt_y + alt_h - 9*mm, 'Rellene UNA por pregunta')

    grid_top = alt_y + alt_h - INNER_PAD_TOP - 3*mm
    grid_bottom = alt_y + INNER_PAD_BOTTOM
    avail_h = grid_top - grid_bottom
    actual_row_h = avail_h / N_PER_COL

    # Posiciones X de las dos columnas, alineadas a la izquierda con padding
    col1_x = alt_x + INNER_PAD_X
    col2_x = col1_x + col_w + COL_INNER_GAP

    for col_idx, col_x in enumerate([col1_x, col2_x]):
        q_start = col_idx*N_PER_COL + 1
        q_end = q_start + N_PER_COL - 1
        bub_x0 = col_x + NUM_W

        for q_idx, q_num in enumerate(range(q_start, q_end+1)):
            row_ctr = grid_top - q_idx*actual_row_h - actual_row_h/2
            cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 9)
            cv.drawRightString(col_x + NUM_W - 2*mm, row_ctr - 2.5*mm, f'{q_num}.')
            for i, l in enumerate(CHOICES):
                _bubble(cv, bub_x0 + i*BUB_GAP, row_ctr, BUB_R, l)

    # ====== PIE ======
    cv.setFillColor(MGRAY); cv.setFont('Helvetica-Oblique', 6)
    cv.drawCentredString(W/2, MY + 13*mm,
        'Use lapicero negro . Rellene completamente . UNA respuesta por pregunta . No use corrector')
    cv.setFillColor(TEAL); cv.setFont('Helvetica-Bold', 7.5)
    cv.drawCentredString(W/2, MY + 8*mm,
        f'Escala {scale_min}-{scale_max} . Aprobacion {threshold_pct}% . Nota minima {passing}')

    cv.setFillColor(MGRAY); cv.setFont('Helvetica', 5.5)
    cv.drawString(MX, MY + 2*mm,
        f'Evalys . ID: {assessment_id[:13]} . {assessment_name} . {course_name}')
    cv.setFillColor(TEAL); cv.setFont('Helvetica-Bold', 6)
    cv.drawRightString(W-MX, MY + 2*mm,
        f'Ver.{version} . {n_questions}P . {date}')

    cv.save()
    return buf.getvalue()
