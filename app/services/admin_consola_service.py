"""
Consola del Administrador (CEO) — supervisión de gobernanza, SOLO LECTURA, rol 'creador'.

Acceso "fantasma": observa sin participar ni alterar la interacción. Cada lectura de contenido
de estudiantes registra un asiento en `admin_accesos_log` (bitácora que protege al CEO).

Ámbito actual: datos ya almacenados de la capa social (Notas y Momentos). Grabar videollamadas
o retener diálogos indefinidamente es un módulo aparte (captura de datos nuevos) que NO se hace aquí.
"""
from __future__ import annotations

import datetime as _dt
import logging

_LOG_CONSOLA = logging.getLogger("evalys")

from sqlalchemy.orm import Session

from app.models.admin_log import AccesoAdminLog
from app.models.pand_nota import PandNota
from app.models.pand_momento import PandMomento
from app.models.reunion import Disponibilidad, Reserva
from app.models.silabo import MensajeSilabo, SilaboAgente


def _iso(x):
    """Instante en ISO para que el cliente lo pinte en la hora local de quien mira."""
    return x.isoformat() if hasattr(x, "isoformat") else (str(x) if x else None)


def _log(db: Session, admin_email: str, recurso: str, detalle: str = "") -> None:
    try:
        db.add(AccesoAdminLog(admin_email=admin_email or "?", recurso=recurso, detalle=(detalle or None)))
        db.commit()
    except Exception:
        db.rollback()


def resumen(db: Session, admin_email: str) -> dict:
    """Conteos globales para el tablero (no lee contenido → asiento liviano)."""
    n_notas = db.query(PandNota).count()
    n_moment = db.query(PandMomento).count()
    n_accesos = db.query(AccesoAdminLog).count()
    _log(db, admin_email, "resumen", f"notas={n_notas} momentos={n_moment}")
    return {"ok": True, "resumen": {"notas": n_notas, "momentos": n_moment, "accesos_registrados": n_accesos}}


_MAX_SOCIAL = 300      # techo del listado; sin él la consola crece sin límite con el uso


def social(db: Session, admin_email: str, con_imagen: bool = False, limite: int = 0) -> dict:
    """Todas las Notas y Momentos de la plataforma (contenido). Registra el acceso.

    Las imágenes NO viajan en el listado: se entrega la URL de cada una y el navegador las
    pide cuando toca pintarlas. Devolver el base64 de todos los momentos en un solo JSON
    hacía crecer la respuesta a decenas de megas y el navegador cortaba con un
    "Failed to fetch" que no decía nada. `con_imagen` se mantiene para quien lo llame de
    forma explícita, pero ya no es como carga la consola.
    """
    tope = max(1, min(int(limite or _MAX_SOCIAL), 1000))
    notas = [{"id": str(r.id), "owner_key": r.owner_key, "curso": r.curso, "char": r.char,
              "nombre": r.nombre, "texto": r.texto,
              "created_at": r.created_at.isoformat() if r.created_at else None}
             for r in db.query(PandNota).order_by(PandNota.created_at.desc()).limit(tope).all()]
    momentos = []
    for r in db.query(PandMomento).order_by(PandMomento.created_at.desc()).limit(tope).all():
        d = {"id": str(r.id), "owner_key": r.owner_key, "curso": r.curso, "char": r.char,
             "nombre": r.nombre, "caption": r.caption, "reportes": r.reportes, "oculto": bool(r.oculto),
             "tiene_imagen": bool(r.imagen),
             "imagen_url": (f"/api/v1/admin/consola/momento/{r.id}/imagen" if r.imagen else None),
             "created_at": r.created_at.isoformat() if r.created_at else None}
        if con_imagen:
            d["imagen"] = r.imagen
        momentos.append(d)
    _log(db, admin_email, "social", f"notas={len(notas)} momentos={len(momentos)} imagen={int(con_imagen)}")
    return {"ok": True, "notas": notas, "momentos": momentos}


def reuniones(db: Session, admin_email: str) -> dict:
    """Reuniones/reservas EN VIVO: disponibilidades activas + próximas citas confirmadas."""
    disp_activas = db.query(Disponibilidad).filter(Disponibilidad.activo == True).count()  # noqa: E712
    hoy = _dt.date.today().isoformat()
    filas = (db.query(Reserva).filter(Reserva.estado == "confirmada", Reserva.fecha >= hoy)
             .order_by(Reserva.fecha.asc(), Reserva.inicio.asc()).limit(80).all())
    disp_ids = {r.disponibilidad_id for r in filas}
    disp = {d.id: d for d in db.query(Disponibilidad).filter(Disponibilidad.id.in_(disp_ids)).all()} if disp_ids else {}
    reservas = []
    for r in filas:
        d = disp.get(r.disponibilidad_id)
        reservas.append({"id": str(r.id), "fecha": r.fecha, "inicio": r.inicio, "fin": r.fin,
                         "invitado": r.invitado, "anfitrion": (d.anfitrion if d else ""),
                         "titulo": (d.titulo if d else "Reunión"), "video": bool(r.video_url),
                         "nota": r.nota})
    _log(db, admin_email, "reuniones", f"activas={disp_activas} reservas={len(reservas)}")
    return {"ok": True, "disponibilidades_activas": disp_activas, "reservas": reservas}


def dialogos(db: Session, admin_email: str, limite: int = 60) -> dict:
    """Diálogos con Runi EN VIVO: las consultas más recientes de los estudiantes (pulso, no archivo)."""
    filas = db.query(MensajeSilabo).order_by(MensajeSilabo.created_at.desc()).limit(min(int(limite or 60), 200)).all()
    ag_ids = {f.agente_id for f in filas}
    agentes = {a.id: a for a in db.query(SilaboAgente).filter(SilaboAgente.id.in_(ag_ids)).all()} if ag_ids else {}
    out = []
    for f in filas:
        a = agentes.get(f.agente_id)
        curso = (a.nombre_curso if a and a.nombre_curso else (a.codigo if a else None)) or "—"
        out.append({"id": str(f.id), "curso": curso, "alias": f.alias, "pregunta": f.pregunta,
                    "respuesta": (f.respuesta_ia or "")[:400], "tema": f.tema, "categoria": f.categoria,
                    "confianza": f.confianza, "estado": f.estado,
                    "created_at": f.created_at.isoformat() if f.created_at else None})
    _log(db, admin_email, "dialogos", f"n={len(out)}")
    return {"ok": True, "dialogos": out}


def accesos(db: Session, admin_email: str, limite: int = 200) -> dict:
    """La bitácora de accesos del propio administrador (transparencia interna)."""
    filas = db.query(AccesoAdminLog).order_by(AccesoAdminLog.created_at.desc()).limit(min(int(limite or 200), 1000)).all()
    return {"ok": True, "accesos": [{"admin": r.admin_email, "recurso": r.recurso, "detalle": r.detalle,
                                     "created_at": r.created_at.isoformat() if r.created_at else None} for r in filas]}


def sesiones(db: Session, admin_email: str) -> dict:
    """Sesiones de grupo ABIERTAS en toda la plataforma, de los cuatro tipos que existen.

    Nació de una auditoría antes del piloto: el CEO no tenía forma de saber qué sesiones
    había vivas. Cada tipo se listaba solo por su código o por su evaluación, y las salas de
    estudio de los alumnos no las listaba NADIE — existían y eran invisibles.

    Solo lectura, coherente con el modo fantasma del resto de la consola: dice QUÉ hay
    abierto y quién lo abrió, no el contenido de lo que se conversa dentro.
    """
    from app.models.sala_estudio import SalaEstudio, SalaMensaje
    from app.models.en_vivo import SesionEnVivo, ParticipanteVivo
    from app.models.asistencia import SesionAsistencia, MarcaAsistencia
    from app.models.grupo import Grupo, GrupoIntegrante
    from app.models.course import Course
    from app.models.assessment import Assessment
    from app.models.silabo import SilaboAgente

    # Cada bloque va aislado. Antes, si UNA tabla fallaba (p. ej. una columna que el modelo
    # declara y el esquema desplegado no tiene), reventaba el panel entero con un 500 que
    # pierde las cabeceras CORS: el CEO solo veía "Failed to fetch" y se quedaba sin
    # supervisión durante el piloto. Ahora el resto sigue vivo y el fallo se REPORTA.
    fallos = []

    def _bloque(nombre, fn, por_defecto):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            db.rollback()       # una consulta rota deja la sesión inutilizable para las siguientes
            _LOG_CONSOLA.error("consola/sesiones · bloque %s falló: %s", nombre, e)
            fallos.append({"bloque": nombre, "error": str(e)[:300]})
            return por_defecto

    # ── 1. Salas de estudio (las abren los propios alumnos) ──
    agentes = _bloque("agentes", lambda: {a.id: a for a in db.query(SilaboAgente).all()}, {})
    n_msg = _bloque("mensajes_sala",
                    lambda: dict(db.query(SalaMensaje.sala_id, _func_count(db))
                                 .group_by(SalaMensaje.sala_id).all()), {})
    estudio = []
    for s in _bloque("salas_estudio",
                     lambda: db.query(SalaEstudio).filter(SalaEstudio.activa.is_(True)).all(), []):
        ag = agentes.get(s.agente_id)
        estudio.append({"codigo": s.codigo, "titulo": s.titulo,
                        "curso": (ag.nombre_curso if ag else None),
                        "abierta_por": s.creador_alias, "abierta_at": _iso(s.created_at),
                        "participantes": len(s.participantes or []),
                        "mensajes": int(n_msg.get(s.id, 0))})

    # ── 2. Salas en vivo (las abre el docente sobre una evaluación) ──
    # Se piden solo las columnas necesarias: así una columna nueva del modelo que aún no
    # exista en el esquema desplegado no tumba la consulta entera.
    asms = _bloque("evaluaciones",
                   lambda: {str(i): (n, cid) for i, n, cid in
                            db.query(Assessment.id, Assessment.name, Assessment.course_id).all()}, {})
    cursos = _bloque("cursos",
                     lambda: {i: n for i, n in db.query(Course.id, Course.name).all()}, {})
    n_part = dict(db.query(ParticipanteVivo.sesion_id, _func_count(db))
                  .group_by(ParticipanteVivo.sesion_id).all())
    vivo = []
    for s in _bloque("salas_en_vivo",
                     lambda: db.query(SesionEnVivo).filter(SesionEnVivo.estado != "cerrada").all(), []):
        a = asms.get(str(s.assessment_id))
        c = cursos.get(a[1]) if a else None
        vivo.append({"codigo": s.codigo, "estado": s.estado,
                     "evaluacion": (a[0] if a else None), "curso": c,
                     "pregunta": s.pregunta_actual, "de": s.n_preguntas,
                     "participantes": int(n_part.get(s.id, 0)), "abierta_at": _iso(s.created_at)})

    # ── 3. Sesiones de asistencia ──
    n_marcas = dict(db.query(MarcaAsistencia.sesion_id, _func_count(db))
                    .group_by(MarcaAsistencia.sesion_id).all())
    asistencia = []
    for s in _bloque("asistencia",
                     lambda: db.query(SesionAsistencia).filter(SesionAsistencia.estado == "abierta").all(), []):
        c = cursos.get(s.course_id)
        asistencia.append({"codigo": s.codigo, "titulo": s.titulo,
                           "curso": c, "fecha": s.fecha,
                           "inicio": _iso(s.inicio), "fin": _iso(s.fin),
                           "presentes": int(n_marcas.get(s.id, 0))})

    # ── 4. Grupos de trabajo (nota grupal) ──
    n_int = dict(db.query(GrupoIntegrante.grupo_id, _func_count(db))
                 .group_by(GrupoIntegrante.grupo_id).all())
    grupos = []
    for g in _bloque("grupos_trabajo", lambda: db.query(Grupo).all(), []):
        a = asms.get(str(g.assessment_id))
        c = cursos.get(a[1]) if a else None
        grupos.append({"nombre": g.nombre, "evaluacion": (a[0] if a else None),
                       "curso": c,
                       "integrantes": int(n_int.get(g.id, 0)), "creado_at": _iso(g.created_at)})

    # ── 5. Grupos de la Pandilla (los arman los propios alumnos) ──
    # Se construyeron después de este panel y se habían quedado fuera: el CEO veía los
    # grupos del DOCENTE (nota grupal) pero no los que forman los estudiantes entre ellos.
    from app.models.pand_grupo import PandGrupo, PandGrupoMiembro
    pandilla = []
    for g in _bloque("grupos_pandilla",
                     lambda: db.query(PandGrupo).order_by(PandGrupo.created_at.desc()).all(), []):
        ms = db.query(PandGrupoMiembro).filter(PandGrupoMiembro.grupo_id == g.id).order_by(
            PandGrupoMiembro.created_at.asc()).all()
        pandilla.append({"codigo": g.codigo, "nombre": g.nombre, "curso": g.curso,
                         "abierto": bool(g.abierto), "n_miembros": len(ms),
                         "integrantes": [(m.nombre or "Sin nombre") for m in ms],
                         "creado_at": _iso(g.created_at)})

    total = len(estudio) + len(vivo) + len(asistencia)
    _log(db, admin_email, "sesiones",
         f"estudio={len(estudio)} vivo={len(vivo)} asistencia={len(asistencia)} "
         f"grupos={len(grupos)} pandilla={len(pandilla)}")
    return {"ok": True,
            "resumen": {"abiertas": total, "salas_estudio": len(estudio), "en_vivo": len(vivo),
                        "asistencia": len(asistencia), "grupos_trabajo": len(grupos),
                        "grupos_pandilla": len(pandilla)},
            "salas_estudio": estudio, "en_vivo": vivo,
            "asistencia": asistencia, "grupos_trabajo": grupos, "grupos_pandilla": pandilla,
            "fallos": fallos}


def chats(db: Session, admin_email: str, limite: int = 300, grupo: str | None = None) -> dict:
    """Conversaciones de la Pandilla: las del curso y las de cada grupo.

    Decisión del CEO: «profesor solo tiene acceso a chat [de Runi]; administrador, acceso
    completo de todo registro». El ámbito vive en la columna `curso`: el id del curso para
    la conversación general, y 'g:<codigo>' para la de un grupo.

    Como toda la consola, esto es SOLO LECTURA y deja asiento en la bitácora.
    """
    from app.models.pand_chat import PandChat
    from app.models.pand_grupo import PandGrupo, PandGrupoMiembro
    from app.models.course import Course
    from app.models.silabo import SilaboAgente

    # Con `grupo` se pide UNA conversación (para abrirla desde el panel de sesiones): así no
    # hay que traer las de toda la plataforma para leer la de un equipo.
    q = db.query(PandChat)
    if grupo:
        q = q.filter(PandChat.curso == "g:" + str(grupo).strip().upper())
    filas = q.order_by(PandChat.created_at.desc()).limit(max(1, min(int(limite or 300), 1000))).all()

    # Para poder DISTINGUIR una conversación de otra hacen falta los nombres reales. Antes
    # toda conversación de curso se titulaba igual ("Conversación del curso"), así que con
    # varios cursos se veían como una lista plana e indistinguible.
    cursos = {str(i): n for i, n in db.query(Course.id, Course.name).all()}
    grupos = {g.codigo: g for g in db.query(PandGrupo).all()}
    # El grupo guarda el código del sílabo; el sílabo sabe a qué curso pertenece.
    curso_de_silabo = {a.codigo: cursos.get(str(a.course_id), a.nombre_curso)
                       for a in db.query(SilaboAgente).all()}

    ambitos = {}
    for m in reversed(filas):                       # cronológico dentro de cada conversación
        clave = m.curso or "—"
        if clave not in ambitos:
            es_grupo = clave.startswith("g:")
            cod = clave[2:] if es_grupo else None
            if es_grupo:
                g = grupos.get(cod)
                titulo = (g.nombre if g else None) or ("Grupo " + cod)
                curso_nom = curso_de_silabo.get(g.curso) if g else None
                integrantes = g and db.query(PandGrupoMiembro).filter(
                    PandGrupoMiembro.grupo_id == g.id).count() or 0
            else:
                titulo = cursos.get(clave) or "Curso"
                curso_nom = titulo
                integrantes = 0
            ambitos[clave] = {
                "ambito": clave,
                "tipo": "grupo" if es_grupo else "curso",
                "titulo": titulo,
                "curso": curso_nom,
                "n_integrantes": integrantes,
                "codigo": cod,
                "mensajes": [],
            }
        ambitos[clave]["mensajes"].append({
            "nombre": m.nombre or "Estudiante", "char": m.char, "texto": m.texto,
            "created_at": _iso(m.created_at)})

    # Los grupos primero: son lo que el CEO viene a mirar, y las conversaciones de curso
    # (una por curso) quedan debajo.
    convs = sorted(ambitos.values(),
                   key=lambda c: (0 if c["tipo"] == "grupo" else 1, -len(c["mensajes"])))
    _log(db, admin_email, "chats",
         (f"grupo={grupo} " if grupo else "")
         + f"conversaciones={len(convs)} mensajes={sum(len(c['mensajes']) for c in convs)}")
    return {"ok": True, "conversaciones": convs,
            "resumen": {"n_conversaciones": len(convs),
                        "n_grupos": sum(1 for c in convs if c["tipo"] == "grupo"),
                        "n_mensajes": sum(len(c["mensajes"]) for c in convs)}}


def _func_count(db):
    from sqlalchemy import func
    return func.count()


def imagen_momento(db: Session, admin_email: str, momento_id):
    """(bytes, mime) de UNA foto. Se sirve suelta para que el listado no cargue megas."""
    import base64
    import re as _re
    from app.models.pand_momento import PandMomento
    r = db.query(PandMomento).filter(PandMomento.id == momento_id).first()
    if not r or not r.imagen:
        return None
    m = _re.match(r"^data:([^;]+);base64,(.*)$", str(r.imagen), _re.S)
    mime = m.group(1) if m else "image/jpeg"
    crudo = m.group(2) if m else str(r.imagen)
    try:
        return base64.b64decode(crudo, validate=False), mime
    except Exception:  # noqa: BLE001
        return None
