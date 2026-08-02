"""
Reuniones / reservas nativas (v2.0 · estilo Bookings, keyless).

Flujo: el anfitrión publica ventanas semanales → código público + enlace. El invitado abre el enlace,
ve los huecos LIBRES de los próximos N días y reserva uno → cita con sala de video Jitsi (sin llaves)
+ archivo .ics. Todo queda en la agenda de ambos.
"""
from __future__ import annotations

import datetime as _dt
import re
import secrets
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import not_found, unprocessable
from app.models.reunion import Disponibilidad, Reserva

_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CL_OFFSET = _dt.timedelta(hours=-4)   # aprox. horario de Chile (para no ofrecer huecos ya pasados hoy)


def _now_cl() -> _dt.datetime:
    return _dt.datetime.utcnow() + _CL_OFFSET


def _min(hhmm: str) -> int:
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(hhmm or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else -1


def _hhmm(mins: int) -> str:
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _norm_hora(v) -> str:
    s = re.sub(r"[^0-9:]", "", str(v or ""))
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", s)
    if not m:
        return ""
    hh, mm = int(m.group(1)), int(m.group(2))
    return f"{hh:02d}:{mm:02d}" if hh < 24 and mm < 60 else ""


def _gen_code(db: Session) -> str:
    for _ in range(30):
        c = "".join(secrets.choice(_ALFABETO) for _ in range(6))
        if not db.query(Disponibilidad).filter(Disponibilidad.code == c).first():
            return c
    return "".join(secrets.choice(_ALFABETO) for _ in range(9))


def _video_url(code: str, fecha: str, inicio: str) -> str:
    room = f"EvalysRuni-{code}-{fecha.replace('-', '')}{inicio.replace(':', '')}"
    return f"https://meet.jit.si/{room}"


def _disp_dict(d: Disponibilidad) -> dict:
    return {"code": d.code, "anfitrion": d.anfitrion, "titulo": d.titulo, "duracion": d.duracion,
            "ventanas": d.ventanas or [], "vigencia_dias": d.vigencia_dias, "video": bool(d.video),
            "lugar": d.lugar, "activo": bool(d.activo), "color": d.color or "#7cc6ff"}


def _reserva_dict(r: Reserva, d: Disponibilidad | None = None) -> dict:
    out = {"id": str(r.id), "fecha": r.fecha, "inicio": r.inicio, "fin": r.fin,
           "invitado": r.invitado, "contacto": r.invitado_contacto, "nota": r.nota,
           "video_url": r.video_url, "estado": r.estado}
    if d is not None:
        out.update({"titulo": d.titulo, "anfitrion": d.anfitrion, "code": d.code,
                    "lugar": d.lugar, "color": d.color or "#7cc6ff"})
    return out


# ── Anfitrión ──────────────────────────────────────────────────────────────────
def crear(db: Session, owner_key: str, anfitrion: str, payload: dict) -> dict:
    p = payload or {}
    ventanas = []
    for v in (p.get("ventanas") or []):
        try:
            dia = int(v.get("dia"))
        except (TypeError, ValueError):
            continue
        ini, fin = _norm_hora(v.get("inicio")), _norm_hora(v.get("fin"))
        if 0 <= dia <= 6 and ini and fin and _min(fin) > _min(ini):
            ventanas.append({"dia": dia, "inicio": ini, "fin": fin})
    if not ventanas:
        raise unprocessable("Agrega al menos una ventana horaria (día + desde/hasta).")
    dur = int(p.get("duracion") or 30)
    dur = dur if dur in (15, 20, 30, 45, 60, 90) else 30
    d = Disponibilidad(
        code=_gen_code(db), owner_key=owner_key,
        anfitrion=str(anfitrion or p.get("anfitrion") or "Anfitrión").strip()[:120],
        titulo=str(p.get("titulo") or "Reunión").strip()[:160], duracion=dur,
        ventanas=ventanas, vigencia_dias=min(max(int(p.get("vigencia_dias") or 21), 1), 60),
        video=bool(p.get("video", True)), lugar=(str(p.get("lugar") or "").strip()[:160] or None),
        color=(p.get("color") or "#7cc6ff"))
    db.add(d); db.commit()
    return {"ok": True, "disponibilidad": _disp_dict(d)}


def mias(db: Session, owner_key: str) -> dict:
    ds = db.query(Disponibilidad).filter(Disponibilidad.owner_key == owner_key).all()
    out = []
    for d in ds:
        rs = db.query(Reserva).filter(Reserva.disponibilidad_id == d.id,
                                      Reserva.estado == "confirmada").all()
        item = _disp_dict(d)
        item["reservas"] = sorted([_reserva_dict(r) for r in rs], key=lambda x: (x["fecha"], x["inicio"]))
        out.append(item)
    return {"ok": True, "disponibilidades": out}


def eliminar(db: Session, owner_key: str, code: str) -> dict:
    d = db.query(Disponibilidad).filter(Disponibilidad.code == str(code).upper(),
                                        Disponibilidad.owner_key == owner_key).first()
    if not d:
        raise not_found("Disponibilidad no encontrada.")
    db.query(Reserva).filter(Reserva.disponibilidad_id == d.id).delete(synchronize_session=False)
    db.delete(d); db.commit()
    return {"ok": True}


# ── Página pública del invitado ─────────────────────────────────────────────────
def _reservados(db: Session, disp_id) -> set:
    rs = db.query(Reserva).filter(Reserva.disponibilidad_id == disp_id,
                                  Reserva.estado == "confirmada").all()
    return {(r.fecha, r.inicio) for r in rs}


def publica(db: Session, code: str) -> dict:
    d = db.query(Disponibilidad).filter(Disponibilidad.code == str(code).upper()).first()
    if not d or not d.activo:
        return {"ok": False, "motivo": "no_disponible"}
    ocupados = _reservados(db, d.id)
    ahora = _now_cl()
    hoy = ahora.date()
    por_dia = {}
    for i in range(0, d.vigencia_dias + 1):
        fecha = hoy + _dt.timedelta(days=i)
        wd = fecha.weekday()  # Lunes=0
        fstr = fecha.isoformat()
        for v in (d.ventanas or []):
            if int(v.get("dia", -1)) != wd:
                continue
            ini, fin = _min(v["inicio"]), _min(v["fin"])
            t = ini
            while t + d.duracion <= fin:
                hh = _hhmm(t)
                # no ofrecer huecos ya pasados hoy
                if not (i == 0 and t <= (ahora.hour * 60 + ahora.minute)):
                    if (fstr, hh) not in ocupados:
                        por_dia.setdefault(fstr, []).append({"inicio": hh, "fin": _hhmm(t + d.duracion)})
                t += d.duracion
    dias = [{"fecha": f, "slots": s} for f, s in sorted(por_dia.items()) if s]
    return {"ok": True, "disponibilidad": _disp_dict(d), "dias": dias}


def reservar(db: Session, code: str, payload: dict) -> dict:
    p = payload or {}
    d = db.query(Disponibilidad).filter(Disponibilidad.code == str(code).upper()).first()
    if not d or not d.activo:
        raise not_found("Esta agenda ya no está disponible.")
    fecha = str(p.get("fecha") or "")[:10]
    inicio = _norm_hora(p.get("inicio"))
    invitado = str(p.get("invitado") or "").strip()[:120]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", fecha) or not inicio or not invitado:
        raise unprocessable("Faltan datos: elige un horario y escribe tu nombre.")
    # validar que el hueco pertenece a una ventana y sigue libre
    try:
        wd = _dt.date.fromisoformat(fecha).weekday()
    except ValueError:
        raise unprocessable("Fecha inválida.")
    ini = _min(inicio)
    valido = any(int(v.get("dia", -1)) == wd and _min(v["inicio"]) <= ini
                 and ini + d.duracion <= _min(v["fin"]) for v in (d.ventanas or []))
    if not valido:
        raise unprocessable("Ese horario no está disponible.")
    if (fecha, inicio) in _reservados(db, d.id):
        raise unprocessable("Alguien acaba de tomar ese horario. Elige otro, porfa.")
    fin = _hhmm(ini + d.duracion)
    video = _video_url(d.code, fecha, inicio) if d.video else None
    r = Reserva(disponibilidad_id=d.id, fecha=fecha, inicio=inicio, fin=fin, invitado=invitado,
                invitado_contacto=(str(p.get("contacto") or "").strip()[:160] or None),
                invitado_owner_key=(str(p.get("owner_key") or "").strip()[:80] or None),
                nota=(str(p.get("nota") or "").strip()[:300] or None), video_url=video)
    db.add(r); db.commit()
    return {"ok": True, "reserva": _reserva_dict(r, d), "ics": _ics(r, d)}


# ── Agenda del alumno (como anfitrión y como invitado) ──────────────────────────
def de_alumno(db: Session, owner_key: str) -> dict:
    mias_ids = {d.id: d for d in db.query(Disponibilidad).filter(Disponibilidad.owner_key == owner_key).all()}
    como_anfitrion = []
    if mias_ids:
        rs = db.query(Reserva).filter(Reserva.disponibilidad_id.in_(list(mias_ids.keys())),
                                      Reserva.estado == "confirmada").all()
        for r in rs:
            item = _reserva_dict(r, mias_ids.get(r.disponibilidad_id))
            item["rol"] = "anfitrion"
            como_anfitrion.append(item)
    como_invitado = []
    ri = db.query(Reserva).filter(Reserva.invitado_owner_key == owner_key,
                                  Reserva.estado == "confirmada").all()
    for r in ri:
        d = db.query(Disponibilidad).filter(Disponibilidad.id == r.disponibilidad_id).first()
        item = _reserva_dict(r, d)
        item["rol"] = "invitado"
        como_invitado.append(item)
    todas = sorted(como_anfitrion + como_invitado, key=lambda x: (x["fecha"], x["inicio"]))
    return {"ok": True, "reuniones": todas}


def cancelar(db: Session, owner_key: str, reserva_id) -> dict:
    try:
        rid = _uuid.UUID(str(reserva_id))
    except (ValueError, TypeError):
        raise not_found("Reserva no válida.")
    r = db.query(Reserva).filter(Reserva.id == rid).first()
    if not r:
        raise not_found("Reserva no encontrada.")
    d = db.query(Disponibilidad).filter(Disponibilidad.id == r.disponibilidad_id).first()
    permitido = (r.invitado_owner_key == owner_key) or (d and d.owner_key == owner_key)
    if not permitido:
        raise not_found("No puedes cancelar esta reunión.")
    r.estado = "cancelada"; db.commit()
    return {"ok": True}


def _ics(r: Reserva, d: Disponibilidad) -> str:
    def dt(fecha, hhmm):
        return fecha.replace("-", "") + "T" + hhmm.replace(":", "") + "00"
    stamp = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    loc = r.video_url or (d.lugar or "")
    desc = f"Reunión con {d.anfitrion}."
    if r.video_url:
        desc += f"\\nVideollamada: {r.video_url}"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Evalys//Runi//ES", "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT", f"UID:{r.id}@evalys.cl", f"DTSTAMP:{stamp}",
        f"DTSTART:{dt(r.fecha, r.inicio)}", f"DTEND:{dt(r.fecha, r.fin)}",
        f"SUMMARY:{d.titulo}", f"DESCRIPTION:{desc}", f"LOCATION:{loc}",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(lines)
