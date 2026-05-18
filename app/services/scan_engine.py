"""
Evidentra — Motor de escaneo óptico con OpenCV
"""
import cv2
import numpy as np
import json
import base64
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


def read_qr(img):
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(img)
    if not data:
        data, _, _ = detector.detectAndDecode(cv2.bitwise_not(img))
    if not data:
        return None
    try:
        p = json.loads(data)
        return QRData(p.get("aid",""), p.get("cid",""), int(p.get("nq",40)), p.get("ver","A"), data)
    except:
        return QRData(data[:12], "", 40, "A", data)


def is_bubble_filled(gray, cx, cy, r, threshold=0.45):
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.circle(mask, (cx, cy), max(r-3, 2), 255, -1)
    mean_val = cv2.mean(gray, mask=mask)[0]
    darkness = 1.0 - (mean_val/255.0)
    return darkness > threshold, darkness


def read_rut(gray):
    cfg = {"x_start":60,"y_start":220,"col_gap":66,"row_gap":60,"n_cols":9,"bubble_r":20}
    digits = []
    conf_scores = []
    DV = list(range(10)) + ["K"]
    for col in range(cfg["n_cols"]):
        cx = cfg["x_start"] + col*cfg["col_gap"]
        n_rows = 11 if col == 8 else 10
        col_data = []
        for row in range(n_rows):
            cy = cfg["y_start"] + row*cfg["row_gap"]
            filled, darkness = is_bubble_filled(gray, cx, cy, cfg["bubble_r"])
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
    n_per_col = n_questions // 2
    img_h = gray.shape[0]
    # row_gap dinámico según alto de imagen para evitar caer en pie de página
    y_start = 1050
    y_end = img_h - 120
    row_gap = int((y_end - y_start) / max(n_per_col - 1, 1))
    row_gap = max(55, min(row_gap, 95))  # limitar entre 55-95px
    cfg = {"col1_x":95,"col2_x":1155,"y_start":y_start,"choice_gap":83,"bubble_r":28}
    CHOICES = ["A","B","C","D","E"]
    answers = []
    ambiguous = []
    for col_idx in range(2):
        x_base = cfg["col1_x"] if col_idx == 0 else cfg["col2_x"]
        q_start = col_idx * n_per_col
        for row in range(n_per_col):
            cy = cfg["y_start"] + row*row_gap
            row_res = []
            for i, ch in enumerate(CHOICES):
                cx = x_base + i*cfg["choice_gap"]
                filled, dark = is_bubble_filled(gray, cx, cy, cfg["bubble_r"])
                row_res.append((ch, filled, dark))
            row_res.sort(key=lambda x: x[2], reverse=True)
            best = row_res[0]
            second = row_res[1] if len(row_res) > 1 else None
            if best[2] > 0.45:
                if second and second[2] > 0.35 and best[2]-second[2] < 0.12:
                    answers.append(None)
                    ambiguous.append(q_start+row+1)
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


def scan_sheet(image_bytes: bytes, n_questions_override: int = 0) -> ScanResult:
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return ScanResult(success=False, error="No se pudo decodificar la imagen")
    gray = preprocess(img)
    fiducials = find_fiducials(gray)
    if fiducials:
        img = correct_perspective(img, fiducials)
        gray = preprocess(img)
    qr_data = read_qr(gray)
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
