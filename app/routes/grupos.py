"""
Router de grupos de trabajo (evaluaciones con puntaje GRUPAL).

  POST /assessments/{id}/grupos                       -> crea grupo + integrantes (membresia inmutable)
  GET  /assessments/{id}/grupos                       -> lista grupos + integrantes
  POST /assessments/{id}/grupos/{grupo_id}/rubrica/validar -> valida criterios GRUPALES una vez

El criterio grupal se valida UNA VEZ (sujeto = el grupo); la nota de cada integrante lo
referencia (consistencia). Trazable e inmutable (G5); la nota es del docente (G1).
"""
import logging
import traceback
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, req_profesor, req_lectura_datos
from app.core.errors import not_found
from app.models.grupo import Grupo, GrupoIntegrante
from app.services import matriz_service, validacion_service

router = APIRouter(tags=["grupos"])
logger = logging.getLogger("evalys")


@router.post("/assessments/{assessment_id}/grupos", dependencies=[Depends(req_profesor)])
def crear_grupo(assessment_id: UUID, payload: dict, db: Session = Depends(get_db)):
    """payload = {nombre, integrantes:[student_id, ...]}. La membresia es append-only (snapshot)."""
    try:
        from app.models.assessment import Assessment
        if not db.get(Assessment, assessment_id):
            raise not_found("Evaluacion no encontrada.")
        g = Grupo(assessment_id=str(assessment_id), nombre=payload.get("nombre") or "Grupo")
        db.add(g); db.flush()
        for sid in payload.get("integrantes", []):
            db.add(GrupoIntegrante(grupo_id=g.id, student_id=str(sid)))
        db.commit(); db.refresh(g)
        return {"grupo_id": str(g.id), "nombre": g.nombre,
                "sujeto": matriz_service._pseudo(g.id),
                "n_integrantes": len(payload.get("integrantes", []))}
    except Exception:
        logger.error(f"Error en crear_grupo {assessment_id}: {traceback.format_exc()}")
        raise


@router.get("/assessments/{assessment_id}/grupos", dependencies=[Depends(req_lectura_datos)])
def listar_grupos(assessment_id: UUID, db: Session = Depends(get_db)):
    grupos = db.query(Grupo).filter(Grupo.assessment_id == str(assessment_id)).all()
    return {"grupos": [{"grupo_id": str(g.id), "nombre": g.nombre,
                        "sujeto": matriz_service._pseudo(g.id),
                        "integrantes": [i.student_id for i in g.integrantes]} for g in grupos]}


@router.post("/assessments/{assessment_id}/grupos/{grupo_id}/rubrica/validar",
             dependencies=[Depends(req_profesor)])
def validar_grupo(assessment_id: UUID, grupo_id: UUID, payload: dict,
                  db: Session = Depends(get_db)):
    """
    Valida los criterios GRUPALES de una vez: sujeto = el grupo. La misma decision aplica a
    todos los integrantes (una sola fuente de verdad). Trazabilidad inmutable (G5).
    """
    try:
        g = db.get(Grupo, grupo_id)
        if not g or g.assessment_id != str(assessment_id):
            raise not_found("Grupo no encontrado en esta evaluacion.")
        pseudo = matriz_service._pseudo(g.id)
        registros, version_hash = validacion_service.persistir_validaciones(
            db, pseudo, assessment_id, payload)
        return {"sujeto": pseudo, "ambito": "grupal", "grupo": g.nombre,
                "n_registrados": len(registros),
                "aplica_a": [i.student_id for i in g.integrantes],
                "rubrica_version_hash": version_hash,
                "gobernanza": "Decision grupal unica (consistencia); aplica a todos los "
                              "integrantes. Nota del docente (G1), trazable e inmutable (G5)."}
    except KeyError as e:
        raise not_found(f"Falta el campo {e} en un criterio del payload.")
    except Exception:
        logger.error(f"Error en validar_grupo {grupo_id}: {traceback.format_exc()}")
        raise
