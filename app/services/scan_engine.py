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
    TARGET_W, TARGET_H = 2100, 2970
    src = np.float32(fiducials)
    dst = np.float32([[50,50],[TARGET_W-50,50],[50,TARGET_H-50],[TARGET_W-50,TARGET_H-50]])
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
    # Coordenadas derivadas de sheet_service.py. Imagen normalizada a 2100x2970 = 10px/mm.
    MM = 10.0
    H_MM = 297.0
    MX = 12.0
    rut_x0 = MX + 2.0
    RUT_GX = 7.0
    RUT_GY = 6.2
    RUT_R = 2.6
    MY = 10.0; HDR_H = 10.0
    hdr_y = H_MM - MY - HDR_H
    top_zone_y = hdr_y - 2.0
    RUT_HDR_H = 6.0
    N_DCOLS = 9
    bubble_r = int(RUT_R * MM)
    digits = []
    conf_scores = []
    DV = list(range(10)) + ["K"]
    for col in range(N_DCOLS):
        cx = int((rut_x0 + col*RUT_GX) * MM)
        n_rows = 11 if col == 8 else 10
        col_data = []
        for row in range(n_rows):
            cy_pdf = top_zone_y - RUT_HDR_H - (row+1)*RUT_GY
            cy = int((H_MM - cy_pdf) * MM)
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
                idx = best[2]
                digits.append(DV[idx] if col==8 else idx)
                conf_scores.append(best[1])
        else:
            digits.append(None)
            conf_scores.append(0.0)
    rut_str = None
    if all(d is not None for d in digits):
        num = "".join(str(d) for d in digits[:8])
        dv = str(digits[8])
        rut_str = f"{num}-{dv}"
    avg = float(np.mean([s for s in conf_scores if s > 0])) if any(s > 0 for s in conf_scores) else 0.0
    return rut_str, digits, avg, []


def read_answers(gray, n_questions):
    # Coordenadas derivadas de sheet_service.py. Imagen normalizada a 2100x2970 = 10px/mm.
    MM = 10.0
    H_MM = 297.0
    n_per_col = n_questions // 2
    MY = 10.0; HDR_H = 10.0
    hdr_y = H_MM - MY - HDR_H
    top_zone_y = hdr_y - 2.0
    top_zone_h = 80.0
    INST_Y = top_zone_y - top_zone_h - 2.0
    INST_H = 5.5
    GRID_TOP = INST_Y - INST_H - 3.0
    PIE_H = 7.0; GRID_BOT = MY + PIE_H
    HDR_Q = 6.0
    ROW_H = (GRID_TOP - GRID_BOT - HDR_Q) / n_per_col
    ROW_H = max(4.8, min(ROW_H, 11.0))
    MX = 12.0; COL_GAP = 6.0
    COL_W = (210.0 - 2*MX - COL_GAP) / 2
    NUM_W = 10.0; BUB_GAP = 8.5; BUB_R = 3.4
    CHOICES = ["A","B","C","D","E"]
    answers = []
    ambiguous = []
    for col_idx in range(2):
        col_x = MX + col_idx*(COL_W + COL_GAP)
        bub_x0 = col_x + NUM_W + 2.0
        q_start = col_idx * n_per_col
        for q_idx in range(n_per_col):
            row_top = GRID_TOP - HDR_Q - (q_idx+1)*ROW_H
            row_ctr_mm_bottom = row_top + ROW_H/2
            cy = int((H_MM - row_ctr_mm_bottom) * MM)
            row_res = []
            for i, ch in enumerate(CHOICES):
                cx = int((bub_x0 + i*BUB_GAP) * MM)
                filled, dark = is_bubble_filled(gray, cx, cy, int(BUB_R*MM))
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
    n_questions = n_questions_override or (qr_data.n_questions if qr_data else 40)
    if n_questions % 2 != 0:
        n_questions += 1
    rut_str, rut_digits, rut_conf, _ = read_rut(gray)
    answers, ambiguous = read_answers(gray, n_questions)
    debug_b64 = draw_debug(img, fiducials, qr_data, rut_digits, answers, ambiguous)
    answer_conf = sum(1 for a in answers if a is not None)/len(answers) if answers else 0
    return ScanResult(
        success=True, qr=qr_data, rut=rut_str, rut_digits=rut_digits,
        answers=answers, ambiguous=ambiguous,
        confidence=(rut_conf+answer_conf)/2, debug_image=debug_b64,
    )
