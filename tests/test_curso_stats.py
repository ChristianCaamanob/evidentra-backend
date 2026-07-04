"""
Test del motor de estadistica del curso (P1).

Verifica la psicometria clasica sobre un caso controlado y que el vinculo curricular
(por RA) solo aparece cuando se entrega la TE del instrumento (no se proyecta).
"""
from __future__ import annotations

from app.services import curso_stats_service as css

# Pauta de 4 items; correctas A,B,C,D.
PAUTA = {1: "A", 2: "B", 3: "C", 4: "D"}
# 5 alumnos con desempeno decreciente (para discriminacion positiva).
ALUMNOS = [
    {"student_id": "S1", "respuestas": {1: "A", 2: "B", 3: "C", 4: "D"}},  # 4/4
    {"student_id": "S2", "respuestas": {1: "A", 2: "B", 3: "C", 4: "A"}},  # 3/4
    {"student_id": "S3", "respuestas": {1: "A", 2: "B", 3: "A", 4: "A"}},  # 2/4
    {"student_id": "S4", "respuestas": {1: "A", 2: "A", 3: "A", 4: "A"}},  # 1/4
    {"student_id": "S5", "respuestas": {1: "B", 2: "A", 3: "A", 4: "A"}},  # 0/4
]
TE = {i: {"ra": f"RA{i}", "bloom": "Comprension", "unidad": "Unidad 1"} for i in (1, 2, 3, 4)}


def test_descriptivos_y_aprobacion():
    R = css.analizar_evaluacion(ALUMNOS, PAUTA, te_tags=TE)
    assert R["instrumento"]["n_alumnos"] == 5
    assert R["instrumento"]["n_items"] == 4
    # puntajes 4,3,2,1,0 -> % 100,75,50,25,0 -> media 50
    assert R["descriptivos_pct"]["media"] == 50.0
    assert R["descriptivos_pct"]["mediana"] == 50.0


def test_dificultad_y_distractores():
    R = css.analizar_evaluacion(ALUMNOS, PAUTA, te_tags=TE)
    it1 = next(x for x in R["items"] if x["item"] == 1)
    # item 1: 4 de 5 correctos (A) -> p=0.8
    assert it1["dificultad_p"] == 0.8
    assert it1["distractores"]["A"]["correcta"] is True
    assert it1["distractores"]["A"]["n"] == 4
    assert it1["distractores"]["B"]["n"] == 1


def test_discriminacion_positiva():
    R = css.analizar_evaluacion(ALUMNOS, PAUTA, te_tags=TE)
    # item 4 lo acierta solo el mejor alumno -> discrimina bien (pbis claramente positivo)
    it4 = next(x for x in R["items"] if x["item"] == 4)
    assert it4["discriminacion_pbis"] >= 0.30  # umbral de "buena discriminacion"


def test_kr20_presente():
    R = css.analizar_evaluacion(ALUMNOS, PAUTA, te_tags=TE)
    assert R["confiabilidad_kr20"] is not None


def test_por_ra_solo_con_te():
    con = css.analizar_evaluacion(ALUMNOS, PAUTA, te_tags=TE)
    assert con["por_ra"] is not None and len(con["por_ra"]) == 4
    # Sin TE: NO se proyecta vinculo curricular (cuidado pedido por el docente)
    sin = css.analizar_evaluacion(ALUMNOS, PAUTA, te_tags=None)
    assert sin["por_ra"] is None
    assert sin["instrumento"]["tiene_te"] is False


def test_dataset_para_investigador():
    R = css.analizar_evaluacion(ALUMNOS, PAUTA, te_tags=TE)
    assert len(R["dataset_largo"]) == 5 * 4          # tidy: alumno x item
    assert len(R["dataset_ancho"]) == 5
    fila = R["dataset_largo"][0]
    for campo in ("student_id", "item", "ra", "bloom", "correcto"):
        assert campo in fila
