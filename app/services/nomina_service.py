import re, io


def _dv_ok(num_str, dv):
    """Verifica el dígito verificador chileno (módulo 11)."""
    total = sum(int(d) * [2, 3, 4, 5, 6, 7, 2, 3][i] for i, d in enumerate(reversed(num_str)))
    r = 11 - (total % 11)
    exp = "0" if r == 11 else "K" if r == 10 else str(r)
    return dv == exp


def clean_rut(raw):
    """Normaliza un RUT/RUN a 'num-dv'. Devuelve (normalizado|None, dv_ok).
    Acepta el RUT aunque el DV no calce (dv_ok=False) — NO lo descarta: muchas nóminas reales
    traen DV imperfectos y el docente igual necesita la lista. Devuelve None solo si no parece RUT."""
    if raw is None:
        return None, False
    s = str(raw).strip().upper().replace(".", "").replace(" ", "")
    # Insertar guión si viene pegado (12345678K -> 12345678-K)
    if "-" not in s and len(s) >= 2 and s[-1] in "0123456789K":
        s = s[:-1] + "-" + s[-1]
    m = re.match(r"^(\d{6,9})-([0-9K])$", s)
    if not m:
        return None, False
    num_str, dv = m.group(1), m.group(2)
    return f"{num_str}-{dv}", _dv_ok(num_str, dv)


def validate_rut(rut):
    """Compat: (checksum_ok, normalizado)."""
    norm, ok = clean_rut(rut)
    return (bool(norm) and ok), (norm or str(rut or "").strip())


def _norm(v):
    return str(v or "").strip().upper()


def _looks_like_rut(v):
    return clean_rut(v)[0] is not None


def parse_nomina_excel(file_bytes):
    try:
        import openpyxl
    except Exception:
        return {"error": "openpyxl no disponible", "students": [], "errors": []}
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception as e:
        return {"error": "No se pudo abrir el Excel: " + str(e), "students": [], "errors": []}

    sheet = next((wb[n] for n in wb.sheetnames if "NOMINA" in n.upper() or "NÓMINA" in n.upper()),
                 wb.active)
    MAXC = min(sheet.max_column or 20, 30)

    # ── 1. Detectar la fila de encabezado (tolerante a variantes de nombre de columna) ──
    hrow = rcol = apcol = amcol = ncol = apellidos_col = None
    for ri in range(1, min((sheet.max_row or 20), 20) + 1):
        vals = {ci: _norm(sheet.cell(ri, ci).value) for ci in range(1, MAXC + 1)}
        rut_cols = [ci for ci, v in vals.items() if ("RUT" in v or "RUN" in v) and len(v) <= 24]
        if not rut_cols:
            continue
        pat = [ci for ci, v in vals.items() if "PATERNO" in v]
        mat = [ci for ci, v in vals.items() if "MATERNO" in v]
        nom = [ci for ci, v in vals.items() if "NOMBRE" in v]
        # "APELLIDOS" (columna combinada, sin paterno/materno separados)
        apes = [ci for ci, v in vals.items() if "APELLIDO" in v and "PATERNO" not in v and "MATERNO" not in v]
        if pat or nom or apes:
            hrow, rcol = ri, rut_cols[0]
            apcol = pat[0] if pat else None
            amcol = mat[0] if mat else None
            ncol = nom[0] if nom else None
            apellidos_col = apes[0] if (apes and not pat) else None
            break

    modo_posicional = False
    if not hrow:
        # ── Fallback SIN encabezado: si la 1ª celda de alguna de las primeras filas es un RUT,
        # asumimos col A=RUT, B=apellidos, C=nombres (o B=nombre completo). ──
        for ri in range(1, min((sheet.max_row or 5), 5) + 1):
            if _looks_like_rut(sheet.cell(ri, 1).value):
                hrow = ri - 1     # los datos empiezan en esta fila
                rcol, apellidos_col, ncol = 1, 2, 3
                modo_posicional = True
                break
    if not hrow and not modo_posicional:
        return {"error": "No se reconocieron columnas de RUT y nombre en el Excel. Asegúrate de "
                         "tener encabezados como 'RUT', 'Apellido Paterno', 'Apellido Materno', "
                         "'Nombres' (o usa la plantilla).",
                "students": [], "errors": [], "valid_count": 0, "error_count": 0, "total": 0}

    students, errors, seen = [], [], set()
    dv_warn = 0
    for ri in range(hrow + 1, (sheet.max_row or hrow) + 1):
        raw = sheet.cell(ri, rcol).value
        if raw is None or str(raw).strip() == "":
            continue
        # Filas-resumen al pie de las planillas de notas (no son alumnos): se ignoran en silencio.
        _low = re.sub(r"[^a-z]", "", str(raw).strip().lower())
        if _low in ("promedio", "promedios", "media", "desviacion", "desviacionestandar", "desv",
                    "total", "totales", "maximo", "minimo", "mediana", "moda", "aprobados", "reprobados"):
            continue
        norm, dvok = clean_rut(raw)
        ap = str(sheet.cell(ri, apcol).value or "").strip() if apcol else ""
        am = str(sheet.cell(ri, amcol).value or "").strip() if amcol else ""
        nm = str(sheet.cell(ri, ncol).value or "").strip() if ncol else ""
        if apellidos_col and not ap:          # columna combinada "Apellidos"
            ap = str(sheet.cell(ri, apellidos_col).value or "").strip()
        name = " ".join(x for x in (ap, am, nm) if x).strip() or ("Estudiante " + str(ri - hrow))
        if not norm:
            errors.append({"row": ri, "rut": str(raw), "name": name, "error": "No parece un RUT/RUN válido"})
            continue
        if norm in seen:
            errors.append({"row": ri, "rut": norm, "name": name, "error": "RUT duplicado (se omitió)"})
            continue
        seen.add(norm)
        if not dvok:
            dv_warn += 1
        students.append({"rut": norm, "name": name, "apellido_paterno": ap,
                         "apellido_materno": am, "nombres": nm, "dv_ok": dvok})

    return {
        "students": students,
        "errors": errors,
        "total": len(students) + len(errors),
        "valid_count": len(students),
        "error_count": len(errors),
        "dv_advertencias": dv_warn,
    }
