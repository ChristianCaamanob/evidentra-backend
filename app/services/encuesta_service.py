"""
Encuestas de Runi: crear, ver (con lista blanca), votar y contar.

Dos decisiones que sostienen el resto:
- **Un voto por persona.** Cambiar de opinión ACTUALIZA el voto; no se acumulan filas. Si no,
  el gráfico dejaría de ser "qué piensa el curso" y pasaría a ser "quién insistió más".
- **La identidad sale del token**, nunca de un campo del cuerpo, igual que en los grupos.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found, unprocessable
from app.models.encuesta import Encuesta, EncuestaVoto

_MAX_OPCIONES = 6
_MAX_LARGO_OPCION = 80


def _norm_rut(r) -> str:
    """Mismo criterio que usa la identificación del alumno: sin puntos, guion ni espacios."""
    return re.sub(r"[^0-9kK]", "", str(r or "")).lower()


def _rut_de_owner(owner_key: str) -> str:
    """El owner_key de la Pandilla es 'rut:<normalizado>' cuando la persona se identificó."""
    ow = str(owner_key or "")
    return _norm_rut(ow[4:]) if ow.startswith("rut:") else ""


def puede_verla(e: Encuesta, owner_key: str) -> bool:
    """Lista blanca: si la encuesta nombra RUT, solo esos la ven."""
    permitidos = [x for x in (e.solo_ruts or []) if x]
    if not permitidos:
        return True
    return _rut_de_owner(owner_key) in {_norm_rut(x) for x in permitidos}


def _dict(db: Session, e: Encuesta, owner_key: str | None = None, es_docente: bool = False) -> dict:
    """Ojo con `es_docente`: si el resultado está oculto, los conteos NO se envían al
    estudiante. Ocultarlos solo en la pantalla no serviría de nada — bastaría con mirar la
    respuesta de red para saber cómo va la votación."""
    votos = db.query(EncuestaVoto).filter(EncuestaVoto.encuesta_id == e.id).all()
    opciones = list(e.opciones or [])
    conteo = [0] * len(opciones)
    for v in votos:
        if 0 <= int(v.opcion or 0) < len(conteo):
            conteo[int(v.opcion)] += 1
    total = sum(conteo)
    mio = next((v for v in votos if owner_key and v.owner_key == owner_key), None)
    muestra = es_docente or bool(e.ver_resultados)
    ops = []
    for i, t in enumerate(opciones):
        o = {"i": i, "texto": t}
        if muestra:
            # El porcentaje se calcula aquí para que el gráfico no lo reinvente en cada
            # cliente y todos vean exactamente lo mismo.
            o["n"] = conteo[i]
            o["pct"] = (round(conteo[i] * 100 / total) if total else 0)
        ops.append(o)
    return {
        "id": str(e.id), "pregunta": e.pregunta, "anonima": bool(e.anonima),
        "abierta": bool(e.abierta),
        "total": (total if muestra else None),
        "ver_resultados": bool(e.ver_resultados),
        "permite_cambio": bool(e.permite_cambio),
        "mi_voto": (int(mio.opcion) if mio else None),
        "piloto": bool([x for x in (e.solo_ruts or []) if x]),
        "opciones": ops,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def crear(db: Session, silabo: str, pregunta: str, opciones: list, autor: str = "",
          solo_ruts: list | None = None, anonima: bool = True,
          ver_resultados: bool = False, permite_cambio: bool = False) -> dict:
    p = str(pregunta or "").strip()[:300]
    if not p:
        raise unprocessable("Escribe la pregunta de la encuesta.")
    ops = [str(o).strip()[:_MAX_LARGO_OPCION] for o in (opciones or []) if str(o or "").strip()]
    if len(ops) < 2:
        raise unprocessable("Una encuesta necesita al menos dos opciones.")
    if len(ops) > _MAX_OPCIONES:
        raise unprocessable(f"Máximo {_MAX_OPCIONES} opciones: si son más, la gente no las lee.")
    ruts = [_norm_rut(x) for x in (solo_ruts or []) if _norm_rut(x)]
    e = Encuesta(silabo=str(silabo or "").strip().upper()[:12], pregunta=p, opciones=ops,
                 anonima=bool(anonima), abierta=True, solo_ruts=(ruts or None),
                 ver_resultados=bool(ver_resultados), permite_cambio=bool(permite_cambio),
                 creada_por=(str(autor or "").strip()[:120] or None))
    db.add(e); db.commit(); db.refresh(e)
    return _dict(db, e, es_docente=True)


def listar_para(db: Session, silabo: str, owner_key: str | None) -> dict:
    """Las encuestas que ESA persona puede ver, la más nueva primero.

    Si quien pregunta NO se ha identificado, además se informa CUÁNTAS encuestas hay
    esperando identidad — solo el número, nunca la pregunta ni las opciones. Sin ese dato
    la app no tenía forma de invitar a identificarse y el estudiante veía una pantalla
    vacía creyendo que no había nada.
    """
    filas = (db.query(Encuesta)
             .filter(Encuesta.silabo == str(silabo or "").strip().upper())
             .order_by(Encuesta.created_at.desc()).all())
    visibles = [e for e in filas if puede_verla(e, owner_key or "")]
    esperando = 0
    if not owner_key:
        esperando = sum(1 for e in filas if e.abierta and e not in visibles)
    return {"ok": True, "encuestas": [_dict(db, e, owner_key) for e in visibles],
            "requieren_identidad": esperando}


def listar_del_docente(db: Session, silabo: str) -> dict:
    """Todas las del curso, vea quien vea: es el panel de quien las creó."""
    filas = (db.query(Encuesta)
             .filter(Encuesta.silabo == str(silabo or "").strip().upper())
             .order_by(Encuesta.created_at.desc()).all())
    return {"ok": True, "encuestas": [_dict(db, e, es_docente=True) for e in filas]}


def votar(db: Session, encuesta_id, owner_key: str, nombre: str | None, opcion,
          comentario: str | None = None) -> dict:
    e = db.query(Encuesta).filter(Encuesta.id == encuesta_id).first()
    if not e:
        raise not_found("Esa encuesta no existe.")
    if not e.abierta:
        raise conflict("Esta encuesta ya está cerrada.")
    if not puede_verla(e, owner_key):
        raise conflict("Esta encuesta no está disponible para ti.")
    try:
        i = int(opcion)
    except (TypeError, ValueError):
        raise unprocessable("Elige una opción.")
    if not (0 <= i < len(e.opciones or [])):
        raise unprocessable("Esa opción no existe.")

    # Un voto por persona. Por defecto NO se puede cambiar: se responde una vez y queda,
    # que es lo que hace que el resultado sirva para tomar una decisión.
    mio = db.query(EncuestaVoto).filter(
        EncuestaVoto.encuesta_id == e.id, EncuestaVoto.owner_key == owner_key).first()
    txt = (str(comentario or "").strip()[:500] or None)
    if mio and not e.permite_cambio:
        raise conflict("Ya respondiste esta encuesta. Tu respuesta quedó registrada.")
    if mio:
        mio.opcion = i
        if txt:
            mio.comentario = txt
    else:
        db.add(EncuestaVoto(encuesta_id=e.id, owner_key=owner_key,
                            nombre=(None if e.anonima else (nombre or None)),
                            opcion=i, comentario=txt))
    db.commit()
    return _dict(db, e, owner_key)


def cerrar(db: Session, encuesta_id, abierta: bool = False) -> dict:
    e = db.query(Encuesta).filter(Encuesta.id == encuesta_id).first()
    if not e:
        raise not_found("Esa encuesta no existe.")
    e.abierta = bool(abierta)
    db.commit()
    return _dict(db, e, es_docente=True)


def eliminar(db: Session, encuesta_id) -> dict:
    e = db.query(Encuesta).filter(Encuesta.id == encuesta_id).first()
    if not e:
        raise not_found("Esa encuesta no existe.")
    db.query(EncuestaVoto).filter(EncuestaVoto.encuesta_id == e.id).delete(synchronize_session=False)
    db.delete(e); db.commit()
    return {"ok": True}

def editar(db: Session, encuesta_id, pregunta=None, opciones=None, solo_ruts=None,
           ver_resultados=None, permite_cambio=None) -> dict:
    """Corregir una encuesta ya publicada sin perderla.

    Existe porque la alternativa era borrar y volver a crear por una errata. Regla: el
    TEXTO se puede arreglar siempre, pero **no se puede cambiar el número de opciones si
    ya hay votos** — los votos guardan el índice, así que agregar o quitar una movería
    silenciosamente lo que la gente eligió.
    """
    e = db.query(Encuesta).filter(Encuesta.id == encuesta_id).first()
    if not e:
        raise not_found("Esa encuesta no existe.")
    n_votos = db.query(EncuestaVoto).filter(EncuestaVoto.encuesta_id == e.id).count()

    if pregunta is not None:
        p = str(pregunta).strip()[:300]
        if not p:
            raise unprocessable("La pregunta no puede quedar vacía.")
        e.pregunta = p

    if opciones is not None:
        ops = [str(o).strip()[:_MAX_LARGO_OPCION] for o in opciones if str(o or "").strip()]
        if len(ops) < 2:
            raise unprocessable("Una encuesta necesita al menos dos opciones.")
        if len(ops) > _MAX_OPCIONES:
            raise unprocessable(f"Máximo {_MAX_OPCIONES} opciones.")
        if n_votos and len(ops) != len(e.opciones or []):
            raise conflict(
                f"Ya hay {n_votos} voto(s): puedes corregir el texto de las opciones, pero no "
                "agregar ni quitar, porque cambiaría lo que esas personas eligieron.")
        e.opciones = ops

    if solo_ruts is not None:
        ruts = [_norm_rut(x) for x in solo_ruts if _norm_rut(x)]
        e.solo_ruts = (ruts or None)

    db.commit(); db.refresh(e)
    return _dict(db, e, es_docente=True)
