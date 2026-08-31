"""
El Reto de Runi: Runi deja de esperar y propone.

El CEO lo diagnosticó sobre su propio producto: Runi es pasivo, alguien con quien conversar. Si la
estudiante no entra, no pasa nada. La idea es que cada vez que entre encuentre algo nuevo — y que ese
algo nuevo sea **lo que de verdad entra en el Solemne**, no entretención suelta.

Cómo funciona, y por qué así:

- **Un banco por curso, no una pregunta por alumna por día.** La IA propone una vez, sobre el
  programa y la tabla de especificaciones que el docente ya cargó. Una llamada por estudiante por
  día son miles al mes; el pilotaje ya se quedó sin saldo una vez y Runi entero dejó de responder.
- **La personalización NO cuesta IA.** Elegir qué le toca hoy a esta persona es ordenar el banco:
  primero sus vacíos, después lo que pesa en la tabla, y nunca lo que ya respondió.
- **El docente aprueba antes.** En anatomía aplicada una pregunta mal generada le enseña algo falso
  a quien la responde. La IA propone; la firma es del profesor.
- **2 o 3 por sesión.** Suficiente para que haya algo nuevo, poco para que no se vuelva una tarea.
"""
from __future__ import annotations

import hashlib
import logging
import uuid as _uuid

from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found, unprocessable
from app.models.reto import ESTADOS, RetoPregunta, RetoRespuesta

_LOG = logging.getLogger("evalys")
POR_SESION = 3            # tope duro: el CEO pidió 2 o 3, nunca una rueda infinita
_MAX_BANCO = 400          # por curso; más que esto no lo revisa nadie
NIVELES = ("recordar", "conectar", "aplicar")


# ── generación (propone; NO publica) ──────────────────────────────────────────────────
def _prompt(curso: str, temas: list, contexto: str, n_por_tema: int) -> tuple:
    system = (
        f"Eres quien prepara preguntas de estudio para el curso {curso}. Trabajas SOLO con el "
        "material del profesor que viene abajo: no inventes contenidos que no estén ahí.\n"
        "Para CADA tema entrega preguntas de opción múltiple con 4 alternativas, una sola correcta y "
        "distractores plausibles (errores que un estudiante comete de verdad, no absurdos).\n"
        "Reparte los niveles: 'recordar' (recuperar un hecho), 'conectar' (relacionar dos ideas del "
        "curso) y 'aplicar' (un caso concreto que no está en el material).\n"
        "La justificación explica POR QUÉ la correcta lo es, en una o dos frases, en segunda persona "
        "y sin condescendencia: la va a leer la estudiante justo después de responder.\n"
        "Si el material no alcanza para un tema, entrega MENOS preguntas de ese tema. Preferimos "
        "pocas y sólidas antes que rellenar.\n"
        'Devuelve SOLO JSON: {"preguntas":[{"tema":"…","nivel":"recordar|conectar|aplicar",'
        '"enunciado":"…","alternativas":{"A":"…","B":"…","C":"…","D":"…"},"correcta":"A",'
        '"justificacion":"…"}]}'
    )
    user = ("TEMAS QUE ENTRAN EN LA EVALUACIÓN (con su peso):\n"
            + "\n".join(f"- {t.get('tema')} (peso {t.get('peso', 1)})" for t in temas)
            + f"\n\nGenera hasta {n_por_tema} preguntas por tema.\n\n"
            + "MATERIAL DEL PROFESOR:\n" + (contexto or "")[:24000])
    return system, user


def _temas_desde(temas_txt: str) -> list:
    """Lee los temas que escribió el docente: una línea por tema, con «peso» opcional al final."""
    out = []
    for linea in str(temas_txt or "").splitlines():
        t = linea.strip(" -•\t")
        if not t:
            continue
        peso = 1
        # «Pelvis ósea 30%» o «Pelvis ósea | 3»
        import re as _re
        m = _re.search(r"[|·]?\s*(\d{1,3})\s*%?\s*$", t)
        if m:
            peso = max(1, min(100, int(m.group(1))))
            t = t[:m.start()].strip(" -•|·\t")
        if t:
            out.append({"tema": t[:160], "peso": peso})
    return out[:40]


def generar(db: Session, course_id, temas_txt: str, contexto: str, curso: str = "",
            eval_id: str | None = None, n_por_tema: int = 3) -> dict:
    """Propone preguntas para el banco. Quedan en 'propuesta': NADIE las ve hasta que se aprueben."""
    temas = _temas_desde(temas_txt)
    if not temas:
        raise unprocessable("Escribe al menos un tema (una línea por tema).")
    if not str(contexto or "").strip():
        raise unprocessable("Este curso todavía no tiene material cargado para basarse.")
    n_por_tema = max(1, min(6, int(n_por_tema or 3)))

    import json
    import os
    import re
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise conflict("El motor de IA no está disponible ahora mismo.")
    system, user = _prompt(curso or "el curso", temas, contexto, n_por_tema)
    crudas = []
    for intento in range(3):
        try:
            from app.services import correccion_experta_service as ce
            txt = ce._llamar_anthropic(system, user, max_tokens=8000)
            m = re.search(r"\{.*\}", txt or "", re.S)
            d = json.loads(m.group(0)) if m else {}
            crudas = d.get("preguntas") or []
            if crudas:
                break
        except Exception as e:  # noqa: BLE001
            _LOG.warning("reto: generación intento %d/3 falló: %s", intento + 1, str(e)[:140])
    if not crudas:
        raise conflict("No se pudieron generar preguntas ahora. Reintenta en un momento.")

    pesos = {t["tema"].lower(): t["peso"] for t in temas}
    ya = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id)).count()
    nuevas = []
    for q in crudas:
        if ya + len(nuevas) >= _MAX_BANCO:
            break
        p = _normalizar(q, pesos)
        if p:
            nuevas.append(RetoPregunta(course_id=str(course_id), eval_id=eval_id, **p))
    if not nuevas:
        raise conflict("Las preguntas generadas no eran utilizables. Reintenta.")
    db.add_all(nuevas); db.commit()
    return {"ok": True, "propuestas": len(nuevas),
            "preguntas": [_dict(p, con_respuesta=True) for p in nuevas]}


def _normalizar(q: dict, pesos: dict) -> dict | None:
    """Descarta lo inservible en vez de guardarlo a medias: una pregunta rota gasta el tiempo del
    docente cuando la revisa, y peor aún si se le escapa aprobada."""
    enun = str((q or {}).get("enunciado") or "").strip()
    alts = (q or {}).get("alternativas") or {}
    if not enun or not isinstance(alts, dict):
        return None
    limpias = {k.upper(): str(v).strip()[:300] for k, v in alts.items()
               if str(k).upper() in ("A", "B", "C", "D", "E") and str(v or "").strip()}
    if len(limpias) < 2:
        return None
    corr = str(q.get("correcta") or "").strip().upper()[:1]
    if corr not in limpias:
        return None
    tema = str(q.get("tema") or "").strip()[:160] or "General"
    nivel = str(q.get("nivel") or "recordar").strip().lower()
    return {"tema": tema, "peso": pesos.get(tema.lower(), 1),
            "enunciado": enun[:1200], "alternativas": limpias, "correcta": corr,
            "justificacion": str(q.get("justificacion") or "").strip()[:600] or None,
            "nivel": nivel if nivel in NIVELES else "recordar", "estado": "propuesta", "origen": "ia"}


# ── los «porqués»: Runi redacta, el docente firma ─────────────────────────────────────
# Una pauta trae la respuesta correcta, no la explicación. Sin ella el reto solo CORRIGE; con ella
# ENSEÑA, que es la diferencia entre marcar un error y cerrar un vacío. Pero una explicación
# equivocada de anatomía enseña algo falso igual que una pregunta mala: por eso el texto de la IA
# queda en `justificacion_ia` y NO se le muestra a nadie hasta que el docente lo acepta.
_POR_TANDA = 8          # más preguntas por llamada = respuestas más pobres y JSON que se corta


def _prompt_justificar(curso: str, contexto: str, preguntas: list) -> tuple:
    system = (
        f"Escribes las explicaciones de un banco de preguntas del curso {curso}. Para cada pregunta "
        "te doy el enunciado, las alternativas y CUÁL ES LA CORRECTA (ya está decidida por el "
        "profesor: no la discutas ni la cambies).\n"
        "Escribe POR QUÉ esa alternativa es la correcta, en una o dos frases. Si hay un distractor "
        "que se elige mucho por confusión, di en media frase qué lo distingue.\n"
        "La lee la estudiante justo después de responder: segunda persona, directo, sin "
        "condescendencia y sin felicitarla (de eso se encarga la app). Nada de «como sabemos» ni "
        "«obviamente».\n"
        "Apóyate SOLO en el material del profesor. Si el material no alcanza para justificar una, "
        "devuelve su texto vacío antes que inventar.\n"
        'Devuelve SOLO JSON: {"justificaciones":[{"n":1,"texto":"…"},…]} con la misma numeración.'
    )
    lineas = []
    for i, p in enumerate(preguntas, start=1):
        alts = "; ".join(f"{k}) {v}" for k, v in sorted((p.alternativas or {}).items()))
        lineas.append(f"{i}. {p.enunciado}\n   {alts}\n   CORRECTA: {p.correcta}")
    user = ("MATERIAL DEL PROFESOR:\n" + (contexto or "")[:14000]
            + "\n\nPREGUNTAS:\n" + "\n\n".join(lineas))
    return system, user


def justificar(db: Session, course_id, contexto: str, curso: str = "", rehacer: bool = False) -> dict:
    """Redacta los porqués que faltan. Quedan como BORRADOR hasta que el docente los acepte."""
    import json
    import os
    import re
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise conflict("El motor de IA no está disponible ahora mismo.")
    if not str(contexto or "").strip():
        raise unprocessable("Este curso todavía no tiene material cargado para basarse.")

    q = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id),
                                      RetoPregunta.estado != "descartada")
    faltan = [p for p in q.all()
              if rehacer or (not (p.justificacion or "").strip() and not (p.justificacion_ia or "").strip())]
    if not faltan:
        return {"ok": True, "redactadas": 0, "sin_material": 0, "nada_que_hacer": True}

    from app.services import correccion_experta_service as ce
    redactadas, vacias = 0, 0
    for i in range(0, len(faltan), _POR_TANDA):
        tanda = faltan[i:i + _POR_TANDA]
        system, user = _prompt_justificar(curso or "el curso", contexto, tanda)
        textos = {}
        for intento in range(3):
            try:
                crudo = ce._llamar_anthropic(system, user, max_tokens=2600)
                m = re.search(r"\{.*\}", crudo or "", re.S)
                d = json.loads(m.group(0)) if m else {}
                for j in (d.get("justificaciones") or []):
                    try:
                        textos[int(j.get("n"))] = str(j.get("texto") or "").strip()[:600]
                    except (TypeError, ValueError):
                        continue
                if textos:
                    break
            except Exception as e:  # noqa: BLE001
                _LOG.warning("reto: justificar intento %d/3 falló: %s", intento + 1, str(e)[:140])
        for n, p in enumerate(tanda, start=1):
            t = (textos.get(n) or "").strip()
            if t:
                p.justificacion_ia = t; redactadas += 1
            else:
                vacias += 1     # el material no alcanzaba: se deja vacío antes que inventar
        db.commit()
    return {"ok": True, "redactadas": redactadas, "sin_material": vacias, "nada_que_hacer": False}


def usar_justificacion(db: Session, pregunta_id, texto: str | None = None) -> dict:
    """El docente acepta (o corrige) el borrador: recién ahí lo ve la estudiante."""
    p = _buscar(db, pregunta_id)
    final = (texto if texto is not None else (p.justificacion_ia or "")).strip()[:600]
    if not final:
        raise unprocessable("No hay texto que usar.")
    p.justificacion = final
    p.justificacion_ia = None
    db.commit()
    return {"ok": True, "pregunta": _dict(p, con_respuesta=True)}


def usar_todas_las_justificaciones(db: Session, course_id) -> dict:
    filas = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id)).all()
    n = 0
    for p in filas:
        if (p.justificacion_ia or "").strip():
            p.justificacion = p.justificacion_ia.strip()[:600]
            p.justificacion_ia = None
            n += 1
    db.commit()
    return {"ok": True, "aceptadas": n}


def descartar_justificacion(db: Session, pregunta_id) -> dict:
    p = _buscar(db, pregunta_id)
    p.justificacion_ia = None
    db.commit()
    return {"ok": True}


# ── revisión del docente ──────────────────────────────────────────────────────────────
def _dict(p: RetoPregunta, con_respuesta: bool = False) -> dict:
    d = {"id": str(p.id), "tema": p.tema, "peso": p.peso, "enunciado": p.enunciado,
         "alternativas": p.alternativas or {}, "nivel": p.nivel, "estado": p.estado,
         "origen": p.origen, "veces_servida": p.veces_servida, "aciertos": p.aciertos}
    if con_respuesta:
        d["correcta"] = p.correcta
        d["justificacion"] = p.justificacion
        # El borrador solo viaja al panel del docente, nunca a la app del alumno.
        d["justificacion_ia"] = getattr(p, "justificacion_ia", None)
    return d


def _buscar(db: Session, pregunta_id) -> RetoPregunta:
    try:
        uid = pregunta_id if isinstance(pregunta_id, _uuid.UUID) else _uuid.UUID(str(pregunta_id))
    except (ValueError, TypeError, AttributeError):
        raise not_found("Esa pregunta no existe.")
    p = db.query(RetoPregunta).filter(RetoPregunta.id == uid).first()
    if not p:
        raise not_found("Esa pregunta no existe.")
    return p


def listar_docente(db: Session, course_id, estado: str = "") -> dict:
    q = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id))
    if estado:
        q = q.filter(RetoPregunta.estado == estado)
    filas = q.order_by(RetoPregunta.created_at.desc()).limit(500).all()
    cuenta = {e: 0 for e in ESTADOS}
    for p in db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id)).all():
        cuenta[p.estado] = cuenta.get(p.estado, 0) + 1
    return {"ok": True, "preguntas": [_dict(p, con_respuesta=True) for p in filas], "conteos": cuenta}


def revisar(db: Session, pregunta_id, accion: str, cambios: dict | None = None) -> dict:
    """aprobar · descartar · editar. Editar y aprobar en un solo paso: corregir una pregunta y
    tener que aprobarla aparte es un clic de más en una tarea que ya son decenas de clics."""
    p = _buscar(db, pregunta_id)
    c = cambios or {}
    if "enunciado" in c:
        p.enunciado = str(c["enunciado"]).strip()[:1200] or p.enunciado
    if "alternativas" in c and isinstance(c["alternativas"], dict):
        limpias = {k.upper(): str(v).strip()[:300] for k, v in c["alternativas"].items() if str(v or "").strip()}
        if len(limpias) >= 2:
            p.alternativas = limpias
    if "correcta" in c:
        corr = str(c["correcta"]).strip().upper()[:1]
        if corr in (p.alternativas or {}):
            p.correcta = corr
    if "justificacion" in c:
        p.justificacion = str(c["justificacion"]).strip()[:600] or None
    if "tema" in c:
        p.tema = str(c["tema"]).strip()[:160] or p.tema

    if accion == "aprobar":
        if p.correcta not in (p.alternativas or {}):
            raise unprocessable("Marca cuál es la alternativa correcta antes de aprobar.")
        p.estado = "aprobada"
    elif accion == "descartar":
        p.estado = "descartada"
    elif accion != "editar":
        raise unprocessable("Acción no válida.")
    db.commit()
    return {"ok": True, "pregunta": _dict(p, con_respuesta=True)}


def aprobar_todas(db: Session, course_id) -> dict:
    """Publica de una vez todo lo que está por revisar.

    Revisar treinta preguntas con un clic cada una no es una revisión: es una fila de clics que se
    despacha sin mirar. El docente lee la lista completa en pantalla y publica el lote; lo que no le
    convenza lo descarta antes, una por una, que es donde el clic sí significa algo.
    """
    filas = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id),
                                          RetoPregunta.estado == "propuesta").all()
    ok, rotas = 0, 0
    for p in filas:
        if p.correcta in (p.alternativas or {}):
            p.estado = "aprobada"; ok += 1
        else:
            rotas += 1          # sin correcta válida no se puede corregir: se queda para revisión
    db.commit()
    return {"ok": True, "publicadas": ok, "sin_correcta": rotas}


def vaciar(db: Session, course_id, estado: str) -> dict:
    """Borra de golpe un estado completo (típicamente las descartadas). No toca las demás."""
    if estado not in ESTADOS:
        raise unprocessable("Estado no válido.")
    ids = [p.id for p in db.query(RetoPregunta).filter(
        RetoPregunta.course_id == str(course_id), RetoPregunta.estado == estado).all()]
    if not ids:
        return {"ok": True, "eliminadas": 0}
    db.query(RetoRespuesta).filter(RetoRespuesta.pregunta_id.in_(ids)).delete(synchronize_session=False)
    db.query(RetoPregunta).filter(RetoPregunta.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "eliminadas": len(ids)}


def crear_manual(db: Session, course_id, datos: dict, eval_id: str | None = None) -> dict:
    """Una pregunta escrita por el docente. Nace aprobada: ya la escribió él."""
    p = _normalizar(datos or {}, {})
    if not p:
        raise unprocessable("La pregunta necesita enunciado, al menos dos alternativas y cuál es la correcta.")
    p["estado"] = "aprobada"; p["origen"] = "docente"
    p["tema"] = str((datos or {}).get("tema") or "General")[:160]
    fila = RetoPregunta(course_id=str(course_id), eval_id=eval_id, **p)
    db.add(fila); db.commit()
    return {"ok": True, "pregunta": _dict(fila, con_respuesta=True)}


def eliminar(db: Session, pregunta_id) -> dict:
    p = _buscar(db, pregunta_id)
    db.query(RetoRespuesta).filter(RetoRespuesta.pregunta_id == p.id).delete(synchronize_session=False)
    db.delete(p); db.commit()
    return {"ok": True}


# ── ventanas del día: los retos aparecen y desaparecen ────────────────────────────────
# Pedido del CEO, con su propia imagen: «son como los huevitos de chocolate». Si el banco entero
# está disponible siempre, se convierte en una lista de tareas y se acaba en una sentada; la magia
# está en que aparezcan unos pocos, a ratos, y que si no los tomaste se hayan ido.
#
# Cuatro ventanas de 90 minutos en hora de Chile (UTC-4). Ninguna de noche.
_TZ_CHILE = -4
# Cada 2 horas de 9 a 21 (pedido del CEO: cuatro veces al día «no genera nada»). Ninguna de noche.
VENTANAS = (9, 11, 13, 15, 17, 19, 21)
# La ventana se acorta a 1 hora: con una apertura cada 2 h, 90 minutos dejaría el reto disponible
# tres cuartas partes del día y se perdería justo lo que lo hace un hallazgo.
DURACION_MIN = 60
# Preguntas cada 2 h, pero AVISOS cuatro veces al día. Siete notificaciones diarias no crean el
# hábito: hacen que se silencie la app, y con ella se pierden también los avisos del profesor.
VENTANAS_CON_AVISO = (9, 13, 17, 21)


def _local(ahora=None):
    import datetime as _dt
    return (ahora or _dt.datetime.utcnow()) + _dt.timedelta(hours=_TZ_CHILE)


def ventana_de(ahora=None) -> dict:
    """¿Hay ventana abierta ahora? Devuelve también cuándo abre la próxima, para poder decirlo."""
    import datetime as _dt
    loc = _local(ahora)
    abierta, desde = None, None
    for h in VENTANAS:
        ini = loc.replace(hour=h, minute=0, second=0, microsecond=0)
        if ini <= loc < ini + _dt.timedelta(minutes=DURACION_MIN):
            abierta, desde = h, ini
            break
    prox = None
    for h in VENTANAS:
        if h > loc.hour or (h == loc.hour and loc.minute == 0):
            prox = loc.replace(hour=h, minute=0, second=0, microsecond=0)
            break
    if prox is None:                       # ya pasaron todas: la primera de mañana
        prox = (loc + _dt.timedelta(days=1)).replace(hour=VENTANAS[0], minute=0, second=0, microsecond=0)
    return {"abierta": abierta is not None, "hora": abierta,
            "desde_utc": (desde - _dt.timedelta(hours=_TZ_CHILE)) if desde else None,
            "cierra_local": (desde + _dt.timedelta(minutes=DURACION_MIN)).strftime("%H:%M") if desde else None,
            "proxima_local": prox.strftime("%H:%M"),
            "minutos_para_proxima": max(0, int((prox - loc).total_seconds() // 60))}


def _respondidas_en_ventana(db: Session, pseudo_id: str, v: dict) -> int:
    if not v["abierta"] or not v["desde_utc"]:
        return 0
    return (db.query(RetoRespuesta)
            .filter(RetoRespuesta.pseudo_id == pseudo_id,
                    RetoRespuesta.created_at >= v["desde_utc"]).count())


# ── la sesión del estudiante ──────────────────────────────────────────────────────────
def _prioridad(p: RetoPregunta, vacios: set, pseudo_id: str) -> tuple:
    """Orden en que se le sirven las preguntas a ESTA persona.

    Primero sus vacíos —lo que ya mostró que no domina—, después lo que más pesa en la tabla de
    especificaciones. El desempate es un hash de (persona, pregunta): así dos estudiantes con los
    mismos vacíos no reciben la lista en el mismo orden, y a nadie le toca siempre lo mismo primero.
    """
    es_vacio = 0 if (p.tema or "").lower() in vacios else 1
    desempate = hashlib.sha256(f"{pseudo_id}|{p.id}".encode()).hexdigest()
    return (es_vacio, -int(p.peso or 1), desempate)


def _vacios_de(db: Session, pseudo_id: str) -> set:
    """Los temas donde esta persona se declaró con baja confianza o falló creyendo saber."""
    try:
        from app.models.episode import ConfidenceObs
        obs = db.query(ConfidenceObs).filter(ConfidenceObs.pseudo_id == pseudo_id).all()
    except Exception:  # noqa: BLE001
        return set()
    flojos = set()
    for o in obs:
        if not o.ra:
            continue
        if o.correct is False or (o.confidence or 0) <= 40:
            flojos.add(str(o.ra).lower())
    return flojos


def sesion(db: Session, course_id, pseudo_id: str, n: int = POR_SESION, ahora=None) -> dict:
    """Las 2–3 preguntas de ESTA ventana. Nunca una que ya respondió, y solo si hay ventana abierta."""
    if not (pseudo_id or "").strip():
        raise unprocessable("Falta la identidad del estudiante.")
    v = ventana_de(ahora)
    if not v["abierta"]:
        # Cerrado NO es un error: es lo que hace que valga la pena volver.
        return {"ok": True, "preguntas": [], "cerrado": True, "ventana": v}
    ya_en_ventana = _respondidas_en_ventana(db, pseudo_id, v)
    n = max(0, min(POR_SESION - ya_en_ventana, min(POR_SESION, int(n or POR_SESION))))
    if n <= 0:
        return {"ok": True, "preguntas": [], "cerrado": True, "completa": True, "ventana": v}
    respondidas = {r.pregunta_id for r in db.query(RetoRespuesta).filter(
        RetoRespuesta.pseudo_id == pseudo_id).all()}
    banco = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id),
                                          RetoPregunta.estado == "aprobada").all()
    pendientes = [p for p in banco if p.id not in respondidas]
    if not pendientes:
        # Que se acabe el banco NO es un error: es que ya respondió todo lo que su profe aprobó.
        return {"ok": True, "preguntas": [], "sin_pendientes": True, "ventana": v,
                "banco": len(banco), "respondidas": len(respondidas)}
    vacios = _vacios_de(db, pseudo_id)
    pendientes.sort(key=lambda p: _prioridad(p, vacios, pseudo_id))
    elegidas = pendientes[:n]
    for p in elegidas:
        p.veces_servida = int(p.veces_servida or 0) + 1
    db.commit()
    return {"ok": True, "sin_pendientes": False, "cerrado": False, "ventana": v,
            "preguntas": [_dict(p) for p in elegidas],      # sin la correcta: se revela al responder
            "banco": len(banco), "respondidas": len(respondidas),
            "quedan": len(pendientes) - len(elegidas)}


def responder(db: Session, pregunta_id, pseudo_id: str, elegida: str, course_id=None) -> dict:
    """Registra la respuesta y devuelve el veredicto con su justificación. Idempotente."""
    p = _buscar(db, pregunta_id)
    if p.estado != "aprobada":
        raise conflict("Esa pregunta no está disponible.")
    letra = str(elegida or "").strip().upper()[:1]
    if letra not in (p.alternativas or {}):
        raise unprocessable("Elige una de las alternativas.")

    ya = db.query(RetoRespuesta).filter(RetoRespuesta.pseudo_id == pseudo_id,
                                        RetoRespuesta.pregunta_id == p.id).first()
    if ya:
        return {"ok": True, "ya_respondida": True, "correcta": p.correcta,
                "acerto": bool(ya.correcta), "elegida": ya.elegida,
                "justificacion": p.justificacion}

    acerto = (letra == p.correcta)
    db.add(RetoRespuesta(pregunta_id=p.id, pseudo_id=pseudo_id, elegida=letra, correcta=acerto))
    if acerto:
        p.aciertos = int(p.aciertos or 0) + 1
    try:
        db.commit()
    except Exception:  # noqa: BLE001 — dos pestañas a la vez; la unicidad ya nos protegió
        db.rollback()
        return responder(db, pregunta_id, pseudo_id, elegida, course_id)

    # El reto ALIMENTA la evidencia, no es un juego aparte: queda como episodio verificado con su
    # observación de confianza, así cuenta para la Cumbre igual que un repaso.
    try:
        from app.services import episode_service as eps
        e = eps.start(db, pseudo_id, str(course_id or p.course_id), p.tema,
                      objetivo=f"Reto: {p.tema}", origen="reto")
        eps.observe(db, e["episode_id"], {"item_id": f"reto-{p.id}", "correct": acerto,
                                          "confidence": 60, "ra": p.tema})
        eps.feedback(db, e["episode_id"])
        eps.close(db, e["episode_id"], sintesis=f"Reto de {p.tema}",
                  check_immediate=acerto, programar_diferida="7d")
    except Exception:  # noqa: BLE001 — el reto ya quedó respondido; la evidencia es lo accesorio
        db.rollback()

    return {"ok": True, "acerto": acerto, "correcta": p.correcta, "elegida": letra,
            "justificacion": p.justificacion}


def mi_estado(db: Session, course_id, pseudo_id: str, ahora=None) -> dict:
    """Para la tarjeta de Inicio: cuántos retos lleva y si hay algo nuevo esperándola."""
    banco = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id),
                                          RetoPregunta.estado == "aprobada").count()
    filas = db.query(RetoRespuesta).filter(RetoRespuesta.pseudo_id == pseudo_id).all()
    ids = {r.pregunta_id for r in filas}
    aprobadas = {p.id for p in db.query(RetoPregunta).filter(
        RetoPregunta.course_id == str(course_id), RetoPregunta.estado == "aprobada").all()}
    hechas = len(ids & aprobadas)
    v = ventana_de(ahora)
    quedan_ventana = max(0, POR_SESION - _respondidas_en_ventana(db, pseudo_id, v)) if v["abierta"] else 0
    return {"ok": True, "banco": banco, "respondidos": hechas,
            "aciertos": sum(1 for r in filas if r.correcta and r.pregunta_id in aprobadas),
            # `hay_nuevos` manda en la interfaz: solo hay algo que ofrecer si además la ventana
            # está abierta y le quedan preguntas en ella.
            "hay_nuevos": (hechas < banco) and v["abierta"] and quedan_ventana > 0,
            "quedan_en_banco": banco - hechas, "quedan_en_ventana": quedan_ventana,
            "ventana": v}


# ── el aviso diario ───────────────────────────────────────────────────────────────────
# Ventana horaria en UTC. Chile está en UTC-4, así que 20:00–00:00 UTC es 16:00–20:00 allá: tarde,
# cuando alguien puede sentarse a estudiar. **Nunca de noche**: un recordatorio académico a las 2 AM
# no ayuda a nadie a aprender, solo entrena a silenciar la app.
# El aviso se manda al ABRIRSE cada ventana (ver VENTANAS). Se tolera un retraso: el barrido corre
# cada diez minutos y no siempre cae en el minuto exacto.
_TOLERANCIA_MIN = 25


def tick(db: Session, ahora=None) -> dict:
    """Un aviso al día por curso, con las preguntas nuevas que esperan. Idempotente por día.

    Se apoya en `PushSent` (única por eval_id+owner+hito) para no mandar el mismo aviso dos veces
    aunque el barrido corra cada diez minutos.
    """
    import datetime as _dt
    ahora = ahora or _dt.datetime.utcnow()
    v = ventana_de(ahora)
    if not v["abierta"] or v["hora"] not in VENTANAS_CON_AVISO:
        return {"ok": True, "fuera_de_hora": True, "avisados": 0}
    loc = _local(ahora)
    if loc.minute > _TOLERANCIA_MIN:
        # Ya pasó el momento del aviso: avisar a mitad de ventana llega tarde y molesta.
        return {"ok": True, "fuera_de_hora": True, "avisados": 0}
    hoy = f"{loc.date().isoformat()}#{v['hora']}"      # una vez por VENTANA, no por día

    from app.models.push import PushSent, StudentCourseFollow
    from app.services import push_service as ps

    cursos = {p.course_id for p in db.query(RetoPregunta).filter(
        RetoPregunta.estado == "aprobada").all()}
    avisados = 0
    for cid in cursos:
        banco = [p.id for p in db.query(RetoPregunta).filter(
            RetoPregunta.course_id == cid, RetoPregunta.estado == "aprobada").all()]
        if not banco:
            continue
        # `StudentCourseFollow.course_id` es UUID y el del banco es texto: si un curso quedó con un
        # id que no es UUID, no puede tener seguidores y no vale la pena tumbar el barrido por él.
        try:
            seguidores = db.query(StudentCourseFollow).filter(
                StudentCourseFollow.course_id == _uuid.UUID(str(cid))).all()
        except (ValueError, TypeError, AttributeError):
            continue
        for f in seguidores:
            ref = f"reto:{cid}"
            if db.query(PushSent).filter(PushSent.eval_id == ref, PushSent.owner_key == f.owner_key,
                                         PushSent.hito == hoy).first():
                continue
            db.add(PushSent(eval_id=ref, owner_key=f.owner_key, hito=hoy))
            db.commit()
            try:
                avisados += ps.enviar_a_owner(db, f.owner_key, payload_push(len(banco), v))
            except Exception:  # noqa: BLE001 — un push caído no deja el barrido a medias
                pass
    return {"ok": True, "avisados": avisados}


def payload_push(n_banco: int, v: dict | None = None) -> dict:
    """El aviso lleva la cara de Runi, como los anuncios: quien lo ve sabe de quién viene.

    Dice hasta cuándo está abierta: la ventana es corta a propósito, y no decirlo sería una trampa.
    """
    cierra = (v or {}).get("cierra_local")
    return {"title": "🦊 Runi abrió un reto",
            "body": ("Tres preguntas de lo que entra en tu evaluación"
                     + (", hasta las " + cierra if cierra else "") + ". Te toma un minuto."),
            "tag": "reto-ventana-" + str((v or {}).get("hora") or ""), "url": "/?reto=1",
            "icon": "/runi/icons/icon-192.png", "badge": "/runi/icons/icon-192.png",
            "vibrate": [90, 50, 90]}


# ── importar la pauta del docente (.docx) ─────────────────────────────────────────────
# El profesor ya tiene sus variantes escritas y con la correcta RESALTADA EN AMARILLO. Pedirle que
# las vuelva a escribir en un formulario sería tirar a la basura su trabajo; y transcribirlas a mano
# es justo donde se cuelan los errores. Se lee su archivo tal como está.
def _docx_parrafos(datos: bytes) -> list:
    """(texto, ¿resaltado?) por párrafo del .docx."""
    import io
    import re as _re
    import zipfile
    from html import unescape
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    out = []
    for p in _re.findall(r"<w:p\b.*?</w:p>", xml, _re.S):
        texto = unescape(_re.sub(r"<[^>]+>", "", p)).strip()
        if texto:
            # Cualquier resaltado sirve menos el explícito "none": no todos los docentes usan amarillo.
            marcado = bool(_re.search(r'w:highlight[^>]*w:val="(?!none)', p))
            out.append((texto, marcado))
    return out


_RE_ENUNCIADO = None
_RE_ALTERNATIVA = None


def _regex():
    global _RE_ENUNCIADO, _RE_ALTERNATIVA
    if _RE_ENUNCIADO is None:
        import re as _re
        _RE_ENUNCIADO = _re.compile(r"^\s*(\d{1,3})[.)]\s+(.{3,})$", _re.S)
        _RE_ALTERNATIVA = _re.compile(r"^\s*([a-eA-E])[.)]\s+(.+)$", _re.S)
    return _RE_ENUNCIADO, _RE_ALTERNATIVA


def parsear_docx(datos: bytes, tema_defecto: str = "General") -> list:
    """Lee «1. enunciado / a) … b) …» con la correcta resaltada. Devuelve preguntas listas."""
    re_en, re_alt = _regex()
    parrafos = _docx_parrafos(datos)
    preguntas, actual = [], None
    for texto, marcado in parrafos:
        m = re_alt.match(texto)
        if m and actual is not None:
            letra = m.group(1).upper()
            # Si esa letra YA existe, empezó otro bloque que no se reconoció como enunciado:
            # sobrescribirla corrompería en silencio la pregunta anterior. Se ignora.
            if letra not in actual["alternativas"]:
                actual["alternativas"][letra] = m.group(2).strip()[:300]
                if marcado:
                    actual["correcta"] = letra
            continue
        m = re_en.match(texto)
        if m:
            if actual and len(actual["alternativas"]) >= 2 and actual.get("correcta"):
                preguntas.append(actual)
            actual = {"enunciado": m.group(2).strip()[:1200], "alternativas": {},
                      "correcta": None, "tema": tema_defecto}
    if actual and len(actual["alternativas"]) >= 2 and actual.get("correcta"):
        preguntas.append(actual)
    return preguntas


def importar_docx(db: Session, course_id, datos_b64: str, tema: str = "General",
                  eval_id: str | None = None) -> dict:
    """Importa la pauta como preguntas APROBADAS: las escribió el docente, no hay nada que revisar.

    Solo entran las que traen su correcta marcada. Una pregunta sin respuesta señalada no se puede
    corregir, y adivinarla sería peor que dejarla fuera: se informa cuántas quedaron.
    """
    import base64
    import re as _re
    crudo = _re.sub(r"^data:[^;]+;base64,", "", str(datos_b64 or ""))
    try:
        datos = base64.b64decode(crudo, validate=False)
    except Exception:  # noqa: BLE001
        raise unprocessable("No pude leer el archivo. ¿Es un .docx?")
    try:
        preguntas = parsear_docx(datos, tema)
    except Exception:  # noqa: BLE001
        raise unprocessable("Ese archivo no parece un .docx de Word.")
    if not preguntas:
        raise unprocessable(
            "No encontré preguntas con su alternativa marcada. El formato esperado es «1. enunciado» "
            "y debajo «a) …», con la correcta resaltada en el documento.")

    ya = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id)).count()
    # No se importa dos veces el mismo enunciado: reimportar un archivo corregido es lo normal.
    existentes = {(p.enunciado or "").strip().lower()
                  for p in db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id)).all()}
    nuevas, repetidas = [], 0
    for q in preguntas:
        if ya + len(nuevas) >= _MAX_BANCO:
            break
        if q["enunciado"].strip().lower() in existentes:
            repetidas += 1
            continue
        nuevas.append(RetoPregunta(
            course_id=str(course_id), eval_id=eval_id, tema=q["tema"][:160], peso=1,
            enunciado=q["enunciado"], alternativas=q["alternativas"], correcta=q["correcta"],
            justificacion=None, nivel="recordar", estado="aprobada", origen="docente"))
    if nuevas:
        db.add_all(nuevas); db.commit()
    return {"ok": True, "importadas": len(nuevas), "repetidas": repetidas,
            "leidas": len(preguntas),
            "sin_marcar": max(0, _contar_enunciados(datos) - len(preguntas))}


def _contar_enunciados(datos: bytes) -> int:
    re_en, _ = _regex()
    try:
        return sum(1 for t, _m in _docx_parrafos(datos) if re_en.match(t))
    except Exception:  # noqa: BLE001
        return 0
