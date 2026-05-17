import re, io


def validate_rut(rut):
    if not rut:
        return False, ""
    rut = str(rut).strip().upper().replace(".", "")
    if "-" not in rut and len(rut) >= 2:
        rut = rut[:-1] + "-" + rut[-1]
    m = re.match(r"^(\d{7,8})-([0-9K])$", rut)
    if not m:
        return False, rut
    num_str, dv = m.group(1), m.group(2)
    total = sum(int(d) * [2, 3, 4, 5, 6, 7, 2, 3][i] for i, d in enumerate(reversed(num_str)))
    r = 11 - (total % 11)
    exp = "0" if r == 11 else "K" if r == 10 else str(r)
    return (dv == exp), f"{num_str}-{dv}"


def parse_nomina_excel(file_bytes):
    try:
        import openpyxl
    except Exception:
        return {"error": "openpyxl no disponible", "students": [], "errors": []}
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception as e:
        return {"error": str(e), "students": [], "errors": []}

    sheet = next((wb[n] for n in wb.sheetnames if "NOMINA" in n.upper()), wb.active)

    hrow = rcol = apcol = amcol = ncol = None
    for ri in range(1, 15):
        row_vals = {ci: str(sheet.cell(ri, ci).value or "").upper() for ci in range(1, 10)}
        rut_cols = [ci for ci, v in row_vals.items() if "RUT" in v and len(v) < 10]
        ap_cols = [ci for ci, v in row_vals.items() if "APELLIDO" in v and "PATERNO" in v]
        if rut_cols and ap_cols:
            hrow = ri
            rcol = rut_cols[0]
            apcol = ap_cols[0]
            for ci, v in row_vals.items():
                if "APELLIDO" in v and "MATERNO" in v:
                    amcol = ci
                if "NOMBRE" in v and "APELLIDO" not in v:
                    ncol = ci
            break

    if not hrow:
        return {"error": "No se encontro fila de encabezado", "students": [], "errors": []}

    students, errors, seen = [], [], set()
    for ri in range(hrow + 1, sheet.max_row + 1):
        raw = sheet.cell(ri, rcol).value
        if not raw:
            continue
        raw = str(raw).strip()
        ok, rut = validate_rut(raw)
        ap = str(sheet.cell(ri, apcol).value or "").strip() if apcol else ""
        am = str(sheet.cell(ri, amcol).value or "").strip() if amcol else ""
        nm = str(sheet.cell(ri, ncol).value or "").strip() if ncol else ""
        name = f"{ap} {am} {nm}".strip() or f"Estudiante {ri - hrow}"
        if not ok:
            errors.append({"row": ri, "rut": raw, "name": name, "error": "RUT invalido"})
            continue
        if rut in seen:
            errors.append({"row": ri, "rut": rut, "name": name, "error": "RUT duplicado"})
            continue
        seen.add(rut)
        students.append({
            "rut": rut,
            "name": name,
            "apellido_paterno": ap,
            "apellido_materno": am,
            "nombres": nm,
        })

    return {
        "students": students,
        "errors": errors,
        "total": len(students) + len(errors),
        "valid_count": len(students),
        "error_count": len(errors),
    }
