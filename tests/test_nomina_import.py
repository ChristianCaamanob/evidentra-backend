"""Robustez del import de nómina (Excel) — variantes de encabezado, DV, sin encabezado."""
import io

import openpyxl

from app.services.nomina_service import parse_nomina_excel, clean_rut


def _xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_encabezados_estandar():
    r = parse_nomina_excel(_xlsx([
        ["RUT", "Apellido Paterno", "Apellido Materno", "Nombres"],
        ["12.345.678-5", "Soto", "Vera", "Ana"],
        ["9.876.543-3", "Lira", "Paz", "Beto"],
    ]))
    assert r["valid_count"] == 2 and r["error_count"] == 0
    assert r["students"][0]["rut"] == "12345678-5" and r["students"][0]["nombres"] == "Ana"


def test_run_y_apellidos_combinados():
    r = parse_nomina_excel(_xlsx([
        ["N°", "RUN estudiante", "Apellidos", "Nombres"],
        [1, "11.111.111-1", "Rojas Díaz", "Carolina"],
    ]))
    assert r["valid_count"] == 1
    assert r["students"][0]["apellido_paterno"] == "Rojas Díaz"


def test_dv_invalido_se_importa_igual():
    r = parse_nomina_excel(_xlsx([
        ["RUT", "Apellido Paterno", "Nombres"],
        ["12.345.678-9", "Díaz", "Darío"],   # DV incorrecto (correcto es 5)
    ]))
    assert r["valid_count"] == 1 and r["dv_advertencias"] == 1
    assert r["students"][0]["dv_ok"] is False


def test_sin_encabezado_posicional():
    r = parse_nomina_excel(_xlsx([
        ["18.700.000-0", "Muñoz Rey", "Elsa"],
        ["18.700.373-1", "Vega Luna", "Franco"],
    ]))
    assert r["valid_count"] == 2


def test_rut_pegado_sin_puntos_ni_guion():
    r = parse_nomina_excel(_xlsx([
        ["RUT", "Apellido Paterno", "Nombres"],
        ["123456785", "Núñez", "Ivo"],
    ]))
    assert r["valid_count"] == 1 and r["students"][0]["rut"] == "12345678-5"


def test_sin_columnas_reconocibles_da_error_sin_borrar():
    r = parse_nomina_excel(_xlsx([
        ["Cosa", "Otra"],
        ["x", "y"],
    ]))
    assert r["valid_count"] == 0 and r.get("error")   # error → la ruta NO borra la nómina


def test_clean_rut():
    assert clean_rut("12.345.678-5") == ("12345678-5", True)
    assert clean_rut("12345678K")[0] == "12345678-K"
    assert clean_rut("hola")[0] is None
