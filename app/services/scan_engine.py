"""
Evidentra — Motor de escaneo óptico con OpenCV
"""
import cv2
import numpy as np
import json
import base64
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    from PIL import Image
    import io as _io
    _HEIC_OK = True
except Exception:
    _HEIC_OK = False
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QRData:
    assessment_id: str
    course_id: str
    n_questions: int
    version: str
    raw: str


@dataclass
class ScanResult:
    success: bool
    qr: Optional[QRData] = None
    rut: Optional[str] = None
    rut_digits: list = field(default_factory=list)
    answers: list = field(default_factory=list)
    ambiguous: list = field(default_factory=list)
    confidence: float = 0.0
    debug_image: Optional[str] = None
    error: Optional[str] = None
    detected_version: Optional[str] = None
    detected_n: Optional[int] = None


def preprocess(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    gray = clahe.apply(gray)
    gray = cv2.GaussianBlur(gray, (3,3), 0)
    return gray


def find_fiducials(gray):
    """Detecta los marcadores concentricos (negro-blanco-negro) de las 4 esquinas.
    Usa jerarquia de contornos: un fiducial es un contorno negro que contiene
    un contorno blanco que contiene un contorno negro. La barra del encabezado
    y las burbujas NO tienen esa estructura anidada, asi que se descartan solas."""
    h, w = gray.shape
    _, binimg = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, hierarchy = cv2.findContours(binimg, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return None
    hierarchy = hierarchy[0]

    def es_cuadrado(cnt):
        area = cv2.contourArea(cnt)
        if area < 100:
            return False, 0, 0, 0
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.05*peri, True)
        if len(approx) != 4:
            return False, 0, 0, 0
        x, y, bw, bh = cv2.boundingRect(cnt)
        aspect = bw/bh if bh > 0 else 0
        if not (0.6 < aspect < 1.4):
            return False, 0, 0, 0
        # que sea solido: el area del contorno ocupa buena parte del bounding box
        rect_area = bw*bh
        if rect_area == 0 or area/rect_area < 0.6:
            return False, 0, 0, 0
        return True, x+bw//2, y+bh//2, bw

    candidatos = []
    for i, cnt in enumerate(contours):
        # buscar contorno EXTERNO negro (sin padre o con padre que sea el fondo)
        ok, cx, cy, sz = es_cuadrado(cnt)
        if not ok:
            continue
        # contar descendientes anidados: debe haber al menos un hijo (blanco) con un nieto (negro)
        hijo = hierarchy[i][2]
        if hijo == -1:
            continue
        nieto = hierarchy[hijo][2]
        if nieto == -1:
            continue
        # validar que el hijo tambien sea cuadrado-ish (el cuadro blanco interior)
        ok_h, _, _, _ = es_cuadrado(contours[hijo])
        if not ok_h:
            continue
        candidatos.append((cx, cy, sz))

    if len(candidatos) < 4:
        return None

    # Quedarse con el mejor candidato por cuadrante (cercano a cada esquina de la imagen)
    esquinas = [(0,0), (w,0), (0,h), (w,h)]
    seleccion = []
    usados = set()
    for ex, ey in esquinas:
        mejor = None
        mejor_d = None
        for idx, (cx, cy, sz) in enumerate(candidatos):
            if idx in usados:
                continue
            d = (cx-ex)**2 + (cy-ey)**2
            if mejor_d is None or d < mejor_d:
                mejor_d = d; mejor = idx
        if mejor is None:
            return None
        usados.add(mejor)
        seleccion.append((candidatos[mejor][0], candidatos[mejor][1]))
    # seleccion ya viene en orden TL, TR, BL, BR
    return seleccion


def correct_perspective(img, fiducials):
    """Endereza la imagen mapeando los fiduciales detectados a las posiciones
    exactas donde sheet_service los dibuja. Asi se preserva toda la hoja sin recortes."""
    TARGET_W, TARGET_H = 2100, 2970
    # Posiciones reales de los CENTROS de los fiduciales en el papel:
    # fiducial a 3mm del borde, de 10mm de lado -> centro a 8mm del borde = 80px
    OFFSET = 80
    src = np.float32(fiducials)
    dst = np.float32([
        [OFFSET, OFFSET],                          # TL
        [TARGET_W-OFFSET, OFFSET],                 # TR
        [OFFSET, TARGET_H-OFFSET],                 # BL
        [TARGET_W-OFFSET, TARGET_H-OFFSET],        # BR
    ])
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (TARGET_W, TARGET_H))


def _try_decode(detector, im):
    try:
        data, _, _ = detector.detectAndDecode(im)
        if data:
            return data
    except Exception:
        pass
    return None


def read_qr(img_color):
    detector = cv2.QRCodeDetector()
    variants = []
    g = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY) if len(img_color.shape) == 3 else img_color
    variants.append(img_color)
    variants.append(g)
    variants.append(cv2.bitwise_not(g))
    _, otsu = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(otsu)
    variants.append(cv2.bitwise_not(otsu))
    for scale in (1.5, 2.0, 0.75):
        try:
            variants.append(cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC))
        except Exception:
            pass
    data = None
    for v in variants:
        data = _try_decode(detector, v)
        if data:
            break
    if not data:
        return None
    try:
        p = json.loads(data)
        return QRData(p.get("aid",""), p.get("cid",""), int(p.get("nq",40)), p.get("ver","A"), data)
    except Exception:
        return QRData(data[:12], "", 40, "A", data)


def is_bubble_filled(gray, cx, cy, r, threshold=0.45):
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.circle(mask, (cx, cy), max(r-3, 2), 255, -1)
    mean_val = cv2.mean(gray, mask=mask)[0]
    darkness = 1.0 - (mean_val/255.0)
    return darkness > threshold, darkness


def read_rut(gray):
    """Coordenadas del v6 en PUNTOS PDF, convertidas a pixeles.
    Imagen normalizada 2100x2970. Factor: 2100/595.27 = 3.528 px/punto.
    Las coordenadas SVG del v6 usan y_svg, y en el PDF y_rl = H_PT - y_svg.
    En la imagen (Y hacia abajo): y_px = y_svg * FACTOR directamente."""
    FACTOR = 2100.0 / 595.27  # = 3.528 px por punto PDF
    H_PT = 841.89

    # RUT v6: 8 columnas, centros x (en puntos) y filas
    rut_bub_xs = [356, 375, 394, 413, 432, 451, 470, 489]
    rut_y_top_svg = 205   # primera fila (digito 0), coordenada SVG
    rut_row_gap = 13
    rut_bub_r_pt = 5.5

    bubble_r = int(rut_bub_r_pt * FACTOR)
    digits = []
    conf_scores = []
    # En el v6 NO hay columna DV con burbujas (DV se calcula). Solo 8 columnas 0-9.
    for col_x_pt in rut_bub_xs:
        cx = int(col_x_pt * FACTOR)
        col_data = []
        for row in range(10):
            y_svg = rut_y_top_svg + row * rut_row_gap
            cy = int(y_svg * FACTOR)  # y_svg ya esta en sistema imagen (Y hacia abajo)
            filled, darkness = is_bubble_filled(gray, cx, cy, bubble_r)
            col_data.append((filled, darkness, row))
        col_data.sort(key=lambda x: x[1], reverse=True)
        best = col_data[0]
        if best[1] > 0.45:
            second = col_data[1] if len(col_data) > 1 else (False, 0, -1)
            if second[1] > 0.35 and best[1]-second[1] < 0.15:
                digits.append(None)
                conf_scores.append(0.0)
            else:
                digits.append(best[2])
                conf_scores.append(best[1])
        else:
            digits.append(None)
            conf_scores.append(0.0)
    # Calcular DV automaticamente (modulo 11) si los 8 digitos estan
    rut_str = None
    if all(d is not None for d in digits):
        num = "".join(str(d) for d in digits)
        dv = _calcular_dv(num)
        rut_str = f"{num}-{dv}"
        digits = digits + [dv]
    avg = float(np.mean([s for s in conf_scores if s > 0])) if any(s > 0 for s in conf_scores) else 0.0
    return rut_str, digits, avg, []


def _calcular_dv(num_str):
    """Calcula el digito verificador chileno (modulo 11) de un RUT de 8 digitos."""
    reversed_digits = [int(d) for d in reversed(num_str)]
    factors = [2, 3, 4, 5, 6, 7]
    s = sum(d * factors[i % 6] for i, d in enumerate(reversed_digits))
    resto = 11 - (s % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


def read_answers(gray, n_questions):
    """Coordenadas del v6 en PUNTOS PDF convertidas a pixeles.
    Alternativas en 2 columnas (1-15, 16-30)."""
    FACTOR = 2100.0 / 595.27

    # v6: coordenadas SVG (Y hacia abajo, igual que la imagen)
    col1_bub_xs = [87, 103, 119, 135, 151]
    col2_bub_xs = [210, 226, 242, 258, 274]
    row_y_top_svg = 184
    bub_r_pt = 6.5
    CHOICES = ["A", "B", "C", "D", "E"]

    n_per_col = n_questions // 2
    # Misma formula adaptativa que el generador (deben coincidir exactamente)
    row_gap = min(26.0, 498.0/(n_per_col-1)) if n_per_col > 1 else 26.0
    bubble_r = int(bub_r_pt * FACTOR)
    answers = []
    ambiguous = []

    for col_idx, bub_xs in enumerate([col1_bub_xs, col2_bub_xs]):
        q_start = col_idx * n_per_col
        for q_idx in range(n_per_col):
            y_svg = row_y_top_svg + q_idx * row_gap
            cy = int(y_svg * FACTOR)
            row_res = []
            for i, ch in enumerate(CHOICES):
                cx = int(bub_xs[i] * FACTOR)
                filled, dark = is_bubble_filled(gray, cx, cy, bubble_r)
                row_res.append((ch, filled, dark))
            row_res.sort(key=lambda x: x[2], reverse=True)
            best = row_res[0]
            second = row_res[1] if len(row_res) > 1 else None
            if best[2] > 0.45:
                if second and second[2] > 0.35 and best[2]-second[2] < 0.12:
                    answers.append(None)
                    ambiguous.append(q_start+q_idx+1)
                else:
                    answers.append(best[0])
            else:
                answers.append(None)
    return answers, ambiguous


def draw_debug(img, fiducials, qr_data, rut_digits, answers, ambiguous):
    debug = img.copy()
    if fiducials:
        for pt in fiducials:
            cv2.circle(debug, pt, 15, (0,255,0), 3)
    if qr_data:
        cv2.putText(debug, f"QR:{qr_data.assessment_id[:8]}", (50,50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,200,0), 3)
    if rut_digits:
        rut = "".join(str(d) if d is not None else "?" for d in rut_digits[:8])
        dv = str(rut_digits[8]) if len(rut_digits)>8 and rut_digits[8] is not None else "?"
        cv2.putText(debug, f"RUT:{rut}-{dv}", (50,100),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255,100,0), 3)
    scale = 0.3
    small = cv2.resize(debug, (0,0), fx=scale, fy=scale)
    _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return base64.b64encode(buf).decode("utf-8")


def _fiducials_confiables(fiducials, shape):
    """Con deteccion por patron concentrico ya confiamos en la estructura.
    Solo verificamos que los 4 puntos formen un cuadrilatero con area razonable
    (no amontonados) y que esten distribuidos en los 4 cuadrantes."""
    if not fiducials or len(fiducials) != 4:
        return False
    h, w = shape[:2]
    xs = [p[0] for p in fiducials]
    ys = [p[1] for p in fiducials]
    ancho = max(xs) - min(xs)
    alto = max(ys) - min(ys)
    # deben abarcar al menos 40% del ancho y alto (no amontonados)
    if ancho < w * 0.4 or alto < h * 0.4:
        return False
    return True


def read_form_id(gray):
    """Decodifica el FORM IDENTIFIER (version + N). Mismas coords que el generador.
    Devuelve (version_letter, n_questions) o (None, None) si no es legible o falla paridad."""
    FACTOR = 2100.0 / 595.27
    fid_xs = [353, 368, 383, 398, 413, 428, 443, 458, 473, 488, 503, 518, 533]
    fid_y_rows_svg = [400, 420]
    fid_bub_r = 5.0
    r = int(fid_bub_r * FACTOR)
    rows = []
    for y_svg in fid_y_rows_svg:
        cy = int(y_svg * FACTOR)
        bits = []
        for bx in fid_xs:
            cx = int(bx * FACTOR)
            filled, _ = is_bubble_filled(gray, cx, cy, r)
            bits.append(1 if filled else 0)
        rows.append(bits)
    row0, row1 = rows[0], rows[1]
    if row0[0] != 1 or row1[0] != 1:
        return None, None
    vbits = row0[1:6]
    if sum(vbits) % 2 != row0[6]:
        return None, None
    v = 0
    for b in vbits:
        v = (v << 1) | b
    if v < 1 or v > 31:
        return None, None
    version = chr(ord('A') + v - 1)
    nbits = row1[1:8]
    if sum(nbits) % 2 != row1[8]:
        return None, None
    nq = 0
    for b in nbits:
        nq = (nq << 1) | b
    return version, (nq if nq > 0 else None)


def scan_sheet(image_bytes: bytes, n_questions_override: int = 0) -> ScanResult:
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None and _HEIC_OK:
        # Intentar como HEIC/HEIF (iPhone) via Pillow
        try:
            pil = Image.open(_io.BytesIO(image_bytes)).convert("RGB")
            img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        except Exception:
            img = None
    if img is None:
        return ScanResult(success=False, error="No se pudo decodificar la imagen (formato no soportado)")
    img_original = img.copy()
    gray = preprocess(img)
    fiducials = find_fiducials(gray)
    # Solo corregir perspectiva si los fiduciales son CREIBLES (cerca de las 4 esquinas).
    # Si no, deformaria la imagen y descuadraria las burbujas.
    if fiducials and _fiducials_confiables(fiducials, gray.shape):
        img = correct_perspective(img, fiducials)
        gray = preprocess(img)
        img_original = img.copy()
    else:
        # Normalizar al tamano estandar (2100x2970) para que calcen las coordenadas
        img = cv2.resize(img, (2100, 2970), interpolation=cv2.INTER_AREA)
        gray = preprocess(img)
        img_original = img.copy()
    qr_data = read_qr(img_original)
    fid_version, fid_n = read_form_id(gray)
    n_questions = n_questions_override or fid_n or (qr_data.n_questions if qr_data else 40)
    if n_questions % 2 != 0:
        n_questions += 1
    rut_str, rut_digits, rut_conf, _ = read_rut(gray)
    answers, ambiguous = read_answers(gray, n_questions)
    debug_b64 = draw_debug(img, fiducials, qr_data, rut_digits, answers, ambiguous)
    answer_conf = sum(1 for a in answers if a is not None)/len(answers) if answers else 0
    detected_version = fid_version or (qr_data.version if qr_data else None)
    return ScanResult(
        success=True, qr=qr_data, rut=rut_str, rut_digits=rut_digits,
        answers=answers, ambiguous=ambiguous,
        confidence=(rut_conf+answer_conf)/2, debug_image=debug_b64,
        detected_version=detected_version, detected_n=fid_n,
    )
