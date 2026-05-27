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
    thresh = cv2.adaptiveThreshold(gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 51, 10)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    h, w = gray.shape
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 500 or area > 15000:
            continue
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.04*peri, True)
        if len(approx) != 4:
            continue
        x, y, bw, bh = cv2.boundingRect(cnt)
        aspect = bw/bh if bh > 0 else 0
        if not (0.7 < aspect < 1.3):
            continue
        roi = gray[y+2:y+bh-2, x+2:x+bw-2]
        if roi.size == 0:
            continue
        if np.mean(roi) < 100:
            continue
        candidates.append((x+bw//2, y+bh//2, area))
    if len(candidates) < 4:
        return None
    candidates.sort(key=lambda c: c[2], reverse=True)
    pts = [(c[0], c[1]) for c in candidates[:4]]
    pts.sort(key=lambda p: p[1])
    top = sorted(pts[:2], key=lambda p: p[0])
    bot = sorted(pts[2:], key=lambda p: p[0])
    return [top[0], top[1], bot[0], bot[1]]


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
    """Verifica que los 4 fiduciales esten realmente cerca de las 4 esquinas.
    Si estan amontonados o lejos de las esquinas, no son confiables y
    corregir perspectiva con ellos deformaria la imagen."""
    if not fiducials or len(fiducials) != 4:
        return False
    h, w = shape[:2]
    # Esquinas ideales: TL, TR, BL, BR
    esquinas = [(0, 0), (w, 0), (0, h), (w, h)]
    # Cada fiducial debe estar dentro del 30% del tamano desde su esquina esperada
    tol_x = w * 0.30
    tol_y = h * 0.30
    for (fx, fy), (ex, ey) in zip(fiducials, esquinas):
        if abs(fx - ex) > tol_x or abs(fy - ey) > tol_y:
            return False
    # Verificar que no esten amontonados: area del cuadrilatero razonable
    xs = [p[0] for p in fiducials]
    ys = [p[1] for p in fiducials]
    ancho = max(xs) - min(xs)
    alto = max(ys) - min(ys)
    if ancho < w * 0.5 or alto < h * 0.5:
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
