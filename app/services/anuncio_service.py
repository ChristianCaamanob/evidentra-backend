"""
Anuncios del docente — crear (+ push en tiempo real a los suscritos del curso) y listar (bandeja).
"""
from __future__ import annotations

import base64
import datetime as _dt
import re
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import unprocessable, not_found
from app.models.anuncio import Anuncio
from app.services import push_service, silabo_service


_MAX_BYTES = 6 * 1024 * 1024      # el aviso viaja también como push: se acota el adjunto

# Cada cuántos días vuelve a sonar. "unica" = se avisa una vez y queda en la bandeja.
REPETICIONES = {"unica": 0, "diaria": 1, "cada_2_dias": 2, "semanal": 7, "quincenal": 14}
_TOPE_DIAS = 120          # nada se repite más de cuatro meses: un semestre no dura más que eso
_TOPE_VECES = 40          # y nunca más de 40 veces, pase lo que pase con las fechas


def _dict(a: Anuncio) -> dict:
    """El archivo NUNCA viaja en el listado: solo su ficha y el enlace para descargarlo.

    Devolver el base64 en cada anuncio inflaría la bandeja del alumno a megas por nada.
    """
    tiene = bool(getattr(a, "archivo_datos", None))
    rep = getattr(a, "repeticion", "unica") or "unica"
    return {"id": str(a.id), "titulo": a.titulo, "cuerpo": a.cuerpo, "autor": a.autor,
            "repeticion": rep, "recurrente": rep != "unica",
            "repetir_hasta": getattr(a, "repetir_hasta", None),
            "veces_enviado": int(getattr(a, "veces_enviado", 1) or 1),
            "ultimo_envio": getattr(a, "ultimo_envio", None),
            "vigente": _vigente(a),
            "repeticion_texto": _texto_repeticion(a),
            "url": getattr(a, "url", None),
            "archivo_nombre": getattr(a, "archivo_nombre", None) if tiene else None,
            "archivo_mime": getattr(a, "archivo_mime", None) if tiene else None,
            "tamano": int(getattr(a, "tamano", 0) or 0) if tiene else 0,
            "archivo_url": (f"/api/v1/anuncios/{a.id}/archivo" if tiene else None),
            "created_at": a.created_at.isoformat() if a.created_at else None}


def _texto_repeticion(a) -> str:
    """Cómo se le cuenta al docente y al alumno, en una línea."""
    rep = getattr(a, "repeticion", "unica") or "unica"
    if rep == "unica":
        return "Se avisa una vez"
    nombre = {"diaria": "Cada día", "cada_2_dias": "Día por medio",
              "semanal": "Cada semana", "quincenal": "Cada dos semanas"}.get(rep, "Se repite")
    hasta = getattr(a, "repetir_hasta", None)
    return nombre + (f" · hasta el {hasta}" if hasta else "")


def _vigente(a) -> bool:
    """¿Este comunicado todavía tiene que volver a sonar?"""
    if (getattr(a, "repeticion", "unica") or "unica") == "unica":
        return False
    if int(getattr(a, "veces_enviado", 1) or 1) >= _TOPE_VECES:
        return False
    hasta = getattr(a, "repetir_hasta", None)
    if not hasta:
        return False
    try:
        return _dt.date.fromisoformat(hasta[:10]) >= _dt.date.today()
    except (ValueError, TypeError):
        return False


def _leer_recurrencia(p: dict) -> tuple:
    """Valida la recurrencia. Un recurrente SIEMPRE tiene fecha de término.

    Sin fecha de término un aviso se repite hasta que alguien se acuerde de apagarlo, y lo que pasa
    en la práctica es que nadie se acuerda: el alumno lo silencia y deja de mirar los avisos del
    curso. Si no la ponen, se asume un mes.
    """
    rep = str(p.get("repeticion") or "unica").strip().lower()
    if rep not in REPETICIONES:
        raise unprocessable("Repetición no válida.")
    if rep == "unica":
        return "unica", None
    hasta = str(p.get("repetir_hasta") or "").strip()[:10]
    hoy = _dt.date.today()
    try:
        f = _dt.date.fromisoformat(hasta) if hasta else (hoy + _dt.timedelta(days=30))
    except ValueError:
        raise unprocessable("La fecha de término tiene que ser YYYY-MM-DD.")
    if f <= hoy:
        raise unprocessable("La fecha de término tiene que ser posterior a hoy.")
    tope = hoy + _dt.timedelta(days=_TOPE_DIAS)
    if f > tope:
        f = tope                       # se recorta en silencio: nadie necesita un aviso a un año
    return rep, f.isoformat()


def crear(db: Session, course_id, payload: dict, autor: str = "") -> dict:
    p = payload or {}
    titulo = str(p.get("titulo") or "").strip()[:140]
    cuerpo = str(p.get("cuerpo") or "").strip()[:1000]
    if not titulo and not cuerpo:
        raise unprocessable("El anuncio necesita al menos un título o un mensaje.")
    url = str(p.get("url") or "").strip()[:2000] or None
    b64 = p.get("archivo_datos")
    nombre = str(p.get("archivo_nombre") or "").strip()[:200] or None
    mime = str(p.get("archivo_mime") or "").strip()[:100] or None
    datos, tamano = None, 0
    if b64:
        crudo = re.sub(r"^data:[^;]+;base64,", "", str(b64))
        try:
            tamano = len(base64.b64decode(crudo, validate=False))
        except Exception:  # noqa: BLE001
            tamano = int(len(crudo) * 0.75)
        if tamano > _MAX_BYTES:
            raise unprocessable("El archivo supera 6 MB. Comparte un enlace (Drive/web) en su lugar.")
        datos = crudo

    rep, hasta = _leer_recurrencia(p)
    a = Anuncio(course_id=str(course_id), titulo=titulo or "Anuncio del curso",
                cuerpo=cuerpo, autor=(str(autor or "").strip()[:120] or None),
                url=url, archivo_nombre=nombre, archivo_mime=mime,
                archivo_datos=datos, tamano=tamano,
                repeticion=rep, repetir_hasta=hasta, veces_enviado=1,
                ultimo_envio=_dt.date.today().isoformat())
    db.add(a); db.commit()
    # Push en tiempo real a la pantalla bloqueada de los estudiantes suscritos al curso.
    enviados = 0
    try:
        payload_push = {"title": "📣 " + (a.titulo or "Anuncio del curso"),
                        "body": ((a.cuerpo or "")[:380] or a.titulo) + (" 📎" if (datos or url) else ""),
                        "tag": f"anuncio-{a.id}", "url": "/?avisos=1",
                        "requireInteraction": True, "vibrate": [120, 60, 120, 60, 200],
                        "icon": "/runi/icons/icon-192.png", "badge": "/runi/icons/icon-192.png"}
        enviados = push_service.enviar_a_curso(db, course_id, payload_push)
    except Exception:
        enviados = 0
    return {"ok": True, "anuncio": _dict(a), "enviados": enviados}


def archivo(db: Session, anuncio_id):
    """(bytes, mime, nombre) del adjunto, o None."""
    a = db.query(Anuncio).filter(Anuncio.id == anuncio_id).first()
    if not a or not getattr(a, "archivo_datos", None):
        return None
    try:
        data = base64.b64decode(a.archivo_datos, validate=False)
    except Exception:  # noqa: BLE001
        return None
    return data, (a.archivo_mime or "application/octet-stream"), (a.archivo_nombre or "adjunto")


def listar_por_course(db: Session, course_id, limite: int = 30) -> dict:
    filas = (db.query(Anuncio).filter(Anuncio.course_id == str(course_id))
             .order_by(Anuncio.created_at.desc()).limit(min(int(limite or 30), 100)).all())
    return {"ok": True, "anuncios": [_dict(a) for a in filas]}


def listar_por_codigo(db: Session, codigo: str, limite: int = 30) -> dict:
    try:
        a = silabo_service.agente_por_codigo(db, codigo)
    except Exception:
        return {"ok": True, "anuncios": []}
    return listar_por_course(db, a.course_id, limite)


def _payload_push(a: Anuncio, recordatorio: bool = False, corregido: bool = False) -> dict:
    tiene = bool(getattr(a, "archivo_datos", None) or getattr(a, "url", None))
    titulo = a.titulo or "Anuncio del curso"
    # El emoji dice de qué se trata antes de abrirlo: nuevo, recordatorio o corrección.
    marca = "✏️ Corregido · " if corregido else ("🔁 " if recordatorio else "📣 ")
    return {"title": marca + titulo,
            "body": ((a.cuerpo or "")[:380] or titulo) + (" 📎" if tiene else ""),
            # El tag lleva la vuelta: sin eso el sistema operativo reemplazaría el aviso anterior
            # y un recordatorio pasaría desapercibido justo por ser el mismo texto.
            "tag": f"anuncio-{a.id}-{int(getattr(a, 'veces_enviado', 1) or 1)}",
            "url": "/?avisos=1", "requireInteraction": True,
            "vibrate": [120, 60, 120, 60, 200],
            "icon": "/runi/icons/icon-192.png", "badge": "/runi/icons/icon-192.png"}


def tick(db: Session) -> dict:
    """Reenvía los comunicados recurrentes que tocan hoy. Idempotente: llamarlo diez veces al día
    no manda diez avisos, porque `ultimo_envio` guarda el día en que ya sonó.

    Se repite el AVISO, no el anuncio: no se crean filas nuevas, así la bandeja del alumno conserva
    una sola entrada por comunicado en vez de llenarse de copias del mismo texto.
    """
    hoy = _dt.date.today()
    filas = (db.query(Anuncio)
             .filter(Anuncio.repeticion != "unica", Anuncio.repetir_hasta >= hoy.isoformat()).all())
    enviados, tocados = 0, 0
    for a in filas:
        if not _vigente(a):
            continue
        cada = REPETICIONES.get(a.repeticion or "unica", 0)
        if cada <= 0:
            continue
        try:
            ultimo = _dt.date.fromisoformat((a.ultimo_envio or "")[:10])
        except (ValueError, TypeError):
            ultimo = None
        if ultimo and (hoy - ultimo).days < cada:
            continue                       # todavía no le toca
        try:
            enviados += push_service.enviar_a_curso(db, a.course_id, _payload_push(a, recordatorio=True))
        except Exception:  # noqa: BLE001 — un push caído no puede dejar el barrido a medias
            pass
        a.ultimo_envio = hoy.isoformat()
        a.veces_enviado = int(a.veces_enviado or 1) + 1
        db.commit(); tocados += 1
    return {"ok": True, "recurrentes_reenviados": tocados, "push_enviados": enviados}


def _buscar(db: Session, anuncio_id) -> Anuncio:
    """Acepta el id como texto o como UUID: quien llama no tiene por qué saber cuál espera la BD."""
    try:
        uid = anuncio_id if isinstance(anuncio_id, _uuid.UUID) else _uuid.UUID(str(anuncio_id))
    except (ValueError, TypeError, AttributeError):
        raise not_found("Ese anuncio no existe.")
    a = db.query(Anuncio).filter(Anuncio.id == uid).first()
    if not a:
        raise not_found("Ese anuncio no existe.")
    return a


def editar(db: Session, anuncio_id, payload: dict, notificar: bool = True) -> dict:
    """Corrige un comunicado ya publicado, sin perderlo ni perder su historial de envíos.

    **Por defecto vuelve a avisar.** Un aviso corregido en silencio es peor que un pitido de más:
    quien ya leyó «sala 302» se queda con ese dato y llega al lugar equivocado. Quien solo arregla
    una tilde puede desmarcarlo.

    El adjunto se conserva salvo que manden uno nuevo o pidan quitarlo explícitamente: no se borra
    un archivo por el hecho de no volver a subirlo al editar.
    """
    a = _buscar(db, anuncio_id)
    p = payload or {}

    if "titulo" in p or "cuerpo" in p:
        titulo = str(p.get("titulo", a.titulo) or "").strip()[:140]
        cuerpo = str(p.get("cuerpo", a.cuerpo) or "").strip()[:1000]
        if not titulo and not cuerpo:
            raise unprocessable("El anuncio necesita al menos un título o un mensaje.")
        a.titulo = titulo or "Anuncio del curso"
        a.cuerpo = cuerpo
    if "url" in p:
        a.url = str(p.get("url") or "").strip()[:2000] or None

    if p.get("quitar_archivo"):
        a.archivo_datos = None; a.archivo_nombre = None; a.archivo_mime = None; a.tamano = 0
    elif p.get("archivo_datos"):
        crudo = re.sub(r"^data:[^;]+;base64,", "", str(p["archivo_datos"]))
        try:
            tamano = len(base64.b64decode(crudo, validate=False))
        except Exception:  # noqa: BLE001
            tamano = int(len(crudo) * 0.75)
        if tamano > _MAX_BYTES:
            raise unprocessable("El archivo supera 6 MB. Comparte un enlace (Drive/web) en su lugar.")
        a.archivo_datos = crudo
        a.archivo_nombre = str(p.get("archivo_nombre") or "").strip()[:200] or a.archivo_nombre
        a.archivo_mime = str(p.get("archivo_mime") or "").strip()[:100] or a.archivo_mime
        a.tamano = tamano

    if "repeticion" in p:
        antes = a.repeticion or "unica"
        rep, hasta = _leer_recurrencia(p)
        a.repeticion, a.repetir_hasta = rep, hasta
        # Al pasar de «una vez» a recurrente, la cuenta parte HOY: si no, un anuncio viejo dispararía
        # el recordatorio en el mismo instante de guardarlo.
        if antes == "unica" and rep != "unica":
            a.ultimo_envio = _dt.date.today().isoformat()

    db.commit(); db.refresh(a)
    enviados = 0
    if notificar:
        try:
            enviados = push_service.enviar_a_curso(db, a.course_id, _payload_push(a, corregido=True))
            a.veces_enviado = int(a.veces_enviado or 1) + 1
            a.ultimo_envio = _dt.date.today().isoformat()
            db.commit()
        except Exception:  # noqa: BLE001 — la corrección ya quedó guardada; el push es lo accesorio
            enviados = 0
    return {"ok": True, "anuncio": _dict(a), "enviados": enviados}


def detener(db: Session, anuncio_id) -> dict:
    """Apaga la repetición sin borrar el comunicado: el aviso deja de sonar y el texto sigue en la
    bandeja para quien quiera consultarlo."""
    a = _buscar(db, anuncio_id)
    a.repeticion = "unica"
    a.repetir_hasta = None
    db.commit()
    return {"ok": True, "anuncio": _dict(a)}


def eliminar(db: Session, anuncio_id) -> dict:
    a = _buscar(db, anuncio_id)
    db.delete(a); db.commit()
    return {"ok": True}
