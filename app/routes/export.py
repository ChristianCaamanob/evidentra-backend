"""
Vías de exportación del Investigador (P2 · datasets para análisis externo).

  GET /assessments/{id}/export/matriz.csv        -> matriz 0/1 (persona x item) de UNA evaluación
                                                    (tramo a). Lista para R/lavaan (WLSMV), SPSS, jamovi.
  GET /courses/{id}/export/consolidado.csv       -> dataset largo (tidy) del curso:
                                                    una fila por (evaluación, persona, item, acierto).
                                                    hasta=N -> solo los primeros N tramos (AVANCE);
                                                    hasta=0 -> todas las evaluaciones (CIERRE consolidado).

Datos seudonimizados (G2). El sujeto es la persona-seudónimo, nunca el nombre.
"""
import csv
import io
import logging
import traceback
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_investigador
from app.models.assessment import Assessment
from app.services import matriz_service

router = APIRouter(tags=["export"])
logger = logging.getLogger("evalys")


def _csv(text: str, filename: str) -> StreamingResponse:
    return StreamingResponse(
        io.StringIO(text), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="' + filename + '"'})


@router.get("/assessments/{assessment_id}/export/matriz.csv",
            dependencies=[Depends(req_investigador)])
def export_matriz(assessment_id: UUID, db: Session = Depends(get_db)):
    """Matriz 0/1 (persona × ítem), seudonimizada — el respuestas.csv para el WLSMV en R."""
    try:
        datos = matriz_service.cargar_matriz_respuestas(db, assessment_id)
        X, items, personas = datos["X"], datos["items"], datos.get("personas", [])
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["persona"] + ["i" + str(it) for it in items])
        for idx in range(len(X)):
            pid = personas[idx] if idx < len(personas) else ("p%03d" % (idx + 1))
            w.writerow([pid] + [int(v) for v in X[idx]])
        return _csv(buf.getvalue(), "respuestas.csv")
    except Exception:
        logger.error("Error en export_matriz %s: %s", assessment_id, traceback.format_exc())
        raise


@router.get("/courses/{course_id}/export/consolidado.csv",
            dependencies=[Depends(req_investigador)])
def export_consolidado(course_id: UUID, hasta: int = Query(0, ge=0),
                       db: Session = Depends(get_db)):
    """
    Dataset largo del curso para análisis de avance (por tramos) o de cierre (consolidado).
    hasta > 0: incluye solo las primeras N evaluaciones (corte de avance).
    hasta = 0: incluye todas (consolidado de cierre).
    """
    try:
        evals = (db.query(Assessment)
                 .filter(Assessment.course_id == course_id)
                 .order_by(Assessment.created_at).all())
        if hasta and hasta > 0:
            evals = evals[:hasta]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["evaluacion", "persona", "item", "acierto"])
        incluidas = 0
        for ev in evals:
            try:
                datos = matriz_service.cargar_matriz_respuestas(db, ev.id)
            except Exception:
                continue   # evaluación sin datos suficientes -> se omite del consolidado
            X, items, personas = datos["X"], datos["items"], datos.get("personas", [])
            nombre = getattr(ev, "name", None) or str(ev.id)
            for pi in range(len(X)):
                pid = personas[pi] if pi < len(personas) else ("p%03d" % (pi + 1))
                for ii, it in enumerate(items):
                    w.writerow([nombre, pid, it, int(X[pi][ii])])
            incluidas += 1
        return _csv(buf.getvalue(),
                    ("consolidado_cierre.csv" if not hasta else ("avance_%d_tramos.csv" % hasta)))
    except Exception:
        logger.error("Error en export_consolidado %s: %s", course_id, traceback.format_exc())
        raise
