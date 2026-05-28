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

    # ====== COORDENADAS ABSOLUTAS DEL MOCKUP V6 ======
    # Mockup SVG era 595x842 = A4 en puntos PDF, traslado directo.
    # En SVG Y crece hacia abajo. En ReportLab Y crece hacia arriba.
    # Conversion: y_rl = H - y_svg
    # Punto = unidad nativa de ReportLab, lo dejo sin *mm para coordenadas absolutas.
    from reportlab.lib.units import inch

    # ====== RECUADRO ALTERNATIVAS (izquierda) ======
    # SVG: x=30, y=230, w=290, h=900 (alto largo)
    # ReportLab: alt_x=30, alt_y=H-(230+900)=H-1130, alt_w=290, alt_h=900
    # Pero como H=842, no entra. Hay que escalar al canvas real.
    # El SVG era 842 alto. Lo dejamos identico ya que A4=842pt.
    # Pero las coords y=230 en SVG = (842-230)=612 en RL. Y h=900 sobrepasa el canvas.
    # Mejor: re-escribir las coords directamente en sistema ReportLab.

    # ALTERNATIVAS: ancho 295pt, desde x=30 hasta x=325. Alto desde y=140 hasta y=695 (SVG).
    # En RL: alt_y = H - 695 = 147. alt_h = 695-140 = 555.
    alt_x = 30
    alt_y = H - 695
    alt_w = 295
    alt_h = 555

    cv.setStrokeColor(BLACK); cv.setLineWidth(2)
    cv.setFillColor(WHITE)
    cv.rect(alt_x, alt_y, alt_w, alt_h, fill=1, stroke=1)
    cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 8)
    cv.drawString(alt_x + 10, alt_y + alt_h - 15, 'ALTERNATIVAS')
    cv.setFillColor(MGRAY); cv.setFont('Helvetica-Oblique', 5.5)
    cv.drawString(alt_x + 10, alt_y + alt_h - 25, 'Rellene UNA por pregunta')

    # 30 preguntas en 2 columnas (15 + 15)
    # Coords del mockup SVG: col1 numeros en x=58, burbujas x=80,96,112,128,144
    # col2 numeros en x=175, burbujas x=190,204,218,232,246
    # Primera fila y=184 (SVG) = H-184 (RL). Gap entre filas = 26 (SVG, hacia abajo) = -26 (RL).
    BUB_R = 6.5
    CHOICES = ['A','B','C','D','E']
    col1_num_x = 58
    col1_bub_xs = [80, 96, 112, 128, 144]
    col2_num_x = 175
    col2_bub_xs = [190, 204, 218, 232, 246]
    row_y_top_svg = 184
    row_gap = 26

    for col_idx, (num_x, bub_xs) in enumerate([(col1_num_x, col1_bub_xs), (col2_num_x, col2_bub_xs)]):
        q_start = col_idx*15 + 1
        for q_idx, q_num in enumerate(range(q_start, q_start+15)):
            y_svg = row_y_top_svg + q_idx*row_gap
            y_rl = H - y_svg
            cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 9)
            cv.drawRightString(num_x, y_rl - 3, f'{q_num}.')
            for i, l in enumerate(CHOICES):
                _bubble(cv, bub_xs[i], y_rl, BUB_R, l)

    # ====== RECUADRO RUT (arriba derecha) ======
    # Mockup SVG: x=335, y=140, w=231, h=200
    rut_x = 335
    rut_y = H - 340
    rut_w = 231
    rut_h = 200

    cv.setStrokeColor(BLACK); cv.setLineWidth(2)
    cv.setFillColor(WHITE)
    cv.rect(rut_x, rut_y, rut_w, rut_h, fill=1, stroke=1)
    cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 8)
    cv.drawString(rut_x + 11, rut_y + rut_h - 16, 'RUT')
    cv.setFillColor(MGRAY); cv.setFont('Helvetica', 5.5)
    cv.drawString(rut_x + 11, rut_y + rut_h - 26, 'Escriba arriba y rellene las burbujas')

    # Casillas para escribir RUT: 8 cajas en y=175 (SVG), w=16 h=18
    cas_y_svg = 175 + 18
    cas_y_rl = H - cas_y_svg
    cas_xs = [348, 367, 386, 405, 424, 443, 462, 481]
    cas_w = 16; cas_h = 18
    cv.setStrokeColor(BLACK); cv.setLineWidth(0.6)
    for cx in cas_xs:
        cv.rect(cx, cas_y_rl, cas_w, cas_h, fill=0, stroke=1)
    cv.setFillColor(MGRAY); cv.setFont('Helvetica-Oblique', 7)
    cv.drawString(503, cas_y_rl + 7, '- DV auto')

    # 8 columnas de burbujas, 10 filas (0-9)
    # Mockup: centros x = 356, 375, 394, 413, 432, 451, 470, 489 (gap 19)
    # Primera fila y=205 (SVG), gap 13 entre filas
    rut_bub_xs = [356, 375, 394, 413, 432, 451, 470, 489]
    rut_y_top_svg = 205
    rut_row_gap = 13
    rut_bub_r = 5.5

    for col_x in rut_bub_xs:
        for j in range(10):
            y_svg = rut_y_top_svg + j*rut_row_gap
            y_rl = H - y_svg
            _bubble(cv, col_x, y_rl, rut_bub_r, str(j), color=NAVY)

    # ====== RECUADRO FORM IDENTIFIER (debajo del RUT) ======
    # Mockup: x=335, y=355, w=231, h=80
    fid_x = 335
    fid_y = H - 435
    fid_w = 231
    fid_h = 80

    cv.setStrokeColor(BLACK); cv.setLineWidth(2)
    cv.setFillColor(WHITE)
    cv.rect(fid_x, fid_y, fid_w, fid_h, fill=1, stroke=1)
    cv.setFillColor(NAVY); cv.setFont('Helvetica-Bold', 8)
    cv.drawString(fid_x + 11, fid_y + fid_h - 16, 'FORM IDENTIFIER')
    cv.setFillColor(MGRAY); cv.setFont('Helvetica-Oblique', 5.5)
    cv.drawString(fid_x + 11, fid_y + fid_h - 26, 'No marcar - uso del sistema')

    # 2 filas de 13 burbujas: y_svg = 400 (fila sup), 420 (fila inf)
    FID_PATTERN = [
        [2,1,0,2,1,1,2,2,0,1,2,0,2],
        [1,2,0,1,1,2,1,0,1,2,0,1,1],
    ]
    fid_xs = [353, 368, 383, 398, 413, 428, 443, 458, 473, 488, 503, 518, 533]
    fid_y_rows_svg = [400, 420]
    fid_bub_r = 5.0

    for row_idx, row in enumerate(FID_PATTERN):
        y_rl = H - fid_y_rows_svg[row_idx]
        for col_idx, state in enumerate(row):
            bx = fid_xs[col_idx]
            cv.setStrokeColor(BLACK); cv.setLineWidth(0.6)
            if state == 1:
                cv.setFillColor(BLACK)
                cv.circle(bx, y_rl, fid_bub_r, fill=1, stroke=1)
            elif state == 2:
                cv.setFillColor(WHITE)
                cv.circle(bx, y_rl, fid_bub_r, fill=1, stroke=1)
                cv.line(bx-fid_bub_r*0.7, y_rl-fid_bub_r*0.35, bx+fid_bub_r*0.7, y_rl-fid_bub_r*0.35)
                cv.line(bx-fid_bub_r*0.8, y_rl, bx+fid_bub_r*0.8, y_rl)
                cv.line(bx-fid_bub_r*0.7, y_rl+fid_bub_r*0.35, bx+fid_bub_r*0.7, y_rl+fid_bub_r*0.35)
            else:
                cv.setFillColor(WHITE)
                cv.circle(bx, y_rl, fid_bub_r, fill=1, stroke=1)

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
