"""
Runi Reward System v1 — rutas del alumno (identidad seudonimizada, sin login).

Todos los POST son idempotentes: reintentar por mala conexión no duplica una recompensa ni vuelve a
acreditar Lumis. Nada de aquí toca notas ni evaluaciones.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.errors import unprocessable
from app.services import logros_service as ls
from app.services import recompensa_service as rw

router = APIRouter(tags=["recompensas"])


def _pseudo(payload: dict) -> str:
    p = str((payload or {}).get("pseudo_id") or "").strip()[:80]
    if not p:
        raise unprocessable("Falta la identidad del estudiante.")
    return p


@router.get("/recompensas/catalogo")
def catalogo():
    return {"ok": True, **rw.catalogo()}


@router.get("/recompensas/inventario")
def inventario(pseudo_id: str = "", db: Session = Depends(get_db)):
    return rw.inventario(db, pseudo_id)


@router.get("/recompensas/pendientes")
def pendientes(pseudo_id: str = "", db: Session = Depends(get_db)):
    return rw.pendientes(db, pseudo_id)


@router.get("/recompensas/cumbre")
def cumbre(pseudo_id: str = "", db: Session = Depends(get_db)):
    """Los 8 tramos del ascenso, qué falta en cada uno y las reglas del juego.

    Se apoya en el motor de medallas: aquí no se decide ningún desbloqueo. Las reglas viajan desde
    el servidor para que la pantalla no pueda contar una versión distinta de la que se aplica.
    """
    est = ls.estado(db, pseudo_id) if pseudo_id else {"medals": [], "xp": 0}
    return {"ok": True, "tramos": rw.cumbre(db, pseudo_id, est.get("medals") or []),
            "xp": est.get("xp", 0), "proxima": est.get("proxima"),
            "reglas": rw.reglas(),
            "saldo": rw.saldo(db, pseudo_id) if pseudo_id else 0}


@router.post("/recompensas/reclamar")
def reclamar(payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return rw.reclamar(db, _pseudo(p), str(p.get("pendiente_id") or ""), p.get("item_id"))


@router.post("/recompensas/equipar")
def equipar(payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return rw.equipar(db, _pseudo(p), str(p.get("slot") or ""), p.get("item_id"))


@router.post("/recompensas/comprar")
def comprar(payload: dict, db: Session = Depends(get_db)):
    p = payload or {}
    return rw.comprar(db, _pseudo(p), str(p.get("item_id") or ""))


@router.get("/recompensas/lumis")
def lumis(pseudo_id: str = "", limite: int = 60, db: Session = Depends(get_db)):
    return rw.libro_mayor(db, pseudo_id, limite)
