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
from app.models.reto import ESTADOS, RetoIntento, RetoPregunta, RetoRespuesta

import datetime as _dt

_LOG = logging.getLogger("evalys")
_EPOCA = _dt.datetime(1970, 1, 1)
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


# ── variantes: más munición sin volver a escribirlo todo ──────────────────────────────
# El criterio lo puso el propio CEO en su pauta: «cada ítem evalúa el MISMO núcleo temático de la
# pregunta de origen, pero posee una respuesta correcta DISTINTA». No es parafrasear: es rotar cuál
# alternativa es la buena, que es lo que impide memorizar la letra en vez del contenido.
_VARIANTES_POR_TANDA = 6      # más por llamada = variantes flojas y JSON que se corta


def _prompt_variantes(curso: str, contexto: str, originales: list) -> tuple:
    system = (
        f"Preparas variantes de preguntas para el curso {curso}. Para cada pregunta original te doy "
        "el enunciado, sus alternativas y cuál es la correcta.\n"
        "Escribe UNA variante de cada una con esta regla, que es la del propio banco del profesor:\n"
        "  · MISMO núcleo temático que la original (la misma estructura, el mismo concepto);\n"
        "  · pero la respuesta correcta debe ser DISTINTA — no la misma idea con otras palabras.\n"
        "Así rota cuál es la buena y no se puede memorizar la letra en vez del contenido.\n"
        "Cuatro alternativas, una sola correcta, y distractores plausibles: errores que un estudiante "
        "comete de verdad, no absurdos evidentes.\n"
        "Incluye la justificación: por qué la correcta lo es, en una o dos frases, en segunda persona "
        "y sin condescendencia; si hay un distractor que se confunde mucho, di qué lo distingue.\n"
        "Trabaja SOLO con el material del profesor y con el contenido de la original: no inventes "
        "temas que no estén. Si de alguna no puedes hacer una variante honesta, OMÍTELA — es mejor "
        "devolver menos que rellenar.\n"
        'Devuelve SOLO JSON: {"variantes":[{"n":1,"tema":"…","nivel":"recordar|conectar|aplicar",'
        '"enunciado":"…","alternativas":{"A":"…","B":"…","C":"…","D":"…"},"correcta":"B",'
        '"justificacion":"…"}]} con la misma numeración que las originales.'
    )
    lineas = []
    for i, p in enumerate(originales, start=1):
        alts = "; ".join(f"{k}) {v}" for k, v in sorted((p.alternativas or {}).items()))
        lineas.append(f"{i}. [{p.tema}] {p.enunciado}\n   {alts}\n   CORRECTA: {p.correcta}")
    user = ("MATERIAL DEL PROFESOR:\n" + (contexto or "")[:12000]
            + "\n\nPREGUNTAS ORIGINALES:\n" + "\n\n".join(lineas))
    return system, user


def variantes(db: Session, course_id, contexto: str, curso: str = "",
              solo_del_docente: bool = True) -> dict:
    """Genera una variante de cada pregunta del banco. Quedan en 'propuesta': las revisa el docente.

    Por defecto parte SOLO de las preguntas escritas por el profesor. Hacer variantes de variantes
    aleja cada ronda un poco más del original y termina en preguntas que ya no son suyas.
    """
    import json
    import os
    import re
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise conflict("El motor de IA no está disponible ahora mismo.")

    q = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id),
                                      RetoPregunta.estado == "aprobada")
    if solo_del_docente:
        q = q.filter(RetoPregunta.origen == "docente")
    originales = q.all()
    if not originales:
        # El mensaje anterior decía «sube tu pauta o escribe alguna» incluso cuando la pauta estaba
        # subida: mandaba a hacer de nuevo algo ya hecho y escondía la causa. Ahora dice qué hay.
        todas = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id)).all()
        aprobadas = [p for p in todas if p.estado == "aprobada"]
        if not todas:
            raise unprocessable(
                "Este curso no tiene ninguna pregunta todavía. Sube tu pauta o escribe alguna primero.")
        if not aprobadas:
            raise unprocessable(
                f"Tienes {len(todas)} preguntas, pero ninguna publicada. Publícalas primero: las "
                "variantes parten de las que ya están en juego.")
        raise unprocessable(
            f"Ninguna de tus {len(aprobadas)} preguntas publicadas figura como escrita por ti "
            "(están marcadas como generadas por Runi). Puedes hacer variantes de todas igual.")

    existentes = {(p.enunciado or "").strip().lower()
                  for p in db.query(RetoPregunta).filter(
                      RetoPregunta.course_id == str(course_id)).all()}
    ya = len(existentes)
    from app.services import correccion_experta_service as ce
    nuevas, omitidas = [], 0
    for i in range(0, len(originales), _VARIANTES_POR_TANDA):
        tanda = originales[i:i + _VARIANTES_POR_TANDA]
        system, user = _prompt_variantes(curso or "el curso", contexto, tanda)
        crudas = []
        for intento in range(3):
            try:
                txt = ce._llamar_anthropic(system, user, max_tokens=5000)
                m = re.search(r"\{.*\}", txt or "", re.S)
                crudas = (json.loads(m.group(0)) if m else {}).get("variantes") or []
                if crudas:
                    break
            except Exception as e:  # noqa: BLE001
                _LOG.warning("reto: variantes intento %d/3 falló: %s", intento + 1, str(e)[:140])
        if not crudas:
            omitidas += len(tanda)
            continue
        por_n = {}
        for v in crudas:
            try:
                por_n[int(v.get("n"))] = v
            except (TypeError, ValueError):
                continue
        for n, orig in enumerate(tanda, start=1):
            v = por_n.get(n)
            if not v:
                omitidas += 1
                continue
            datos = _normalizar(v, {})
            if not datos or ya + len(nuevas) >= _MAX_BANCO:
                omitidas += 1
                continue
            if datos["enunciado"].strip().lower() in existentes:
                omitidas += 1          # salió igual que una que ya existe: no aporta nada
                continue
            existentes.add(datos["enunciado"].strip().lower())
            datos["tema"] = (str(v.get("tema") or orig.tema or "General"))[:160]
            datos["peso"] = orig.peso or 1
            nuevas.append(RetoPregunta(course_id=str(course_id), eval_id=orig.eval_id, **datos))
        db.commit()
    if nuevas:
        db.add_all(nuevas); db.commit()
    return {"ok": True, "creadas": len(nuevas), "originales": len(originales), "omitidas": omitidas}


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
# Ventanas en hora de Chile. Ninguna de noche.
_TZ_CHILE = -4          # solo como respaldo si falta la base de zonas horarias
_ZONA = "America/Santiago"
# Una tanda por HORA, de 08:00 a 19:00 (pedido del CEO). Ninguna de noche: la última abre a las
# 19:00 y cierra a las 20:00.
VENTANAS = tuple(range(8, 20))
DURACION_MIN = 60
# La dosificación ya NO la da el hueco entre ventanas —ahora son seguidas—, la da `POR_SESION`:
# son 3 preguntas y hasta la hora siguiente no hay más. Se responden en dos minutos y el resto de
# la hora no hay nada que hacer, que es justo lo que evita que se convierta en una lista de tareas.
#
# AVISOS cuatro veces al día, no doce: doce notificaciones diarias no crean el hábito, hacen que se
# silencie la app y con ella se pierden también los avisos del profesor. El tope y la separación
# viven en `AVISOS_POR_DIA` y `SEPARACION_MIN`, junto al barrido que los aplica; atarlos a horas
# fijas exigía una puntualidad que el disparador no tiene (ver `tick`).


def _a_utc(local):
    """De hora de Chile a UTC, respetando el horario de verano vigente ese dia."""
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        return local.replace(tzinfo=ZoneInfo(_ZONA)).astimezone(_dt.timezone.utc).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return local - _dt.timedelta(hours=_TZ_CHILE)


def _local(ahora=None):
    """La hora de Chile de verdad, con su horario de verano.

    Antes era `utcnow() + (-4)`. Un desfase fijo se rompe solo dos veces al ano: al entrar Chile en
    horario de verano las ventanas quedaron corridas una hora y la de las 21:00 paso a abrirse a las
    22:00 — que es de noche, justo lo que la regla prohibe. La zona la sabe el sistema.
    """
    import datetime as _dt
    base = (ahora or _dt.datetime.utcnow()).replace(tzinfo=_dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return base.astimezone(ZoneInfo(_ZONA)).replace(tzinfo=None)
    except Exception:  # noqa: BLE001 — sin base de zonas, el desfase fijo es mejor que nada
        return base.replace(tzinfo=None) + _dt.timedelta(hours=_TZ_CHILE)


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
            "desde_utc": _a_utc(desde) if desde else None,
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


def _para_repaso(db: Session, pseudo_id: str, banco: list, v: dict) -> list:
    """El orden de la segunda vuelta: primero lo que falló, después lo más antiguo.

    Se excluye lo respondido DENTRO de esta misma ventana: repetir la misma pregunta a los cinco
    minutos no es repasar, es un bucle.
    """
    previas = {r.pregunta_id: r for r in db.query(RetoRespuesta).filter(
        RetoRespuesta.pseudo_id == pseudo_id).all()}
    desde = v.get("desde_utc")
    fuera = []
    for p in banco:
        r = previas.get(p.id)
        if not r:
            continue
        if desde and r.created_at and r.created_at >= desde:
            continue                       # ya la vio en esta ventana
        fuera.append((0 if not r.correcta else 1, r.created_at or _EPOCA, p))
    fuera.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in fuera]


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
    repaso = False
    if not pendientes:
        # SEGUNDA VUELTA. Que se acabe el banco no puede ser el final: la estudiante volvería a
        # entrar y no encontraría nada, que es justo lo que este módulo existe para evitar. Se
        # vuelve a servir lo ya respondido, empezando por lo que FALLÓ y por lo más antiguo — que es
        # además lo que la práctica espaciada recomienda repasar.
        pendientes = _para_repaso(db, pseudo_id, banco, v)
        repaso = True
        if not pendientes:
            # Solo pasa si ya repasó todo el banco dentro de ESTA ventana.
            return {"ok": True, "preguntas": [], "sin_pendientes": True, "ventana": v,
                    "banco": len(banco), "respondidas": len(respondidas)}
    if not repaso:
        vacios = _vacios_de(db, pseudo_id)
        pendientes.sort(key=lambda p: _prioridad(p, vacios, pseudo_id))
    elegidas = pendientes[:n]
    for p in elegidas:
        p.veces_servida = int(p.veces_servida or 0) + 1
    db.commit()
    return {"ok": True, "sin_pendientes": False, "cerrado": False, "ventana": v, "repaso": repaso,
            "preguntas": [_dict(p) for p in elegidas],      # sin la correcta: se revela al responder
            "banco": len(banco), "respondidas": len(respondidas),
            "quedan": len(pendientes) - len(elegidas)}


def _anotar_intento(db: Session, p: RetoPregunta, pseudo_id: str, letra: str, acerto: bool,
                    course_id=None) -> None:
    """Deja el acta del intento. Nunca hace commit: viaja con la transacción de `responder`.

    Si esto falla, la respuesta de la estudiante NO se cae: perder una fila de auditoría es malo,
    pero mucho menos malo que dejarla mirando un error por haber contestado bien.
    """
    try:
        previos = db.query(RetoIntento).filter(RetoIntento.pseudo_id == pseudo_id,
                                               RetoIntento.pregunta_id == p.id).count()
        db.add(RetoIntento(course_id=str(course_id or p.course_id or ""), pregunta_id=p.id,
                           pseudo_id=pseudo_id, elegida=letra, correcta=acerto,
                           vuelta=int(previos) + 1))
    except Exception:  # noqa: BLE001
        _LOG.warning("No se pudo anotar el intento del reto", exc_info=True)


def responder(db: Session, pregunta_id, pseudo_id: str, elegida: str, course_id=None, ahora=None) -> dict:
    """Registra la respuesta y devuelve el veredicto con su justificación. Idempotente."""
    p = _buscar(db, pregunta_id)
    if p.estado != "aprobada":
        raise conflict("Esa pregunta no está disponible.")
    letra = str(elegida or "").strip().upper()[:1]
    if letra not in (p.alternativas or {}):
        raise unprocessable("Elige una de las alternativas.")

    ya = db.query(RetoRespuesta).filter(RetoRespuesta.pseudo_id == pseudo_id,
                                        RetoRespuesta.pregunta_id == p.id).first()
    v = ventana_de(ahora)
    acerto = (letra == p.correcta)
    if ya:
        # Dentro de la MISMA ventana no se puede cambiar la respuesta: sería adivinar hasta acertar.
        if not v.get("desde_utc") or (ya.created_at and ya.created_at >= v["desde_utc"]):
            return {"ok": True, "ya_respondida": True, "correcta": p.correcta,
                    "acerto": bool(ya.correcta), "elegida": ya.elegida,
                    "justificacion": p.justificacion}
        # Segunda vuelta: se actualiza el ESTADO. Una fila por par persona-pregunta, así «lo más
        # antiguo primero» sigue significando algo y el estado no se infla. La historia no se
        # pierde: el intento anterior ya quedó en `reto_intentos`, que solo crece.
        ya.elegida = letra
        ya.correcta = acerto
        ya.created_at = _dt.datetime.utcnow()
        if acerto:
            p.aciertos = int(p.aciertos or 0) + 1
        _anotar_intento(db, p, pseudo_id, letra, acerto, course_id)
        db.commit()
        return {"ok": True, "acerto": acerto, "correcta": p.correcta, "elegida": letra,
                "justificacion": p.justificacion, "repaso": True}

    db.add(RetoRespuesta(pregunta_id=p.id, pseudo_id=pseudo_id, elegida=letra, correcta=acerto))
    _anotar_intento(db, p, pseudo_id, letra, acerto, course_id)
    if acerto:
        p.aciertos = int(p.aciertos or 0) + 1
    try:
        db.commit()
    except Exception:  # noqa: BLE001 — dos pestañas a la vez; la unicidad ya nos protegió
        db.rollback()
        return responder(db, pregunta_id, pseudo_id, elegida, course_id, ahora)

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

    # Premio inmediato por acertar, solo en la primera vuelta. El repaso NO paga: si pagara, bastaría
    # con fallar a propósito y volver a acertar. `ref` incluye la pregunta, así que reintentar por un
    # error de red tampoco cobra dos veces.
    lumis = 0
    if acerto:
        try:
            from app.services import recompensa_service as rc
            lumis = int(rc.acreditar(db, pseudo_id, "reto", f"reto:{p.id}",
                                     detalle=f"Reto de {p.tema}").get("acreditado") or 0)
        except Exception:  # noqa: BLE001 — la respuesta ya está registrada; el premio es lo accesorio
            _LOG.warning("No se pudo acreditar el Lumin del reto", exc_info=True)

    return {"ok": True, "acerto": acerto, "correcta": p.correcta, "elegida": letra,
            "justificacion": p.justificacion, "lumis": lumis, "puntos": PUNTOS_ACIERTO if acerto else 0}


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
            # Con la segunda vuelta ya no se acaba: mientras haya banco y ventana abierta, hay algo.
            "hay_nuevos": banco > 0 and v["abierta"] and quedan_ventana > 0,
            "en_repaso": banco > 0 and hechas >= banco,
            "quedan_en_banco": banco - hechas, "quedan_en_ventana": quedan_ventana,
            "ventana": v}


# ── el aviso diario ───────────────────────────────────────────────────────────────────
# Ventana horaria en UTC. Chile está en UTC-4, así que 20:00–00:00 UTC es 16:00–20:00 allá: tarde,
# cuando alguien puede sentarse a estudiar. **Nunca de noche**: un recordatorio académico a las 2 AM
# no ayuda a nadie a aprender, solo entrena a silenciar la app.
# El aviso se manda al ABRIRSE cada ventana (ver VENTANAS). Se tolera un retraso: el barrido corre
# cada diez minutos y no siempre cae en el minuto exacto.


def _liquidar_podios(db: Session, ahora) -> int:
    """Cierra el día y paga el podio de cada curso, en la hora siguiente a la última ventana.

    Corre en el barrido que ya existe (cada 10 min) en vez de en un cron propio: un trabajo
    programado más es una cosa más que puede quedarse callada sin que nadie se entere. Se ejecuta
    varias veces dentro de esa hora a propósito —si un barrido falla, el siguiente cobra— y no paga
    dos veces porque la `ref` del movimiento lleva curso y fecha.
    """
    try:
        loc = _local(ahora)
        if loc.hour != VENTANAS[-1] + 1:      # justo después de que cierra la última ventana
            return 0
        cursos = {p.course_id for p in db.query(RetoPregunta).filter(
            RetoPregunta.estado == "aprobada").all()}
        return sum(cerrar_dia(db, cid, ahora).get("premiadas", 0) for cid in cursos)
    except Exception:  # noqa: BLE001 — el reparto no puede tumbar los avisos del profesor
        _LOG.warning("No se pudieron liquidar los podios del reto", exc_info=True)
        return 0


AVISOS_POR_DIA = 4          # tope: más que esto y se silencia la app, con los avisos del profesor dentro
SEPARACION_MIN = 140        # ~2 h 20 entre avisos, para que no lleguen en ráfaga si el barrido se atrasa


def _marca(dia: str, loc) -> str:
    """La marca del aviso: «2026-09-22#1205». Son 15 caracteres a propósito — `PushSent.hito` es
    VARCHAR(20), y un ISO completo (36) lo desborda: Postgres lo rechaza y SQLite lo recorta en
    silencio, que es peor porque los tests pasarían igual."""
    return f"{dia}#{loc:%H%M}"


def _avisos_de_hoy(db, ref: str, owner_key: str, dia: str) -> list:
    """Las horas a las que ya se avisó hoy a esa persona en ese curso, en orden."""
    from app.models.push import PushSent
    filas = db.query(PushSent).filter(PushSent.eval_id == ref, PushSent.owner_key == owner_key,
                                      PushSent.hito.like(dia + "#%")).all()
    out = []
    for r in filas:
        try:
            hhmm = str(r.hito).split("#", 1)[1]
            out.append(_dt.datetime.strptime(f"{dia} {hhmm}", "%Y-%m-%d %H%M"))
        except (ValueError, IndexError):
            continue
    return sorted(out)


def tick(db: Session, ahora=None) -> dict:
    """Avisa de los retos abiertos. Hasta `AVISOS_POR_DIA`, separados entre sí.

    ANTES esto exigía que el barrido cayera en una de cuatro horas exactas y dentro de sus primeros
    25 minutos. Medido sobre 60 barridos reales de 10 días: GitHub, que es quien los dispara, ignora
    el `*/10` y corre cada ~3,5 horas (hasta 6,8). Solo 8 de 60 cayeron a tiempo — menos de un aviso
    al día en vez de cuatro. El reto estaba abierto cada hora y nadie se enteraba.
    
    La corrección no es pedirle puntualidad al disparador: es dejar de depender de ella. Ahora avisa
    cuando el barrido pase y haya una ventana abierta, siempre que hayan pasado `SEPARACION_MIN`
    desde el aviso anterior y no se haya llegado al tope del día. El límite lo pone el reloj del
    último aviso, no el del barrido. Como efecto lateral deja de importar el horario de verano, que
    con horas fijas en UTC corría los avisos una hora dos veces al año.
    """
    import datetime as _dt
    ahora = ahora or _dt.datetime.utcnow()
    premiadas = _liquidar_podios(db, ahora)
    v = ventana_de(ahora)
    if not v["abierta"]:
        return {"ok": True, "fuera_de_hora": True, "avisados": 0, "premiadas": premiadas}
    loc = _local(ahora)
    dia = loc.date().isoformat()
    hoy = _marca(dia, loc)              # la marca lleva la hora REAL del aviso, no la de la ventana

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
            previos = _avisos_de_hoy(db, ref, f.owner_key, dia)
            if len(previos) >= AVISOS_POR_DIA:
                continue
            if previos and (loc.replace(tzinfo=None) - previos[-1]) < _dt.timedelta(minutes=SEPARACION_MIN):
                continue
            db.add(PushSent(eval_id=ref, owner_key=f.owner_key, hito=hoy))
            db.commit()
            try:
                avisados += ps.enviar_a_owner(db, f.owner_key, payload_push(len(banco), v))
            except Exception:  # noqa: BLE001 — un push caído no deja el barrido a medias
                pass
    return {"ok": True, "avisados": avisados, "premiadas": premiadas}


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
# Formas de marcar la respuesta correcta en Word, en orden de intención. El docente marca como
# sabe: unos con el resaltador, otros pintando la letra de verde, otros subrayando o poniendo en
# negrita. Antes solo se leía el resaltador y una pauta marcada en verde se rechazaba entera con
# «no encontré preguntas con su alternativa marcada» — lo que es literalmente falso: estaban todas
# marcadas, solo que de otra manera.
_SENALES = ("resaltado", "color", "subrayado", "negrita")


def _senales_de(p: str) -> set:
    """Qué marcas de formato lleva este párrafo."""
    import re as _re
    out = set()
    if _re.search(r'w:highlight[^>]*w:val="(?!none)', p):
        out.add("resaltado")
    # El negro y el "automático" no son una marca: son el color por defecto del documento.
    for c in _re.findall(r'<w:color w:val="([0-9A-Fa-f]{6}|auto)"', p):
        if c.lower() not in ("auto", "000000"):
            out.add("color")
    if _re.search(r'<w:u [^>]*w:val="(?!none)', p):
        out.add("subrayado")
    if _re.search(r"<w:b[ /]", p) and not _re.search(r'<w:b w:val="(0|false)', p):
        out.add("negrita")
    return out


def _docx_parrafos(datos: bytes) -> list:
    """(texto, marcas) por párrafo del .docx."""
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
            out.append((texto, _senales_de(p)))
    return out


def _cual_esta_marcada(alts: list) -> str | None:
    """De las alternativas de UNA pregunta, cuál está marcada distinto de sus hermanas.

    La clave es «distinto de sus hermanas», no «tiene tal formato». Si el docente pone en negrita
    las cuatro alternativas, la negrita no señala nada; si pone una sola en verde, esa es. Mirar el
    grupo y no el párrafo suelto es lo que permite aceptar cualquier convención sin inventarse una
    respuesta cuando no hay ninguna marca real.
    """
    for senal in _SENALES:
        con = [letra for letra, _txt, marcas in alts if senal in marcas]
        if len(con) == 1:
            return con[0]
    return None


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
    """Lee «1. enunciado / a) … b) …» con la correcta marcada. Devuelve preguntas listas.

    Qué cuenta como «marcada» no se decide por párrafo sino comparando las alternativas de cada
    pregunta entre sí: la que va distinta de sus hermanas es la respuesta, se haya marcado con el
    resaltador, con color de letra, subrayando o en negrita.
    """
    re_en, re_alt = _regex()
    preguntas, actual = [], None

    def _cerrar(q):
        if not q or len(q["alts"]) < 2:
            return
        letra = _cual_esta_marcada(q["alts"])
        if not letra:
            return
        preguntas.append({"enunciado": q["enunciado"], "tema": q["tema"], "correcta": letra,
                          "alternativas": {L: t for L, t, _m in q["alts"]}})

    for texto, marcas in _docx_parrafos(datos):
        m = re_alt.match(texto)
        if m and actual is not None:
            letra = m.group(1).upper()
            # Si esa letra YA existe, empezó otro bloque que no se reconoció como enunciado:
            # sobrescribirla corrompería en silencio la pregunta anterior. Se ignora.
            if letra not in {L for L, _t, _m in actual["alts"]}:
                actual["alts"].append((letra, m.group(2).strip()[:300], marcas))
            continue
        m = re_en.match(texto)
        if m:
            _cerrar(actual)
            actual = {"enunciado": m.group(2).strip()[:1200], "alts": [], "tema": tema_defecto}
    _cerrar(actual)
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
        # El mensaje anterior decía lo mismo para dos problemas distintos —no reconocí el formato
        # / lo reconocí pero no hay nada marcado— y mandaba a «resaltar», que es solo una de las
        # cuatro formas válidas. Con 32 enunciados leídos y cero marcas, decir «no encontré
        # preguntas» es directamente falso y deja al docente sin saber qué tocar.
        n = _contar_enunciados(datos)
        if not n:
            raise unprocessable(
                "No reconocí ninguna pregunta. Cada una tiene que empezar por su número —«1.» o "
                "«1)»— y debajo las alternativas, una por línea, empezando por «A.», «a)» o similar.")
        raise unprocessable(
            f"Leí {n} preguntas, pero en ninguna hay una alternativa marcada distinto de las otras. "
            "Marca la correcta como prefieras —resaltada, en negrita, subrayada o de otro color—; "
            "lo único que importa es que vaya distinta de sus compañeras de esa misma pregunta.")

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


# ── trazabilidad: qué pasó con cada pregunta ──────────────────────────────────────────
# El CEO preguntó si había trazabilidad de las respuestas. La había en la base y no la veía nadie:
# `reto_respuestas` solo se consultaba filtrando por `pseudo_id`, es decir, cada alumna mirando lo
# suyo. Esto es lo que faltaba, y va deliberadamente SIN NOMBRES: al docente le sirve saber que una
# pregunta la falla el 70% y que se van a la C, no quién se fue a la C. Su regla, no la mía.
_MIN_PARA_MOSTRAR = 3     # bajo esto, un porcentaje es ruido disfrazado de dato


def analisis(db: Session, course_id) -> dict:
    """Por pregunta: cuántas la respondieron, cuántas acertaron y a qué distractor se fueron.

    Se lee de `reto_intentos` (el acta) y no de `reto_respuestas` (el estado), porque el estado se
    sobreescribe en la segunda vuelta: contando ahí, un error corregido después desaparece y la
    pregunta parece más fácil de lo que fue.
    """
    cid = str(course_id)
    preguntas = {p.id: p for p in db.query(RetoPregunta).filter(RetoPregunta.course_id == cid).all()}
    if not preguntas:
        return {"ok": True, "preguntas": [], "resumen": {"intentos": 0, "personas": 0}}

    filas = (db.query(RetoIntento).filter(RetoIntento.pregunta_id.in_(list(preguntas.keys())))
             .order_by(RetoIntento.created_at.asc()).all())

    por_pregunta: dict = {}
    personas, corregidos, reincidentes = set(), 0, 0
    # Para «falló y después acertó» hace falta mirar los intentos de cada par en orden.
    trayecto: dict = {}
    for r in filas:
        personas.add(r.pseudo_id)
        d = por_pregunta.setdefault(r.pregunta_id, {"intentos": 0, "aciertos": 0, "elecciones": {},
                                                    "personas": set(), "ultimo": None})
        d["intentos"] += 1
        d["personas"].add(r.pseudo_id)
        if r.correcta:
            d["aciertos"] += 1
        letra = (r.elegida or "?").upper()
        d["elecciones"][letra] = d["elecciones"].get(letra, 0) + 1
        if r.created_at:
            d["ultimo"] = r.created_at.isoformat()
        t = trayecto.setdefault((r.pseudo_id, r.pregunta_id), [])
        t.append(bool(r.correcta))

    for pasos in trayecto.values():
        if len(pasos) > 1 and not pasos[0]:
            corregidos += 1 if pasos[-1] else 0
            reincidentes += 0 if pasos[-1] else 1

    salida = []
    for pid, p in preguntas.items():
        d = por_pregunta.get(pid)
        n = d["intentos"] if d else 0
        aciertos = d["aciertos"] if d else 0
        elec = d["elecciones"] if d else {}
        # El distractor que más arrastra: la alternativa incorrecta más elegida. Es el dato que
        # dice QUÉ entendieron mal, no solo que fallaron.
        malas = {k: v for k, v in elec.items() if k != p.correcta}
        top = max(malas.items(), key=lambda kv: kv[1]) if malas else None
        salida.append({
            "id": str(pid), "tema": p.tema, "nivel": p.nivel, "estado": p.estado, "origen": p.origen,
            "enunciado": p.enunciado, "alternativas": p.alternativas or {}, "correcta": p.correcta,
            "intentos": n, "personas": len(d["personas"]) if d else 0, "aciertos": aciertos,
            # `None` en vez de 0: «nadie la ha respondido» y «la falla todo el mundo» no son lo
            # mismo, y pintar 0% en una pregunta sin datos sería mentirle al profesor.
            "acierto_pct": round(100 * aciertos / n) if n >= _MIN_PARA_MOSTRAR else None,
            "suficiente": n >= _MIN_PARA_MOSTRAR,
            "elecciones": elec,
            "distractor": ({"letra": top[0], "texto": (p.alternativas or {}).get(top[0], ""),
                            "n": top[1], "pct": round(100 * top[1] / n)} if top and n else None),
            "ultimo": d["ultimo"] if d else None,
        })
    # Lo más fallado primero: es la lista de lo que hay que repasar antes de la prueba. Las que
    # nadie respondió van al final, no arriba fingiendo ser un problema.
    salida.sort(key=lambda q: (q["acierto_pct"] is None, q["acierto_pct"] if q["acierto_pct"] is not None else 101))
    return {"ok": True, "preguntas": salida,
            "resumen": {"intentos": len(filas), "personas": len(personas),
                        "preguntas_con_datos": sum(1 for q in salida if q["suficiente"]),
                        "corregidos": corregidos, "reincidentes": reincidentes,
                        "minimo": _MIN_PARA_MOSTRAR}}


# ── puntaje, tabla y premios ──────────────────────────────────────────────────────────
# El CEO pidió premios «de acuerdo a las mejores puntuaciones». Eso es comparar estudiantes, y su
# propia regla del sistema de recompensas fue «sin ranking, solo meta personal». La tabla existe,
# entonces, bajo una condición que aquí es código y no promesa: **nunca sale un nombre ni un RUT**.
# El alias se DERIVA del pseudónimo con un hash; no se lee de ningún campo que una persona pueda
# rellenar, así que no hay forma de que se cuele un dato real por descuido de nadie.
PUNTOS_ACIERTO = 10
LUMIS_ACIERTO = 5                 # premio inmediato: todas ganan algo por acertar
LUMIS_PODIO = (50, 30, 20)        # premio del día a las tres mejores
_ANIMALES = ("Zorro", "Puma", "Cóndor", "Nutria", "Alpaca", "Chinchilla", "Pudú", "Guanaco",
             "Flamenco", "Quirquincho", "Coipo", "Huemul", "Tucúquere", "Vizcacha", "Degú", "Loica")


def alias_de(pseudo_id: str) -> str:
    """Un apodo estable y sin PII. Determinista: la misma persona es siempre el mismo animal."""
    h = hashlib.sha256(("alias|" + str(pseudo_id or "")).encode()).hexdigest()
    return f"{_ANIMALES[int(h[:4], 16) % len(_ANIMALES)]} {int(h[4:8], 16) % 90 + 10}"


def _puntos(db: Session, course_id, desde=None) -> dict:
    """Puntos por persona. Solo cuenta el PRIMER intento de cada pregunta.

    Si contara el repaso, bastaría con fallar a propósito y volver a acertar para subir sin límite,
    y la tabla premiaría la insistencia en vez de saber. Con la primera vuelta cada pregunta paga
    una sola vez y el puntaje mide lo que dice medir.
    """
    ids = {p.id for p in db.query(RetoPregunta).filter(
        RetoPregunta.course_id == str(course_id), RetoPregunta.estado == "aprobada").all()}
    if not ids:
        return {}
    q = db.query(RetoIntento).filter(RetoIntento.pregunta_id.in_(list(ids)), RetoIntento.vuelta == 1)
    if desde is not None:
        q = q.filter(RetoIntento.created_at >= desde)
    out: dict = {}
    for r in q.all():
        d = out.setdefault(r.pseudo_id, {"puntos": 0, "aciertos": 0, "respondidas": 0, "ultimo": None})
        d["respondidas"] += 1
        if r.correcta:
            d["aciertos"] += 1
            d["puntos"] += PUNTOS_ACIERTO
        if r.created_at and (d["ultimo"] is None or r.created_at > d["ultimo"]):
            d["ultimo"] = r.created_at
    return out


def _ordenar(puntos: dict) -> list:
    """Más puntos primero. A igualdad gana quien lo logró con menos intentos (más precisión), y si
    persiste el empate, quien llegó antes: nunca al azar, porque de esto cuelga un premio."""
    filas = [{"pseudo_id": k, **v} for k, v in puntos.items()]
    filas.sort(key=lambda f: (-f["puntos"], f["respondidas"],
                              f["ultimo"] or _dt.datetime.max))
    for i, f in enumerate(filas):
        f["puesto"] = i + 1
    return filas


def tabla(db: Session, course_id, pseudo_id: str = "", tope: int = 10, hoy: bool = False,
          ahora=None) -> dict:
    """La tabla de posiciones, con alias. `pseudo_id` marca cuál fila es la de quien pregunta."""
    desde = None
    if hoy:
        loc = _local(ahora or _dt.datetime.utcnow())
        desde = _a_utc(loc.replace(hour=0, minute=0, second=0, microsecond=0))
    filas = _ordenar(_puntos(db, course_id, desde))
    def _fila(f):
        return {"puesto": f["puesto"], "alias": alias_de(f["pseudo_id"]), "puntos": f["puntos"],
                "aciertos": f["aciertos"], "respondidas": f["respondidas"],
                "yo": bool(pseudo_id) and f["pseudo_id"] == pseudo_id}
    top = [_fila(f) for f in filas[:max(1, min(int(tope or 10), 50))]]
    # Su propia fila SIEMPRE viaja, esté o no en el podio: una tabla donde no te encuentras
    # desmotiva justo a quien más necesita ver que va avanzando.
    yo = next((_fila(f) for f in filas if f["pseudo_id"] == pseudo_id), None) if pseudo_id else None
    return {"ok": True, "tabla": top, "yo": yo, "participantes": len(filas),
            "premios": list(LUMIS_PODIO), "por_acierto": LUMIS_ACIERTO}


def cerrar_dia(db: Session, course_id, ahora=None) -> dict:
    """Reparte el premio del día a las tres mejores. Idempotente: `ref` lleva curso y fecha.

    Se liquida en el SERVIDOR y no al abrir una pantalla: si el premio dependiera de que alguien
    mire la tabla, quien no la abre no cobra, y eso no es un premio sino una trampa.
    """
    loc = _local(ahora or _dt.datetime.utcnow())
    dia = loc.date().isoformat()
    desde = _a_utc(loc.replace(hour=0, minute=0, second=0, microsecond=0))
    filas = [f for f in _ordenar(_puntos(db, course_id, desde)) if f["puntos"] > 0][:len(LUMIS_PODIO)]
    if not filas:
        return {"ok": True, "premiadas": 0, "dia": dia}
    from app.services import recompensa_service as rc
    premiadas = 0
    for f in filas:
        r = rc.acreditar(db, f["pseudo_id"], "podio", f"podio:{course_id}:{dia}:{f['puesto']}",
                         monto=LUMIS_PODIO[f["puesto"] - 1],
                         detalle=f"Puesto {f['puesto']} del reto · {dia}")
        premiadas += 1 if r.get("acreditado") else 0
    return {"ok": True, "premiadas": premiadas, "dia": dia,
            "podio": [{"alias": alias_de(f["pseudo_id"]), "puesto": f["puesto"],
                       "puntos": f["puntos"]} for f in filas]}


# ── ponerle tema a un banco que quedó todo bajo «General» ──────────────────────────────
# Al importar la pauta, el campo «tema» iba vacío y las 56 preguntas quedaron con el relleno
# «General». Eso no es cosmético: el reto prioriza por tema, el panel agrupa por tema y la escalera
# de repaso construye su consigna con el tema. Con todo en un saco, la estudiante acabó leyendo
# «Sin mirar apuntes, explica con tus palabras: General», que no significa nada.
TEMAS_RELLENO = ("", "general", "sin clasificar", "tu tema", "otro", "varios", "n/a")
_CLASIFICAR_POR_TANDA = 10


def es_tema_relleno(tema: str) -> bool:
    return str(tema or "").strip().lower() in TEMAS_RELLENO


def clasificar_temas(db: Session, course_id, contexto: str, curso: str = "",
                     temas_txt: str = "", solo_relleno: bool = True) -> dict:
    """Le pone a cada pregunta el tema que le corresponde, leyéndolo del enunciado.

    Toca SOLO el campo `tema`. No reescribe enunciados, ni alternativas, ni cuál es la correcta:
    la pregunta que el profesor aprobó sigue siendo exactamente la que aprobó.
    """
    import json
    import os
    import re
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise conflict("El motor de IA no está disponible ahora mismo.")

    todas = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id)).all()
    pendientes = [p for p in todas if not solo_relleno or es_tema_relleno(p.tema)]
    if not pendientes:
        raise unprocessable("Todas tus preguntas ya tienen un tema propio.")

    # Si el docente escribió su lista de temas, se usa esa y no una inventada: son los temas de SU
    # tabla de especificaciones, los que después tiene que poder reconocer en el panel.
    sugeridos = [t["tema"] for t in _temas_desde(temas_txt)]
    if not sugeridos:
        sugeridos = sorted({p.tema for p in todas if not es_tema_relleno(p.tema)})

    from app.services import correccion_experta_service as ce
    system = (
        f"Clasificas preguntas de {curso or 'un curso universitario'} por tema.\n"
        + (("Usa EXCLUSIVAMENTE estos temas:\n- " + "\n- ".join(sugeridos) + "\n")
           if sugeridos else
           "Propon un tema corto (2 a 5 palabras) para cada pregunta, del contenido del curso.\n")
        + "Un tema nombra una estructura o un contenido concreto ('Drenaje linfático de la mama'), "
        "nunca una categoría vacía como 'General', 'Varios' u 'Otro'.\n"
        'Devuelve SOLO JSON: {"temas":[{"n":1,"tema":"…"}]} usando el número que acompaña a cada pregunta.')

    cambiadas, sin_clasificar = 0, 0
    for i in range(0, len(pendientes), _CLASIFICAR_POR_TANDA):
        tanda = pendientes[i:i + _CLASIFICAR_POR_TANDA]
        user = ("MATERIAL DEL CURSO (para ubicar los temas):\n" + (contexto or "")[:12000]
                + "\n\nPREGUNTAS:\n"
                + "\n".join(f"{k + 1}. {(p.enunciado or '')[:400]}" for k, p in enumerate(tanda)))
        try:
            txt = ce._llamar_anthropic(system, user, max_tokens=2000)
            m = re.search(r"\{.*\}", txt or "", re.S)
            filas = (json.loads(m.group(0)) if m else {}).get("temas") or []
        except Exception as e:  # noqa: BLE001 — una tanda caída no arrastra a las demás
            _LOG.warning("clasificar_temas: tanda %d falló: %s", i, str(e)[:140])
            sin_clasificar += len(tanda)
            continue
        vistos = set()
        for fila in filas:
            try:
                k = int(fila.get("n", 0)) - 1
            except (TypeError, ValueError):
                continue
            tema = str(fila.get("tema") or "").strip()[:160]
            # Un tema de relleno devuelto por el modelo se descarta: preferimos dejarla como estaba
            # antes que cambiar «General» por «Varios» y llamar a eso un arreglo.
            if not (0 <= k < len(tanda)) or es_tema_relleno(tema) or k in vistos:
                continue
            vistos.add(k)
            tanda[k].tema = tema
            cambiadas += 1
        sin_clasificar += len(tanda) - len(vistos)
    db.commit()
    resumen: dict = {}
    for p in db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id)).all():
        resumen[p.tema] = resumen.get(p.tema, 0) + 1
    return {"ok": True, "clasificadas": cambiadas, "sin_clasificar": sin_clasificar,
            "temas": sorted(resumen.items(), key=lambda kv: -kv[1])}


def salud_avisos(db: Session, course_id, ahora=None) -> dict:
    """¿Está llegando el reto a alguien? Pensado para responderlo SIN preguntarle a nadie.

    El CEO preguntó «¿Runi está enviando las preguntas?» y no había forma de comprobarlo desde la
    plataforma: había que leer el código y los registros de GitHub. Esto lo contesta de una mirada,
    y separa las tres cosas que pueden fallar, que son distintas y se arreglan distinto:
      1. no hay banco publicado          → el docente aprueba preguntas
      2. nadie activó las notificaciones → la alumna toca «Que Runi te avise»
      3. el barrido no está pasando      → el disparador (GitHub) dejó de correr
    """
    from app.models.push import PushSent, PushSubscription, StudentCourseFollow
    ahora = ahora or _dt.datetime.utcnow()
    loc = _local(ahora)
    cid = str(course_id)
    banco = db.query(RetoPregunta).filter(RetoPregunta.course_id == cid,
                                          RetoPregunta.estado == "aprobada").count()
    try:
        seguidores = db.query(StudentCourseFollow).filter(
            StudentCourseFollow.course_id == _uuid.UUID(cid)).all()
    except (ValueError, TypeError, AttributeError):
        seguidores = []
    owners = {f.owner_key for f in seguidores}
    con_push = {s.owner_key for s in db.query(PushSubscription).filter(
        PushSubscription.owner_key.in_(list(owners) or [""])).all()} if owners else set()

    ref = f"reto:{cid}"
    enviados = db.query(PushSent).filter(PushSent.eval_id == ref).all()
    hoy = loc.date().isoformat()
    de_hoy = [e for e in enviados if str(e.hito).startswith(hoy + "#")]
    ultimo = max((e.created_at for e in enviados if e.created_at), default=None)

    v = ventana_de(ahora)
    if not banco:
        estado, que_hacer = "sin_banco", "Publica preguntas: sin banco aprobado no hay nada que enviar."
    elif not owners:
        estado, que_hacer = "sin_seguidores", "Nadie ha abierto el curso todavía desde su enlace."
    elif not con_push:
        estado, que_hacer = ("sin_permiso",
                             "Tus estudiantes siguen el curso pero ninguna activó las notificaciones. "
                             "Se activan desde la app, en «Que Runi te avise».")
    elif not enviados:
        estado, que_hacer = ("nunca_enviado",
                             "Todo está listo y aún no ha salido ningún aviso. Si sigue así mañana, "
                             "el barrido no está pasando.")
    else:
        estado, que_hacer = "enviando", ""
    return {"ok": True, "estado": estado, "que_hacer": que_hacer,
            "banco": banco, "seguidores": len(owners), "con_notificaciones": len(con_push),
            "avisos_hoy": len(de_hoy), "avisos_total": len(enviados),
            "ultimo_aviso": ultimo.isoformat() if ultimo else None,
            "tope_diario": AVISOS_POR_DIA, "separacion_min": SEPARACION_MIN,
            "ahora_local": loc.strftime("%Y-%m-%d %H:%M"), "ventana": v,
            "por_sesion": POR_SESION,
            # La IA no entra aquí: las preguntas ya están escritas en la base.
            "necesita_ia": False}


# ── barajar las alternativas ──────────────────────────────────────────────────────────
# En la pauta del CEO el 87% de las claves caían en A o B, y solo una en D. Quien marque siempre
# «B» sin leer saca 43%. Eso no mide anatomía, mide haber notado el patrón.
#
# Dos trampas que no se ven a simple vista:
#  1. Una alternativa como «todas las anteriores» depende del ORDEN. Barajarla la rompe, así que
#     esas preguntas se dejan intactas.
#  2. `RetoRespuesta.elegida` y `RetoIntento.elegida` guardan una LETRA. Si se baraja sin más, cada
#     respuesta ya registrada pasa a apuntar a otro texto: el acta de intentos, el porcentaje de
#     acierto y el distractor más votado quedan mintiendo, en silencio y sin arreglo posible. Por
#     eso se reescriben con el mismo mapeo.
_re_ref = None


def _es_referencial(texto: str) -> bool:
    """¿Esta alternativa habla de las OTRAS? Entonces su sitio en la lista es parte del enunciado."""
    global _re_ref
    if _re_ref is None:
        import re as _re
        _re_ref = _re.compile(
            r"(todas|ninguna|ambas|algunas)\s+(de\s+)?(las|los)?\s*(anteriores|opciones|alternativas)"
            r"|\b[a-e]\s+y\s+[a-e]\b|son correctas|es correcta", _re.I)
    return bool(_re_ref.search(str(texto or "")))


def barajar(db: Session, course_id) -> dict:
    """Redistribuye las alternativas para que la correcta no se concentre en una letra.

    No sortea a ciegas: reparte a propósito. A cada pregunta le toca, de las letras que tiene, la
    que menos veces lleva usada como correcta hasta ese momento. Un barajado al azar volvería a
    amontonarlas por pura suerte, que es justo el problema que se viene a resolver.
    """
    import random
    filas = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id)).all()
    if not filas:
        raise unprocessable("Este curso no tiene preguntas que barajar.")

    usos: dict = {}
    barajadas, intactas, respuestas_movidas = 0, 0, 0
    for p in filas:
        alts = dict(p.alternativas or {})
        if len(alts) < 2 or p.correcta not in alts:
            intactas += 1
            continue
        if any(_es_referencial(t) for t in alts.values()):
            intactas += 1          # su orden es parte de lo que preguntan
            continue

        letras = sorted(alts)
        # A la correcta le toca la letra menos usada; a igualdad, al azar, para no crear otro patrón.
        destino = min(letras, key=lambda L: (usos.get(L, 0), random.random()))
        otras = [L for L in letras if L != destino]
        # Se barajan las LETRAS de origen, no los textos. Barajar los textos y después emparejar
        # las letras por su orden original daba un mapa equivocado en cuanto la permutación movía
        # algo: el texto acababa donde tocaba, pero «old → new» apuntaba a otra parte y las
        # respuestas ya dadas se reescribían mal. Un solo recorrido construye las dos cosas a la
        # vez, así no pueden discrepar.
        fuentes = [L for L in letras if L != p.correcta]
        random.shuffle(fuentes)

        nuevo = {destino: alts[p.correcta]}
        mapa = {p.correcta: destino}                 # old → new, para las respuestas ya registradas
        for origen, llega_a in zip(fuentes, otras):
            nuevo[llega_a] = alts[origen]
            mapa[origen] = llega_a
        if nuevo == alts and destino == p.correcta:
            # Le tocó el orden que ya tenía. No hay nada que reescribir, pero esa letra SÍ queda
            # ocupada: si no se cuenta, el reparto de las siguientes se calcula con datos viejos.
            usos[destino] = usos.get(destino, 0) + 1
            intactas += 1
            continue

        p.alternativas = nuevo
        p.correcta = destino
        usos[destino] = usos.get(destino, 0) + 1
        barajadas += 1
        for modelo in (RetoRespuesta, RetoIntento):
            for r in db.query(modelo).filter(modelo.pregunta_id == p.id).all():
                if r.elegida in mapa:
                    r.elegida = mapa[r.elegida]
                    respuestas_movidas += 1
    db.commit()

    reparto: dict = {}
    for p in db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id),
                                           RetoPregunta.estado == "aprobada").all():
        reparto[p.correcta] = reparto.get(p.correcta, 0) + 1
    return {"ok": True, "barajadas": barajadas, "intactas": intactas,
            "respuestas_actualizadas": respuestas_movidas,
            "reparto": dict(sorted(reparto.items()))}


def reparto_de_claves(db: Session, course_id) -> dict:
    """Cuántas correctas caen en cada letra, y si eso se puede adivinar sin leer."""
    filas = db.query(RetoPregunta).filter(RetoPregunta.course_id == str(course_id),
                                          RetoPregunta.estado == "aprobada").all()
    reparto: dict = {}
    for p in filas:
        reparto[p.correcta] = reparto.get(p.correcta, 0) + 1
    n = len(filas)
    top = max(reparto.values()) if reparto else 0
    # Con 4 alternativas el azar da 25%. Por encima de 40% la letra ya es una pista.
    return {"reparto": dict(sorted(reparto.items())), "total": n,
            "mejor_pct": round(100 * top / n) if n else 0,
            "sesgado": bool(n >= 8 and top / n > 0.40)}
