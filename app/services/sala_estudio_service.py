"""Sala de estudio en vivo · lógica (Runi asiste al grupo + premia el aprendizaje + da cuenta del progreso).

Reutiliza el agente de sílabo del curso (silabo_service) para el CONTEXTO y para la respuesta de Runi. En la
sala compartida Runi solo responde lo ACADÉMICO; lo reservado del protocolo (salud/denuncia/justificación/
evaluativa/derivación) NO se expone: Runi redirige al espacio personal. Sin cuentas: identidad = nombre de trato.
"""
from __future__ import annotations

import secrets
import time

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import not_found, conflict
from app.models.sala_estudio import SalaEstudio, SalaMensaje
from app.services import silabo_service as sil

_ALFA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_PRESENCIA_SEG = 35          # "en línea" si dio señal en los últimos 35 s
_PTS_APORTE = 10             # puntos por consulta académica respondida
_PTS_TEMA_NUEVO = 15         # bonus por abrir un tema nuevo para el grupo
# Runi NO expone en la sala compartida lo reservado del protocolo → redirige al espacio personal.
_TIPOS_RESERVADOS = ("personal_salud", "denuncia", "justificacion", "evaluativa", "riesgo_clinico",
                     "fuera_corpus", "extraccion", "solicitud_humana")


def _ahora() -> int:
    return int(time.time())


def _codigo(db: Session) -> str:
    for _ in range(30):
        c = "".join(secrets.choice(_ALFA) for _ in range(6))
        if not db.query(SalaEstudio).filter(SalaEstudio.codigo == c).first():
            return c
    return "".join(secrets.choice(_ALFA) for _ in range(8))


def crear_sala(db: Session, codigo_silabo: str, titulo: str, alias: str | None, device_id: str | None) -> dict:
    a = sil.agente_por_codigo(db, codigo_silabo)             # el curso al que pertenece la sala
    s = SalaEstudio(agente_id=a.id, codigo=_codigo(db),
                    titulo=(titulo or "Sala de estudio").strip()[:160] or "Sala de estudio",
                    creador_alias=(alias or None), activa=True,
                    participantes={}, meta={"puntos_grupo": 0, "temas": [], "hitos": []})
    db.add(s); db.flush()
    _tocar(s, device_id, alias)
    db.add(SalaMensaje(sala_id=s.id, rol="sistema",
                       texto=("¡Sala abierta! 🦊 Invita a tus compañeros con el código. Pregúntenme lo que "
                              "estén estudiando: yo los guío y les voy dando puntos a medida que avanzan.")))
    db.commit(); db.refresh(s)
    return _sala_dict(s, a)


def unirse(db: Session, codigo: str, alias: str | None, device_id: str | None) -> dict:
    s = _por_codigo(db, codigo)
    if not s.activa:
        raise conflict("Esta sala de estudio ya se cerró.")
    nuevo = not (s.participantes or {}).get(str(device_id or ""))
    _tocar(s, device_id, alias)
    if nuevo and device_id:
        db.add(SalaMensaje(sala_id=s.id, rol="sistema", texto=((alias or "Alguien") + " se unió a la sala. 👋")))
    db.commit(); db.refresh(s)
    return _sala_dict(s, sil_agente(db, s), incluir_mensajes=True)


def postear(db: Session, codigo: str, alias: str | None, device_id: str | None, texto: str) -> dict:
    s = _por_codigo(db, codigo)
    if not s.activa:
        raise conflict("Esta sala de estudio ya se cerró.")
    texto = (texto or "").strip()
    if len(texto) < 1:
        raise conflict("Escribe algo para tus compañeros.")
    texto = texto[:1000]
    _tocar(s, device_id, alias)
    db.add(SalaMensaje(sala_id=s.id, rol="alumno", alias=(alias or None), device_id=(device_id or None), texto=texto))
    db.flush()

    a = sil_agente(db, s)
    # Runi responde SOLO lo académico; historial = las últimas vueltas de la sala (memoria conversacional grupal).
    hist = _historial_sala(db, s)
    try:
        tipo, resp, _cat, _urg, necesita, _cita, tema, _fuente, _ev = sil._clasificar_y_responder(
            a, texto, intentos=0, historial=hist)
    except Exception:  # noqa: BLE001
        tipo, resp, necesita, tema = "conceptual", None, False, None

    reservado = (tipo in _TIPOS_RESERVADOS) or necesita
    if reservado:
        db.add(SalaMensaje(sala_id=s.id, rol="runi", tema=None,
                           texto=("Eso mejor lo vemos en tu espacio personal conmigo 🦊 — ahí te ayudo bien y con "
                                  "reserva. Aquí sigamos con lo que están estudiando en grupo.")))
    else:
        db.add(SalaMensaje(sala_id=s.id, rol="runi", tema=(tema or None),
                           texto=(resp or "Cuéntame un poco más para ayudarte bien.")))
        _premiar(s, device_id, alias, tema)                 # puntos con significado (aprendizaje real)
    flag_modified(s, "participantes"); flag_modified(s, "meta")
    db.commit(); db.refresh(s)
    return _sala_dict(s, a, incluir_mensajes=True)


def estado(db: Session, codigo: str, device_id: str | None = None, alias: str | None = None) -> dict:
    s = _por_codigo(db, codigo)
    if device_id:
        _tocar(s, device_id, alias); flag_modified(s, "participantes"); db.commit(); db.refresh(s)
    return _sala_dict(s, sil_agente(db, s), incluir_mensajes=True)


def cerrar(db: Session, codigo: str) -> dict:
    s = _por_codigo(db, codigo)
    s.activa = False
    db.add(SalaMensaje(sala_id=s.id, rol="sistema", texto="La sala se cerró. ¡Buen trabajo en equipo! 🎉"))
    db.commit(); db.refresh(s)
    return _sala_dict(s, sil_agente(db, s), incluir_mensajes=True)


# ── helpers ──────────────────────────────────────────────────────────────────────────
def _por_codigo(db: Session, codigo: str) -> SalaEstudio:
    s = db.query(SalaEstudio).filter(SalaEstudio.codigo == str(codigo).upper()).first()
    if not s:
        raise not_found("Sala de estudio no encontrada.")
    return s


def sil_agente(db: Session, s: SalaEstudio):
    from app.models.silabo import SilaboAgente
    return db.query(SilaboAgente).filter(SilaboAgente.id == s.agente_id).first()


def _course_id(db, s):
    a = sil_agente(db, s)
    return getattr(a, "course_id", None)


def _tocar(s: SalaEstudio, device_id, alias) -> None:
    """Registra presencia + alias del participante (sin PII); crea su registro si es nuevo."""
    if not device_id:
        return
    p = s.participantes or {}
    d = p.get(str(device_id)) or {"alias": (alias or "Anónimo"), "puntos": 0, "aportes": 0}
    if alias:
        d["alias"] = alias[:80]
    d["ultimo_ts"] = _ahora()
    p[str(device_id)] = d
    s.participantes = p


def _premiar(s: SalaEstudio, device_id, alias, tema) -> None:
    meta = s.meta or {"puntos_grupo": 0, "temas": [], "hitos": []}
    pts = _PTS_APORTE
    temas = meta.get("temas") or []
    if tema and tema not in temas:
        temas.append(tema); pts += _PTS_TEMA_NUEVO
    meta["temas"] = temas[:200]
    meta["puntos_grupo"] = int(meta.get("puntos_grupo", 0)) + pts
    # hitos con significado (aprendizaje conjunto, no monedas vacías)
    hitos = set(meta.get("hitos") or [])
    for umbral, nombre in ((3, "Cubrieron 3 temas juntos"), (7, "7 temas en equipo"), (15, "15 temas — ¡crack colectivo!")):
        if len(meta["temas"]) >= umbral and nombre not in hitos:
            hitos.add(nombre)
    meta["hitos"] = sorted(hitos)
    s.meta = meta
    if device_id:
        p = s.participantes or {}
        d = p.get(str(device_id)) or {"alias": (alias or "Anónimo"), "puntos": 0, "aportes": 0}
        d["puntos"] = int(d.get("puntos", 0)) + _PTS_APORTE
        d["aportes"] = int(d.get("aportes", 0)) + 1
        p[str(device_id)] = d
        s.participantes = p


def _historial_sala(db: Session, s: SalaEstudio, n: int = 6) -> str:
    msgs = (db.query(SalaMensaje).filter(SalaMensaje.sala_id == s.id, SalaMensaje.rol != "sistema")
            .order_by(SalaMensaje.created_at.desc()).limit(n).all())
    partes = []
    for m in reversed(msgs):
        quien = "Runi" if m.rol == "runi" else (m.alias or "Compañero")
        partes.append(quien + ": " + (m.texto or "")[:280])
    return "\n".join(partes)[:2500]


def _sala_dict(s: SalaEstudio, a=None, incluir_mensajes: bool = False) -> dict:
    ahora = _ahora()
    parts = s.participantes or {}
    lista = sorted(
        [{"alias": v.get("alias", "Anónimo"), "puntos": int(v.get("puntos", 0)), "aportes": int(v.get("aportes", 0)),
          "en_linea": (ahora - int(v.get("ultimo_ts", 0))) <= _PRESENCIA_SEG} for v in parts.values()],
        key=lambda x: x["puntos"], reverse=True)
    meta = s.meta or {}
    out = {"codigo": s.codigo, "titulo": s.titulo, "activa": s.activa,
           "curso": getattr(a, "nombre_curso", None) if a else None,
           "creador_alias": s.creador_alias,
           "participantes": lista, "en_linea": sum(1 for p in lista if p["en_linea"]),
           "puntos_grupo": int(meta.get("puntos_grupo", 0)), "temas": meta.get("temas") or [],
           "hitos": meta.get("hitos") or []}
    if incluir_mensajes:
        msgs = sorted(s.mensajes, key=lambda m: (m.created_at.isoformat() if getattr(m, "created_at", None) else ""))
        out["mensajes"] = [{"id": str(m.id), "rol": m.rol, "alias": m.alias, "texto": m.texto,
                            "tema": m.tema, "device_id": m.device_id,
                            "fecha": m.created_at.isoformat() if getattr(m, "created_at", None) else None}
                           for m in msgs][-120:]
    return out
