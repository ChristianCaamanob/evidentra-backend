"""
C2 - Importacion de curriculo (programa / RA / tabla de especificaciones).

Principio (G6, postura propositiva): se PRESERVA el texto aprobado del programa.
La importacion es literal: el texto entra tal cual y se guarda sin reformular. La
plataforma aporta valor vinculando (RA <-> items <-> Bloom), nunca reescribiendo el
programa del docente.

La importacion es idempotente por (course_id, code): volver a importar actualiza el
mismo RA en lugar de duplicarlo, para poder recargar el programa las veces que haga
falta sin ensuciar los datos.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.curriculo import LearningOutcome

# Codigo del curso de referencia del roadmap (Morfologia).
DMOR0030_CODE = "DMOR0030"

# Seed de RA de DMOR0030. El texto es un marcador de posicion representativo:
# debe reemplazarse por el texto EXACTO del programa oficial cuando este disponible.
# La importacion lo guardara literalmente, sea cual sea (esa es justamente la garantia
# que verifica el test de aceptacion).
DMOR0030_RA: list[dict] = [
    {"code": "RA1", "unidad": "Unidad I", "orden": 1,
     "text": "Reconocer la organizacion general del cuerpo humano y su terminologia anatomica."},
    {"code": "RA2", "unidad": "Unidad II", "orden": 2,
     "text": "Describir la estructura del sistema osteoarticular y muscular."},
    {"code": "RA3", "unidad": "Unidad III", "orden": 3,
     "text": "Relacionar la morfologia de los sistemas con su funcion."},
    {"code": "RA4", "unidad": "Unidad IV", "orden": 4,
     "text": "Integrar los conocimientos morfologicos en el analisis de casos."},
]


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def import_curriculo(db: Session, course_id, ras: list[dict]) -> list[LearningOutcome]:
    """
    Importa (o actualiza) los RA de un curso preservando su texto literal.

    ras: lista de dicts con al menos {"code", "text"} y opcionalmente
         {"unidad", "orden", "source"}. El "text" se almacena EXACTAMENTE como llega.

    Idempotente por (course_id, code). Devuelve los RA importados, en orden.
    """
    cid = _as_uuid(course_id)
    existentes = {
        lo.code: lo
        for lo in db.query(LearningOutcome).filter(LearningOutcome.course_id == cid).all()
    }
    resultado: list[LearningOutcome] = []
    for i, ra in enumerate(ras):
        code = ra["code"]
        # Preservacion literal: no se aplica strip, lower, ni normalizacion alguna.
        text = ra["text"]
        lo = existentes.get(code)
        if lo is None:
            lo = LearningOutcome(course_id=cid, code=code)
            db.add(lo)
        lo.text = text
        lo.unidad = ra.get("unidad")
        lo.orden = ra.get("orden", i + 1)
        lo.source = ra.get("source", "programa_oficial")
        resultado.append(lo)
    db.commit()
    for lo in resultado:
        db.refresh(lo)
    resultado.sort(key=lambda x: x.orden)
    return resultado


def import_dmor0030(db: Session, course_id) -> list[LearningOutcome]:
    """Carga los RA de DMOR0030 sobre un curso ya existente, preservando el texto."""
    return import_curriculo(db, course_id, DMOR0030_RA)
