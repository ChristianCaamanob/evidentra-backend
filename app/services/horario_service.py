"""
Horario mágico (v2.0): foto/PDF/texto del horario → bloques estructurados (visión de Claude) → agenda.

Flujo: (1) `extraer` manda la(s) imagen(es) o el texto a Claude con un prompt estricto y devuelve bloques
normalizados + avisos (choques/dudas) para que el alumno confirme campo por campo; (2) `guardar` persiste
los bloques confirmados (reemplaza los del alumno); (3) `obtener` los lee. Identidad: cuenta (sid) o device.
"""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.core.errors import unprocessable
from app.models.agenda import AgendaBloque

_DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
_DIA_ALIAS = {
    "lun": 0, "lu": 0, "mon": 0, "l": 0,
    "mar": 1, "ma": 1, "tue": 1, "k": 1,
    "mie": 2, "mié": 2, "mi": 2, "wed": 2, "x": 2, "w": 2,
    "jue": 3, "ju": 3, "thu": 3, "j": 3,
    "vie": 4, "vi": 4, "fri": 4, "v": 4,
    "sab": 5, "sá": 5, "sa": 5, "sat": 5, "s": 5,
    "dom": 6, "do": 6, "sun": 6, "d": 6,
}
_COLORES = ["#34e5a8", "#f0954a", "#9d7cff", "#4da5ff", "#ff6b9d", "#f6bd60", "#31d6cc"]


def owner_key(db: Session, device_id: str, sesion: str = "") -> str:
    if sesion:
        try:
            from app.services import alumno_auth as aa
            info = aa.sesion_desde_token(db, sesion)
            if info and info.get("sid"):
                return "sid:" + str(info["sid"])
        except Exception:  # noqa: BLE001
            pass
    dev = re.sub(r"[^0-9a-zA-Z_-]", "", str(device_id or "anon"))[:64] or "anon"
    return "dev:" + dev


def _json(txt: str):
    t = str(txt or "")
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        return json.loads(t[i:j + 1])
    except Exception:  # noqa: BLE001
        # segundo intento: recorta comas colgantes simples
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", t[i:j + 1]))
        except Exception:  # noqa: BLE001
            return {}


def _norm_dia(v) -> int | None:
    s = str(v or "").strip().lower()
    if s.isdigit():
        n = int(s)
        return n if 0 <= n <= 6 else None
    s = s.replace("é", "e").replace("á", "a").replace("í", "i").replace("ó", "o").replace("ú", "u")
    if s in _DIAS:
        return _DIAS.index(s)
    for pre, n in _DIA_ALIAS.items():
        if s.startswith(pre):
            return n
    return None


def _norm_hora(v) -> str:
    s = re.sub(r"[^0-9:]", "", str(v or ""))
    if not s:
        return ""
    if ":" not in s:
        s = (s[:-2] + ":" + s[-2:]) if len(s) >= 3 else s
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", s)
    if not m:
        return ""
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 23 or mm > 59:
        return ""
    return f"{hh:02d}:{mm:02d}"


_SYSTEM = (
    "Eres un extractor experto de HORARIOS académicos. Recibes la foto o el texto del horario de un "
    "estudiante y devuelves EXCLUSIVAMENTE un JSON válido (sin texto adicional, sin markdown). "
    "No inventes datos: si un campo no aparece, déjalo vacío. Respeta el formato de 24 horas."
)
_USER = (
    "Extrae TODOS los bloques de clase/actividad del horario. Devuelve este JSON exacto:\n"
    '{"bloques":[{"asignatura":"","dia":"Lun|Mar|Mie|Jue|Vie|Sab|Dom","inicio":"HH:MM",'
    '"fin":"HH:MM","sala":"","docente":"","tipo":"clase|lab|ayudantia|otro"}],"avisos":["texto corto"]}\n'
    "Reglas: un bloque por franja y día (si una clase se repite en varios días, crea un bloque por día). "
    "Usa 24h (ej 14:30). En 'avisos' incluye choques de horario detectados o campos dudosos. "
    "Si el texto/imagen no parece un horario, devuelve bloques:[] y un aviso explicándolo."
)


def extraer(imagenes: list | None, texto: str = "") -> dict:
    imagenes = [im for im in (imagenes or []) if isinstance(im, dict) and im.get("data")][:6] or None
    if not imagenes and not (texto or "").strip():
        raise unprocessable("Envía una foto de tu horario o pégalo como texto.")
    try:
        from app.services import correccion_experta_service as ce
        if imagenes:
            crudo = ce._llamar_anthropic_vision(_SYSTEM, _USER, imagenes, max_tokens=2200)
        else:
            crudo = ce._llamar_anthropic(_SYSTEM, _USER + "\n\nHORARIO (texto):\n" + texto[:8000], max_tokens=2200)
    except Exception as e:  # noqa: BLE001
        raise unprocessable(f"No pude leer el horario ahora: {e}")

    data = _json(crudo)
    brutos = data.get("bloques") if isinstance(data, dict) else None
    avisos = [str(a)[:160] for a in (data.get("avisos") or [])][:8] if isinstance(data, dict) else []
    out = []
    ci = 0
    asig_color = {}
    for b in (brutos or []):
        if not isinstance(b, dict):
            continue
        dia = _norm_dia(b.get("dia"))
        ini = _norm_hora(b.get("inicio"))
        fin = _norm_hora(b.get("fin"))
        asig = str(b.get("asignatura") or "").strip()[:160]
        if dia is None or not ini or not asig:
            continue
        if asig not in asig_color:
            asig_color[asig] = _COLORES[ci % len(_COLORES)]; ci += 1
        out.append({
            "asignatura": asig, "dia": dia, "inicio": ini, "fin": fin or ini,
            "sala": str(b.get("sala") or "").strip()[:80] or None,
            "docente": str(b.get("docente") or "").strip()[:120] or None,
            "tipo": (str(b.get("tipo") or "clase").strip().lower()[:30]) or "clase",
            "color": asig_color[asig],
        })
    out.sort(key=lambda x: (x["dia"], x["inicio"]))
    # Choques (mismo día con solape) → aviso adicional si el modelo no lo detectó.
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            if out[i]["dia"] == out[j]["dia"] and out[i]["fin"] > out[j]["inicio"] and out[i]["inicio"] < out[j]["fin"]:
                aviso = f"Posible choque: {out[i]['asignatura']} y {out[j]['asignatura']} el {_DIAS[out[i]['dia']]}."
                if aviso not in avisos:
                    avisos.append(aviso)
    return {"ok": True, "bloques": out, "avisos": avisos, "total": len(out)}


def guardar(db: Session, owner: str, bloques: list) -> dict:
    db.query(AgendaBloque).filter(AgendaBloque.owner_key == owner).delete()
    n = 0
    for b in (bloques or [])[:120]:
        if not isinstance(b, dict):
            continue
        dia = _norm_dia(b.get("dia"))
        ini = _norm_hora(b.get("inicio"))
        asig = str(b.get("asignatura") or "").strip()[:160]
        if dia is None or not ini or not asig:
            continue
        db.add(AgendaBloque(
            owner_key=owner, asignatura=asig, dia=dia, inicio=ini,
            fin=_norm_hora(b.get("fin")) or ini, sala=str(b.get("sala") or "").strip()[:80] or None,
            docente=str(b.get("docente") or "").strip()[:120] or None,
            tipo=str(b.get("tipo") or "clase").strip().lower()[:30] or "clase",
            color=str(b.get("color") or "").strip()[:16] or None, recurrencia="semanal"))
        n += 1
    db.commit()
    return {"ok": True, "guardados": n}


def _b(r: AgendaBloque) -> dict:
    return {"id": str(r.id), "asignatura": r.asignatura, "dia": r.dia, "inicio": r.inicio,
            "fin": r.fin, "sala": r.sala, "docente": r.docente, "tipo": r.tipo, "color": r.color}


def obtener(db: Session, owner: str) -> dict:
    filas = db.query(AgendaBloque).filter(AgendaBloque.owner_key == owner).all()
    bloques = sorted([_b(r) for r in filas], key=lambda x: (x["dia"], x["inicio"]))
    return {"ok": True, "bloques": bloques, "total": len(bloques)}
