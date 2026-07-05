"""
F4 - Aprendizaje de calibracion (la IA aprende del briefing docente).

Cierra el lazo F3 -> F2: las validaciones del docente (donde AJUSTO a la IA) son la
senal de aprendizaje. Pero un sistema de evaluacion serio es flexible SIN dejar de ser
consistente y replicable. Por eso el aprendizaje aqui NO es deriva continua: es un ciclo
gobernado en cuatro pasos, versionado por saltos y con compuerta humana.

    1. extraer_senales   : mina los ajustes del docente, los agrupa por criterio y
                           direccion, cuenta recurrencia y guarda evidencia seudonimizada.
    2. proponer_ajustes  : convierte senales en propuestas de REGLA y les corre los
                           guardrails (generalizable, recurrente, consistente con la norma
                           disciplinar). Relajar la norma exige override docente explicito.
    3. [docente]         : aprueba/rechaza cada propuesta (G1: aprueba la regla, no solo
                           la nota). Nada aprende en silencio.
    4. aplicar_ajustes   : produce una version NUEVA de la rubrica (hash de contenido,
                           changelog). La version anterior queda congelada -> el pasado
                           sigue reproducible (replicabilidad).

curva_aprendizaje mide el QWK IA<->docente por version: la evidencia replicable de que la
IA de verdad convergio hacia el criterio docente, y no solo cambio.

Determinista y sin dependencias externas (hashlib + json): dos corridas identicas dan
exactamente el mismo hash y las mismas propuestas.
"""
from __future__ import annotations

import hashlib
import json

# --- Tipos de ajuste que la IA puede aprender -------------------------------------------
TIPO_SINONIMO = "sinonimo_aceptado"       # aceptar un termino como equivalente
TIPO_ANALOGIA = "analogia_valida"         # aceptar una analogia/parafrasis que expresa el concepto
TIPO_ANCLA = "ancla_nueva"                # anadir una respuesta validada como ejemplar (few-shot)
TIPO_ALCANCE = "alcance_ampliado"         # ampliar lo que cuenta como en-alcance
TIPO_PRECISION = "precision_terminologica"  # exigir el termino estandar (endurece hacia la norma)
TIPO_ENDURECIDO = "criterio_endurecido"   # subir la vara del criterio

RELAJANTES = {TIPO_SINONIMO, TIPO_ANALOGIA, TIPO_ALCANCE}   # amplian la aceptacion
ENDURECEN = {TIPO_PRECISION, TIPO_ENDURECIDO}               # la restringen (hacia la norma)

_ORDEN = {"no_logrado": 0, "parcial": 1, "logrado": 2}


# --- Utilidades de replicabilidad / privacidad ------------------------------------------
def hash_criterios(criterios: list[dict]) -> str:
    """Hash de contenido estable (canonico) del conjunto de criterios -> identidad de version."""
    payload = json.dumps(criterios, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _pseudo(ref: str) -> str:
    """Seudonimiza una referencia de respuesta (G2): estable pero sin identidad."""
    return "resp:" + hashlib.sha256(str(ref).encode("utf-8")).hexdigest()[:8]


def _clasifica(direccion: str, comentario: str | None) -> str:
    c = (comentario or "").lower()
    if direccion == "sube":   # la IA fue demasiado estricta
        if any(k in c for k in ("analog", "ejemplo", "metafor", "otra forma", "acorde", "parafras")):
            return TIPO_ANALOGIA
        if any(k in c for k in ("sinonim", "equivale", "termino", "mismo que", "igual que", "tambien vale")):
            return TIPO_SINONIMO
        if any(k in c for k in ("alcance", "tambien cuenta", "es valido", "se acepta", "abarca")):
            return TIPO_ALCANCE
        return TIPO_ANCLA     # subida sin pista textual -> guardar como ejemplar (lo mas seguro)
    # baja: la IA fue demasiado indulgente
    if any(k in c for k in ("termino", "precis", "norma", "nomenclat", "correcto es", "estandar")):
        return TIPO_PRECISION
    return TIPO_ENDURECIDO


# --- Paso 1: extraer senales de las validaciones docentes -------------------------------
def extraer_senales(registros: list[dict]) -> list[dict]:
    """
    De los registros de F3 (con accion/nivel_ia/nivel_docente/comentario/respuesta_ref),
    toma solo los AJUSTADOS, los agrupa por (criterio, tipo, direccion) y cuenta recurrencia.
    La evidencia se guarda seudonimizada (G2).
    """
    grupos: dict[tuple, dict] = {}
    for r in registros:
        if r.get("accion") != "ajustado":
            continue
        ni, nd = r.get("nivel_ia"), r.get("nivel_docente")
        if ni not in _ORDEN or nd not in _ORDEN or _ORDEN[nd] == _ORDEN[ni]:
            continue
        direccion = "sube" if _ORDEN[nd] > _ORDEN[ni] else "baja"
        tipo = _clasifica(direccion, r.get("comentario"))
        crit = r.get("criterio", "?")
        g = grupos.setdefault((crit, tipo, direccion), {
            "criterio": crit, "tipo": tipo, "direccion": direccion,
            "evidencia": [], "comentarios": [],
        })
        g["evidencia"].append(_pseudo(r.get("respuesta_ref") or f"{crit}:{len(g['evidencia'])}"))
        if r.get("comentario"):
            g["comentarios"].append(r["comentario"])

    senales = []
    for g in grupos.values():
        g["evidencia"] = sorted(set(g["evidencia"]))
        g["recurrencia"] = len(g["evidencia"])
        senales.append(g)
    senales.sort(key=lambda s: (-s["recurrencia"], s["criterio"], s["tipo"]))
    return senales


# --- Paso 2: guardrails + propuestas ----------------------------------------------------
def guardrails(senal: dict, criterio: dict | None, norma: str | None,
               min_recurrencia: int = 2) -> dict:
    """
    Decide si una senal puede convertirse en propuesta de regla. Reglas:
      - generalizable : es una regla (recurrente) o un ejemplar (ancla), no un parche.
      - recurrente    : vista >= min_recurrencia veces (las anclas se eximen: son ground truth).
      - consistente   : no relaja la norma disciplinar; si lo hace bajo modo estricto,
                        NO se bloquea, pero exige override docente explicito (queda registrado).
    """
    criterio = criterio or {}
    tipo = senal["tipo"]
    rec = senal.get("recurrencia", 0)
    recurrente = rec >= min_recurrencia
    es_ancla = tipo == TIPO_ANCLA

    estricto = (criterio.get("nivel_exigencia") == "estricto") or \
               (norma is not None and criterio.get("nivel_exigencia") is None)
    relaja_norma = (tipo in RELAJANTES) and estricto and (norma is not None)

    generalizable = recurrente or es_ancla
    # Las anclas (ejemplares validados) siempre estandarizan: aprobables aun con recurrencia 1.
    aprobable = es_ancla or recurrente

    motivos = []
    motivos.append(("regla generalizable" if generalizable else
                    "aun idiosincratico (1 caso, sin patron)"))
    motivos.append(f"recurrencia {rec}" + ("" if recurrente else f" (< {min_recurrencia})"))
    if relaja_norma:
        motivos.append(f"relaja la norma {norma}: requiere override docente con justificacion")
    elif tipo in ENDURECEN:
        motivos.append("endurece hacia la norma: consistente")
    return {
        "generalizable": generalizable,
        "recurrente": recurrente,
        "relaja_norma": relaja_norma,
        "consistente_norma": not relaja_norma,
        "aprobable": aprobable,
        "motivos": motivos,
    }


def proponer_ajustes(senales: list[dict], criterios_por_nombre: dict | None = None,
                     norma: str | None = None, min_recurrencia: int = 2) -> list[dict]:
    """Convierte senales en propuestas con su veredicto de guardrails y estado sugerido."""
    criterios_por_nombre = criterios_por_nombre or {}
    props = []
    for s in senales:
        gr = guardrails(s, criterios_por_nombre.get(s["criterio"]), norma, min_recurrencia)
        props.append({
            "criterio": s["criterio"], "tipo": s["tipo"], "direccion": s["direccion"],
            "recurrencia": s["recurrencia"], "evidencia": s["evidencia"],
            "descripcion": _descripcion(s),
            "comentarios": s.get("comentarios", []),
            "guardrails": gr,
            "requiere_override": gr["relaja_norma"],
            # confianza crece con la recurrencia (satura en 0,95); las anclas parten altas.
            "confianza": round(min(0.95, (0.7 if s["tipo"] == TIPO_ANCLA else 0.45)
                                   + 0.12 * s["recurrencia"]), 2),
            "estado": "propuesto" if gr["aprobable"] else "observacion",
        })
    return props


def _descripcion(s: dict) -> str:
    plantillas = {
        TIPO_SINONIMO: "Aceptar como equivalente el termino usado por el estudiante en '{c}'.",
        TIPO_ANALOGIA: "Aceptar analogias/parafrasis que expresen correctamente '{c}'.",
        TIPO_ANCLA: "Anadir la respuesta validada como ancla ejemplar de '{c}'.",
        TIPO_ALCANCE: "Ampliar lo que cuenta como en-alcance para '{c}'.",
        TIPO_PRECISION: "Exigir el termino estandar de la norma en '{c}'.",
        TIPO_ENDURECIDO: "Subir la vara del criterio '{c}'.",
    }
    return plantillas.get(s["tipo"], "Ajustar '{c}'.").format(c=s["criterio"])


# --- Paso 4: aplicar los aprobados -> nueva version -------------------------------------
def aplicar_ajustes(criterios_actuales: list[dict], aprobados: list[dict],
                    version_actual: int = 1, autor: str = "docente") -> dict:
    """
    Aplica las propuestas APROBADAS sobre una copia de los criterios y devuelve una version
    NUEVA (version+1, hash nuevo, changelog). No muta la entrada -> la version previa queda
    congelada. Cada aprobado puede traer 'payload' (p. ej. {'termino': 'elastico'} o
    {'texto': '...', 'nivel': 'logrado'}); si relaja la norma, exige 'justificacion'.
    """
    nuevos = [dict(c, sinonimos=list(c.get("sinonimos", [])),
                   anclas=list(c.get("anclas", []))) for c in criterios_actuales]
    por_nombre = {c.get("nombre", c.get("criterio")): c for c in nuevos}
    changelog = []

    for a in aprobados:
        if a.get("requiere_override") and not a.get("justificacion"):
            raise ValueError(
                f"El ajuste '{a['tipo']}' sobre '{a['criterio']}' relaja la norma y requiere "
                f"justificacion del docente (override).")
        c = por_nombre.get(a["criterio"])
        payload = a.get("payload", {})
        if c is not None:
            tipo = a["tipo"]
            if tipo == TIPO_SINONIMO and payload.get("termino"):
                if payload["termino"] not in c["sinonimos"]:
                    c["sinonimos"].append(payload["termino"])
            elif tipo in (TIPO_ANALOGIA, TIPO_ANCLA) and payload.get("texto"):
                c["anclas"].append({"texto": payload["texto"],
                                    "nivel": payload.get("nivel", "logrado")})
            elif tipo == TIPO_ALCANCE and payload.get("nota"):
                c["alcance_notas"] = (c.get("alcance_notas", "") + " " + payload["nota"]).strip()
            elif tipo in ENDURECEN:
                c["nivel_exigencia"] = "estricto"
                if payload.get("termino_requerido"):
                    c["termino_requerido"] = payload["termino_requerido"]
        changelog.append({
            "criterio": a["criterio"], "tipo": a["tipo"], "direccion": a.get("direccion"),
            "recurrencia": a.get("recurrencia"), "evidencia": a.get("evidencia", []),
            "requiere_override": bool(a.get("requiere_override")),
            "justificacion": a.get("justificacion"),
            "aprobado_por": a.get("aprobado_por", autor),
        })

    nuevo_hash = hash_criterios(nuevos)
    return {
        "version": version_actual + 1,
        "hash": nuevo_hash,
        "parent_hash": hash_criterios(criterios_actuales),
        "criterios": nuevos,
        "estado": "propuesta",   # el docente la activa; hasta entonces no califica nada
        "autor": autor,
        "n_cambios": len(changelog),
        "changelog": changelog,
        "resumen": f"v{version_actual + 1}: {len(changelog)} ajuste(s) aprendidos del docente.",
        "gobernanza": ("Version nueva e inmutable; la anterior queda congelada (replicabilidad). "
                       "Cada cambio fue aprobado por el docente (G1) con evidencia seudonimizada (G2)."),
    }


# --- Evidencia de que aprendio: curva de aprendizaje ------------------------------------
def curva_aprendizaje(qwk_por_version: list[dict]) -> dict:
    """
    qwk_por_version: [{version, qwk, n}] en orden. Devuelve la trayectoria del acuerdo
    IA<->docente y si el sistema converge hacia el criterio docente (evidencia replicable).
    """
    serie = sorted(qwk_por_version, key=lambda x: x["version"])
    if not serie:
        return {"disponible": False}
    qwks = [round(float(x["qwk"]), 3) for x in serie]
    delta = round(qwks[-1] - qwks[0], 3)
    mejora_monotona = all(b >= a - 0.02 for a, b in zip(qwks, qwks[1:]))  # tolera ruido pequeno
    if delta >= 0.05 and mejora_monotona:
        verdicto = "El acuerdo IA<->docente mejora de forma sostenida: la IA converge al criterio."
    elif delta >= 0.05:
        verdicto = "El acuerdo mejora en neto, con oscilaciones; revisar versiones que retrocedieron."
    elif delta <= -0.05:
        verdicto = "El acuerdo empeora: alguna version introdujo un ajuste que aleja de la norma."
    else:
        verdicto = "Acuerdo estable: la IA ya esta calibrada al criterio docente."
    return {
        "disponible": True,
        "versiones": [x["version"] for x in serie],
        "qwk": qwks,
        "delta_total": delta,
        "mejora_monotona": mejora_monotona,
        "convergencia": qwks[-1] >= 0.8,   # >=0,80 = acuerdo operativo
        "verdicto": verdicto,
    }


# --- Orquestador: briefing para el docente ---------------------------------------------
def ciclo_aprendizaje(registros: list[dict], criterios_por_nombre: dict | None = None,
                      norma: str | None = None, min_recurrencia: int = 2) -> dict:
    """Ejecuta pasos 1-2 y arma el briefing que el docente revisara (paso 3, humano)."""
    senales = extraer_senales(registros)
    props = proponer_ajustes(senales, criterios_por_nombre, norma, min_recurrencia)
    proponibles = [p for p in props if p["estado"] == "propuesto"]
    con_override = [p for p in proponibles if p["requiere_override"]]
    return {
        "n_senales": len(senales),
        "n_propuestas": len(proponibles),
        "n_observaciones": len(props) - len(proponibles),
        "n_requieren_override": len(con_override),
        "propuestas": proponibles,
        "observaciones": [p for p in props if p["estado"] == "observacion"],
        "norma": norma,
        "nota": ("La IA propone reglas; el docente aprueba (G1). Solo lo generalizable y "
                 "recurrente se propone; los casos aislados quedan como observacion, no como regla."),
    }
