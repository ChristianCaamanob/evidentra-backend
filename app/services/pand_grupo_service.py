"""
Grupos de la Pandilla: crear, unirse por código (QR), ver y salir.

Quién eres se resuelve SIEMPRE con el token de identidad que ya emite la Pandilla al
identificarte contra la nómina del curso; aquí no se acepta un owner_key suelto por el
cuerpo de la petición, porque eso dejaría entrar a cualquiera diciendo ser otro.
"""
from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.models.pand_grupo import PandGrupo, PandGrupoMiembro

# Sin caracteres ambiguos: quien no pueda escanear tendrá que teclearlo.
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_MAX_MIEMBROS = 12          # un grupo de trabajo, no un curso entero
_MAX_POR_ALUMNO = 4         # nadie necesita más de unos pocos grupos a la vez


def _codigo(db: Session) -> str:
    for _ in range(40):
        c = "".join(secrets.choice(_ALFABETO) for _ in range(6))
        if not db.query(PandGrupo).filter(PandGrupo.codigo == c).first():
            return c
    raise conflict("No se pudo generar un código de grupo único.")


def _grupo(db: Session, codigo: str) -> PandGrupo:
    g = db.query(PandGrupo).filter(PandGrupo.codigo == str(codigo or "").strip().upper()).first()
    if not g:
        raise not_found("Ese grupo no existe. Revisa el código o pide el QR de nuevo.")
    return g


def _dict(db: Session, g: PandGrupo, owner_key: str | None = None) -> dict:
    miembros = (db.query(PandGrupoMiembro)
                .filter(PandGrupoMiembro.grupo_id == g.id)
                .order_by(PandGrupoMiembro.created_at.asc()).all())
    return {
        "codigo": g.codigo, "nombre": g.nombre, "curso": g.curso, "emoji": g.emoji,
        "abierto": bool(g.abierto),
        "soy_creador": bool(owner_key and owner_key == g.creador_owner),
        "soy_miembro": bool(owner_key and any(m.owner_key == owner_key for m in miembros)),
        "n_miembros": len(miembros),
        "cupo": _MAX_MIEMBROS,
        "miembros": [{"nombre": m.nombre or "Compañero/a", "char": m.char,
                      "es_creador": m.owner_key == g.creador_owner,
                      "soy_yo": bool(owner_key and m.owner_key == owner_key)} for m in miembros],
    }


def crear(db: Session, curso: str, owner_key: str, nombre_alumno: str | None,
          nombre: str = "", char: str | None = None, emoji: str | None = None) -> dict:
    mios = (db.query(PandGrupoMiembro)
            .join(PandGrupo, PandGrupo.id == PandGrupoMiembro.grupo_id)
            .filter(PandGrupoMiembro.owner_key == owner_key, PandGrupo.curso == curso).count())
    if mios >= _MAX_POR_ALUMNO:
        raise conflict(f"Ya estás en {mios} grupos de este curso. Sal de alguno para crear otro.")

    g = PandGrupo(curso=curso, codigo=_codigo(db), creador_owner=owner_key,
                  nombre=(str(nombre or "").strip()[:60] or "Mi grupo"),
                  emoji=(str(emoji or "").strip()[:40] or None))
    db.add(g)
    db.flush()
    db.add(PandGrupoMiembro(grupo_id=g.id, owner_key=owner_key,
                            nombre=nombre_alumno, char=char))
    db.commit()
    db.refresh(g)
    return _dict(db, g, owner_key)


def unirse(db: Session, codigo: str, owner_key: str, nombre_alumno: str | None,
           curso: str, char: str | None = None) -> dict:
    g = _grupo(db, codigo)
    # Un grupo pertenece a un curso: el QR de otro ramo no sirve, aunque el código exista.
    if g.curso != curso:
        raise conflict("Ese grupo es de otro curso.")
    ya = db.query(PandGrupoMiembro).filter(
        PandGrupoMiembro.grupo_id == g.id, PandGrupoMiembro.owner_key == owner_key).first()
    if ya:
        # Volver a escanear el QR es lo más natural del mundo: se reentra, no se duplica.
        if nombre_alumno and not ya.nombre:
            ya.nombre = nombre_alumno
            db.commit()
        return _dict(db, g, owner_key)
    if not g.abierto:
        raise conflict("Ese grupo ya está cerrado por quien lo creó.")
    n = db.query(PandGrupoMiembro).filter(PandGrupoMiembro.grupo_id == g.id).count()
    if n >= _MAX_MIEMBROS:
        raise conflict(f"El grupo ya está completo ({_MAX_MIEMBROS} integrantes).")
    db.add(PandGrupoMiembro(grupo_id=g.id, owner_key=owner_key, nombre=nombre_alumno, char=char))
    db.commit()
    return _dict(db, g, owner_key)


def ver(db: Session, codigo: str, owner_key: str | None = None) -> dict:
    return _dict(db, _grupo(db, codigo), owner_key)


def mis_grupos(db: Session, curso: str, owner_key: str) -> dict:
    filas = (db.query(PandGrupo)
             .join(PandGrupoMiembro, PandGrupo.id == PandGrupoMiembro.grupo_id)
             .filter(PandGrupoMiembro.owner_key == owner_key, PandGrupo.curso == curso)
             .order_by(PandGrupo.created_at.desc()).all())
    return {"ok": True, "grupos": [_dict(db, g, owner_key) for g in filas]}


def salir(db: Session, codigo: str, owner_key: str) -> dict:
    g = _grupo(db, codigo)
    m = db.query(PandGrupoMiembro).filter(
        PandGrupoMiembro.grupo_id == g.id, PandGrupoMiembro.owner_key == owner_key).first()
    if not m:
        raise not_found("No estás en ese grupo.")
    db.delete(m)
    db.flush()
    # Si se fue el último, el grupo deja de existir: no se acumulan grupos fantasma.
    quedan = db.query(PandGrupoMiembro).filter(PandGrupoMiembro.grupo_id == g.id).count()
    disuelto = False
    if quedan == 0:
        db.delete(g)
        disuelto = True
    db.commit()
    return {"ok": True, "disuelto": disuelto}


def cerrar(db: Session, codigo: str, owner_key: str, abierto: bool) -> dict:
    """Quien creó el grupo decide si sigue aceptando gente."""
    g = _grupo(db, codigo)
    if g.creador_owner != owner_key:
        raise conflict("Solo quien creó el grupo puede abrirlo o cerrarlo.")
    g.abierto = bool(abierto)
    db.commit()
    return _dict(db, g, owner_key)

# ── Lo que se puede HACER dentro del grupo ────────────────────────────────────────────
# El grupo era solo una lista de integrantes: nada de la plataforma colgaba de él. Estas
# funciones son el enganche para que el equipo tenga vida propia (chat, sala, meta).

def es_miembro(db: Session, codigo: str, owner_key: str) -> PandGrupo:
    """Devuelve el grupo si quien pregunta pertenece a él; si no, corta.

    Es la guarda de TODO lo de adentro: tener el código (o el QR) alcanza para PEDIR
    entrar, no para leer lo que el grupo conversa.
    """
    g = _grupo(db, codigo)
    m = db.query(PandGrupoMiembro).filter(
        PandGrupoMiembro.grupo_id == g.id, PandGrupoMiembro.owner_key == owner_key).first()
    if not m:
        raise conflict("No perteneces a ese grupo.")
    return g


def scope_chat(codigo: str) -> str:
    """Clave de conversación del grupo, distinta de la del curso.

    El chat guarda su ámbito en una sola columna (`curso`): el del curso usa el id del
    curso y el del grupo usa 'g:<codigo>'. Así el mismo motor —y la misma poda de 7
    días— sirve para los dos sin duplicar tablas ni consultas.
    """
    return "g:" + str(codigo or "").strip().upper()


def listar_del_curso(db: Session, curso: str) -> dict:
    """Los grupos de un curso, para que el DOCENTE vea cómo se organizó su clase.

    Solo la composición (quién con quién), nunca lo que conversan dentro.
    """
    filas = db.query(PandGrupo).filter(PandGrupo.curso == curso).order_by(
        PandGrupo.created_at.desc()).all()
    grupos = []
    for g in filas:
        ms = db.query(PandGrupoMiembro).filter(PandGrupoMiembro.grupo_id == g.id).order_by(
            PandGrupoMiembro.created_at.asc()).all()
        grupos.append({"codigo": g.codigo, "nombre": g.nombre, "abierto": bool(g.abierto),
                       "creado_at": g.created_at.isoformat() if g.created_at else None,
                       "n_miembros": len(ms),
                       "integrantes": [(m.nombre or "Sin nombre") for m in ms]})
    en_grupo = {m.owner_key for g in filas for m in
                db.query(PandGrupoMiembro).filter(PandGrupoMiembro.grupo_id == g.id).all()}
    return {"ok": True, "grupos": grupos,
            "resumen": {"n_grupos": len(grupos), "n_estudiantes_en_grupo": len(en_grupo)}}
