"""
Runi Reward System v1 — la capa cosmética de la Cumbre.

Qué NO hace, y es lo primero que hay que poder decir: no cambia notas, no cambia respuestas, no
cambia la dificultad ni el orden de nadie. Los Lumis no se compran con dinero. Es reconocimiento.

De dónde salen las recompensas: **de las 12 medallas que ya existen**, no de un sistema de mérito
nuevo. El motor de logros (`logros_service`) desbloquea una medalla cuando hay XP y evidencia
verificada, y emite un recibo inmutable; ese recibo —y solo ese— produce un cofre. Así la pregunta
"¿por qué gané esto?" siempre tiene una respuesta que apunta a algo que la estudiante hizo.

Las 8 medallas del paquete gráfico son los **tramos** de la Cumbre: el capítulo del ascenso al que
pertenece cada medalla. Son la portada del tramo, no una segunda tabla de méritos.

Sin ranking: no hay Top 10 ni podio. La comparación pública entre estudiantes identificadas por su
universidad dirige la conducta hacia la posición y no hacia aprender, así que las fuentes de Lumis
son todas personales.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import pathlib
import uuid as _uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found, unprocessable
from app.models.recompensa import (LuminMovimiento, RecompensaEquipo, RecompensaItem,
                                   RecompensaPendiente)

_CATALOGO_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "reward_catalog_v1.json"
_CACHE: dict | None = None

# Los 8 tramos de la Cumbre, en orden de ascenso, y qué medallas v3 vive cada uno. Varias medallas
# comparten tramo: el tramo es el capítulo, la medalla es el hito dentro de él.
TRAMOS = [
    ("01-campamento-base", "Campamento Base", [1]),
    ("02-sendero-constancia", "Sendero de Constancia", [2]),
    ("03-bosque-conocimiento", "Bosque del Conocimiento", [3, 4]),
    ("04-puente-desafios", "Puente de los Desafíos", [5, 6]),
    ("06-glaciar-dominio", "Glaciar del Dominio", [7, 8]),
    ("07-ultimo-ascenso", "Último Ascenso", [9]),
    ("05-pandilla", "Campamento de la Pandilla", [10, 11]),
    ("08-la-cumbre", "La Cumbre", [12]),
]

# Qué cofre abre cada medalla. Sube con el tramo: el reconocimiento acompaña al esfuerzo.
_COFRE_POR_MEDALLA = {1: "cofre-expedicion", 2: "cofre-expedicion", 3: "cofre-expedicion",
                      4: "cofre-glaciar", 5: "cofre-glaciar", 6: "cofre-glaciar",
                      7: "cofre-aurora", 8: "cofre-aurora", 9: "cofre-aurora",
                      10: "cofre-legendario", 11: "cofre-legendario", 12: "cofre-legendario"}

# Lo que cada cofre GARANTIZA (spec/REWARD_CATALOG.md). No es azar pagado: siempre se elige entre tres.
_GARANTIA = {"cofre-expedicion": None, "cofre-glaciar": "rare",
             "cofre-aurora": "epic", "cofre-legendario": "legendary"}
_ORDEN_RAREZA = {"common": 0, "rare": 1, "epic": 2, "legendary": 3}

# Fuentes de Lumis (spec/ECONOMY_AND_FAIRNESS.md), sin las de ranking.
LUMIS = {"actividad_dia": 10, "medalla": 40, "meta_semanal": 60, "colaboracion": 20}
_TOPE_DIARIO = 100          # solo para lo repetible; un hito permanente no se puede farmear
_TOPE_SEMANAL = 500
_MOTIVOS_CON_TOPE = ("actividad_dia", "colaboracion")
_CONSUELO = 0.4             # si ya no queda nada nuevo, el cofre paga el 40% del valor medio


def catalogo() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(_CATALOGO_PATH.read_text(encoding="utf-8"))
    return _CACHE


def _items() -> dict:
    return {i["id"]: i for i in catalogo()["items"]}


def _obtenibles() -> list:
    """Lo que puede salir de un cofre o comprarse. Las medallas NO: se ganan con evidencia, no se
    sortean — y los trofeos son del historial personal."""
    return [i for i in catalogo()["items"] if i["category"] in ("accessories", "frames", "titles", "auras")]


# ── Libro mayor de Lumis ──────────────────────────────────────────────────────────────
def saldo(db: Session, pseudo_id: str) -> int:
    v = db.query(func.coalesce(func.sum(LuminMovimiento.delta), 0)).filter(
        LuminMovimiento.pseudo_id == pseudo_id).scalar()
    return int(v or 0)


def _gastado_en(db: Session, pseudo_id: str, desde: _dt.datetime) -> int:
    """Lumis GANADOS por fuentes topables desde una fecha (para el tope, los gastos no cuentan)."""
    v = (db.query(func.coalesce(func.sum(LuminMovimiento.delta), 0))
         .filter(LuminMovimiento.pseudo_id == pseudo_id,
                 LuminMovimiento.creado_at >= desde,
                 LuminMovimiento.motivo.in_(_MOTIVOS_CON_TOPE)).scalar())
    return int(v or 0)


def acreditar(db: Session, pseudo_id: str, motivo: str, ref: str, monto: int | None = None,
              detalle: str | None = None) -> dict:
    """Suma Lumis una sola vez por `ref`. Reintentar no vuelve a pagar.

    El tope diario/semanal se aplica SOLO a las fuentes repetibles. Un hito permanente (una medalla)
    queda fuera: no se puede repetir artificialmente, así que limitarlo solo castigaría a quien
    avanzó mucho en una semana.
    """
    monto = int(monto if monto is not None else LUMIS.get(motivo, 0))
    if monto == 0:
        return {"ok": True, "acreditado": 0, "saldo": saldo(db, pseudo_id)}
    if db.query(LuminMovimiento).filter(LuminMovimiento.pseudo_id == pseudo_id,
                                        LuminMovimiento.ref == ref).first():
        return {"ok": True, "acreditado": 0, "duplicado": True, "saldo": saldo(db, pseudo_id)}
    # El tope regula lo que se GANA por fuentes repetibles; un gasto nunca se recorta.
    if monto > 0 and motivo in _MOTIVOS_CON_TOPE:
        ahora = _dt.datetime.utcnow()
        hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        semana = hoy - _dt.timedelta(days=hoy.weekday())
        margen = min(_TOPE_DIARIO - _gastado_en(db, pseudo_id, hoy),
                     _TOPE_SEMANAL - _gastado_en(db, pseudo_id, semana))
        monto = max(0, min(monto, margen))
        if monto <= 0:
            return {"ok": True, "acreditado": 0, "tope": True, "saldo": saldo(db, pseudo_id)}
    db.add(LuminMovimiento(id=_uuid.uuid4().hex[:32], pseudo_id=pseudo_id, delta=monto,
                           motivo=motivo, ref=ref, detalle=detalle))
    try:
        db.commit()
    except Exception:  # noqa: BLE001 — carrera con otra pestaña; la unicidad de ref ya nos protegió
        db.rollback()
        return {"ok": True, "acreditado": 0, "duplicado": True, "saldo": saldo(db, pseudo_id)}
    return {"ok": True, "acreditado": monto, "saldo": saldo(db, pseudo_id)}


def libro_mayor(db: Session, pseudo_id: str, limite: int = 60) -> dict:
    filas = (db.query(LuminMovimiento).filter(LuminMovimiento.pseudo_id == pseudo_id)
             .order_by(LuminMovimiento.creado_at.desc()).limit(min(int(limite or 60), 200)).all())
    return {"ok": True, "saldo": saldo(db, pseudo_id),
            "movimientos": [{"delta": m.delta, "motivo": m.motivo, "detalle": m.detalle,
                             "fecha": m.creado_at.isoformat() if m.creado_at else None} for m in filas]}


# ── Inventario y equipamiento ─────────────────────────────────────────────────────────
def _tiene(db: Session, pseudo_id: str) -> set:
    return {r.item_id for r in db.query(RecompensaItem).filter(RecompensaItem.pseudo_id == pseudo_id).all()}


def _equipado(db: Session, pseudo_id: str) -> dict:
    return {r.slot: r.item_id for r in db.query(RecompensaEquipo).filter(
        RecompensaEquipo.pseudo_id == pseudo_id).all()}


def otorgar(db: Session, pseudo_id: str, item_id: str, origen: str = "cofre",
            ref: str | None = None) -> bool:
    """Entrega un ítem. Devuelve False si ya lo tenía (no es error: es idempotencia)."""
    it = _items().get(item_id)
    if not it:
        raise not_found("Esa recompensa no existe en el catálogo.")
    if db.query(RecompensaItem).filter(RecompensaItem.pseudo_id == pseudo_id,
                                       RecompensaItem.item_id == item_id).first():
        return False
    db.add(RecompensaItem(id=_uuid.uuid4().hex[:32], pseudo_id=pseudo_id, item_id=item_id,
                          categoria=it["category"], rareza=it["rarity"], origen=origen, ref=ref))
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        return False
    return True


def _medallas_desbloqueadas(db: Session, pseudo_id: str) -> set:
    from app.models.logros import MedalUnlock
    return {int(u.medal_id) for u in db.query(MedalUnlock).filter(
        MedalUnlock.pseudo_id == pseudo_id).all()}


def _ganadas_sin_inventario(db: Session, pseudo_id: str) -> set:
    """Medallas y trofeos: no viven en el inventario porque no se eligen ni se compran.

    Una medalla de tramo es tuya cuando completaste TODOS sus hitos; los tres trofeos marcan 3, 6 y
    los 8 tramos de la Cumbre. Se derivan del motor de logros en cada consulta, así nunca pueden
    quedar desincronizados de la evidencia que los justifica.
    """
    hechas = _medallas_desbloqueadas(db, pseudo_id)
    ganadas, completos = set(), 0
    for asset, _nombre, medallas in TRAMOS:
        if all(m in hechas for m in medallas):
            ganadas.add(asset); completos += 1
    for n, trofeo in ((3, "trofeo-bronce"), (6, "trofeo-plata"), (8, "trofeo-oro")):
        if completos >= n:
            ganadas.add(trofeo)
    return ganadas


def inventario(db: Session, pseudo_id: str) -> dict:
    if not pseudo_id:
        raise unprocessable("Falta la identidad del estudiante.")
    tiene, eq = _tiene(db, pseudo_id), _equipado(db, pseudo_id)
    tiene = tiene | _ganadas_sin_inventario(db, pseudo_id)
    cat = catalogo()
    items = []
    for i in cat["items"]:
        d = dict(i)
        d["owned"] = i["id"] in tiene
        d["equipped"] = eq.get(i.get("slot") or "") == i["id"]
        items.append(d)
    return {"ok": True, "saldo": saldo(db, pseudo_id), "equipado": eq,
            "items": items,
            "total": len(items), "obtenidos": sum(1 for i in items if i["owned"]),
            "coleccion_total": len(items),
            "coleccion_obtenidos": sum(1 for i in items if i["owned"]),
            "nota": cat["nota_obligatoria"], "asset_base": cat["asset_base"]}


def equipar(db: Session, pseudo_id: str, slot: str, item_id: str | None) -> dict:
    """Pone (o quita, con item_id vacío) una recompensa en una ranura. Una por ranura."""
    slot = str(slot or "").strip()[:24]
    if not slot:
        raise unprocessable("Falta la ranura.")
    fila = db.query(RecompensaEquipo).filter(RecompensaEquipo.pseudo_id == pseudo_id,
                                             RecompensaEquipo.slot == slot).first()
    if not item_id:
        if fila:
            db.delete(fila); db.commit()
        return {"ok": True, "equipado": _equipado(db, pseudo_id)}
    it = _items().get(item_id)
    if not it:
        raise not_found("Esa recompensa no existe.")
    if (it.get("slot") or "") != slot:
        raise unprocessable(f"«{it['name']}» no va en esa ranura.")
    if item_id not in _tiene(db, pseudo_id):
        raise conflict("Todavía no tienes esa recompensa.")
    if fila:
        fila.item_id = item_id
        fila.actualizado_at = _dt.datetime.utcnow()
    else:
        db.add(RecompensaEquipo(id=_uuid.uuid4().hex[:32], pseudo_id=pseudo_id, slot=slot, item_id=item_id))
    db.commit()
    return {"ok": True, "equipado": _equipado(db, pseudo_id)}


# ── Cofres ────────────────────────────────────────────────────────────────────────────
def _tres_opciones(pseudo_id: str, cofre_id: str, origen_ref: str, tiene: set) -> list:
    """Las tres opciones de un cofre, elegidas de forma DETERMINISTA a partir de su origen.

    Determinista a propósito: la misma medalla siempre propone las mismas tres cosas, así recargar
    la pantalla no reparte de nuevo. Se priorizan los ítems no obtenidos (regla 4 de la economía) y
    se respeta la garantía de rareza del cofre.
    """
    nuevos = [i for i in _obtenibles() if i["id"] not in tiene]
    if not nuevos:
        return []
    semilla = hashlib.sha256(f"{pseudo_id}|{cofre_id}|{origen_ref}".encode()).digest()
    # Barajado estable: cada ítem recibe una posición fija derivada de la semilla y su id.
    def orden(it):
        return hashlib.sha256(semilla + it["id"].encode()).hexdigest()
    nuevos = sorted(nuevos, key=orden)

    garantia = _GARANTIA.get(cofre_id)
    elegidos = []
    if garantia:
        piso = _ORDEN_RAREZA[garantia]
        # El cofre legendario exige las TRES legendarias; los demás garantizan AL MENOS una.
        exactas = [i for i in nuevos if _ORDEN_RAREZA[i["rarity"]] >= piso]
        if cofre_id == "cofre-legendario":
            elegidos = exactas[:3]
        elif exactas:
            elegidos = [exactas[0]]
    for i in nuevos:
        if len(elegidos) >= 3:
            break
        if i not in elegidos:
            elegidos.append(i)
    return [{"id": i["id"], "category": i["category"], "name": i["name"], "rarity": i["rarity"],
             "slot": i.get("slot"), "asset128": i["asset128"], "asset512": i["asset512"]}
            for i in elegidos[:3]]


def _valor_consuelo() -> int:
    """Si ya no queda nada nuevo, el cofre paga Lumis: el 40% del valor medio del catálogo."""
    precios = [i["price"] for i in _obtenibles() if i.get("price")]
    return int(round((sum(precios) / len(precios)) * _CONSUELO)) if precios else 100


def abrir_cofre(db: Session, pseudo_id: str, origen_ref: str, cofre_id: str,
                origen_texto: str | None = None) -> RecompensaPendiente | None:
    """Crea el cofre de un hecho verificado. Si ese hecho ya generó uno, devuelve el MISMO."""
    ya = db.query(RecompensaPendiente).filter(RecompensaPendiente.pseudo_id == pseudo_id,
                                              RecompensaPendiente.origen_ref == origen_ref).first()
    if ya:
        return ya
    opciones = _tres_opciones(pseudo_id, cofre_id, origen_ref, _tiene(db, pseudo_id))
    p = RecompensaPendiente(id=_uuid.uuid4().hex[:32], pseudo_id=pseudo_id, origen_ref=origen_ref,
                            origen_texto=origen_texto, cofre_id=cofre_id, opciones=opciones)
    db.add(p)
    try:
        db.commit(); db.refresh(p)
    except Exception:  # noqa: BLE001
        db.rollback()
        return db.query(RecompensaPendiente).filter(
            RecompensaPendiente.pseudo_id == pseudo_id,
            RecompensaPendiente.origen_ref == origen_ref).first()
    return p


def _pend_dict(p: RecompensaPendiente) -> dict:
    cofres = {c["id"]: c for c in catalogo()["chests"]}
    c = cofres.get(p.cofre_id, cofres["cofre-expedicion"])
    return {"pendingRewardId": p.id, "sourceEventId": p.origen_ref, "origen": p.origen_texto,
            "chestId": p.cofre_id, "chest": c, "options": p.opciones or [],
            "sin_novedades": not (p.opciones or []), "lumis_consuelo": _valor_consuelo(),
            "elegido": p.elegido, "expiresAt": None,
            "creado": p.creado_at.isoformat() if p.creado_at else None}


def pendientes(db: Session, pseudo_id: str) -> dict:
    filas = (db.query(RecompensaPendiente)
             .filter(RecompensaPendiente.pseudo_id == pseudo_id, RecompensaPendiente.elegido.is_(None))
             .order_by(RecompensaPendiente.creado_at.asc()).all())
    return {"ok": True, "pendientes": [_pend_dict(p) for p in filas], "saldo": saldo(db, pseudo_id)}


def reclamar(db: Session, pseudo_id: str, pendiente_id: str, item_id: str | None) -> dict:
    """Confirma la elección. Idempotente: repetirla devuelve lo mismo, no entrega dos veces."""
    p = db.query(RecompensaPendiente).filter(RecompensaPendiente.id == pendiente_id).first()
    if not p:
        raise not_found("Ese cofre no existe.")
    if p.pseudo_id != pseudo_id:
        raise conflict("Ese cofre no es tuyo.")
    if p.elegido:
        return {"ok": True, "ya_reclamado": True, "elegido": p.elegido,
                "saldo": saldo(db, pseudo_id)}

    opciones = p.opciones or []
    if not opciones:
        # No queda nada nuevo por entregar: se paga en Lumis (regla 5 de la economía).
        monto = _valor_consuelo()
        p.elegido = "lumin"; p.reclamado_at = _dt.datetime.utcnow(); db.commit()
        acreditar(db, pseudo_id, "cofre_sin_novedades", f"cofre:{p.id}", monto,
                  detalle="Ya tenías todo lo del cofre")
        return {"ok": True, "elegido": "lumin", "lumis": monto, "saldo": saldo(db, pseudo_id)}

    validos = {o["id"] for o in opciones}
    if item_id not in validos:
        raise unprocessable("Elige una de las tres opciones del cofre.")
    otorgar(db, pseudo_id, item_id, origen="cofre", ref=p.id)
    p.elegido = item_id; p.reclamado_at = _dt.datetime.utcnow(); db.commit()
    it = _items()[item_id]
    return {"ok": True, "elegido": item_id, "item": it, "saldo": saldo(db, pseudo_id)}


def comprar(db: Session, pseudo_id: str, item_id: str) -> dict:
    """Compra con Lumis. Nunca con dinero real: la moneda no tiene puerta de pago."""
    it = _items().get(item_id)
    if not it:
        raise not_found("Esa recompensa no existe.")
    precio = int(it.get("price") or 0)
    if precio <= 0:
        raise conflict("Esta recompensa no está a la venta: se gana.")
    if item_id in _tiene(db, pseudo_id):
        return {"ok": True, "ya_lo_tienes": True, "saldo": saldo(db, pseudo_id)}
    if saldo(db, pseudo_id) < precio:
        raise conflict(f"Te faltan {precio - saldo(db, pseudo_id)} Lumis para «{it['name']}».")
    if not otorgar(db, pseudo_id, item_id, origen="tienda", ref=f"compra:{item_id}"):
        return {"ok": True, "ya_lo_tienes": True, "saldo": saldo(db, pseudo_id)}
    # El cargo va DESPUÉS de tener el ítem: si algo falla, nadie paga por lo que no recibió.
    acreditar(db, pseudo_id, "compra", f"compra:{item_id}", -precio, detalle=it["name"])
    return {"ok": True, "comprado": item_id, "item": it, "saldo": saldo(db, pseudo_id)}


# ── Enganche con el motor de medallas ─────────────────────────────────────────────────
def tramo_de_medalla(medal_id: int) -> tuple:
    for orden, (asset, nombre, medallas) in enumerate(TRAMOS, start=1):
        if medal_id in medallas:
            return orden, asset, nombre
    return 0, "", ""


def al_desbloquear_medalla(db: Session, pseudo_id: str, medal_id: int, slug: str = "") -> None:
    """Una medalla verificada = 40 Lumis + un cofre. Ambos idempotentes por el id de la medalla.

    Se llama desde `logros_service` justo después de escribir el recibo inmutable. Si algo aquí
    falla, NO puede tumbar el desbloqueo: la medalla es el logro, esto es el adorno.
    """
    try:
        orden, _asset, nombre = tramo_de_medalla(int(medal_id))
        texto = f"Tramo {orden} · {nombre}" if orden else (slug or "Nuevo hito")
        acreditar(db, pseudo_id, "medalla", f"medalla:{medal_id}", detalle=texto)
        abrir_cofre(db, pseudo_id, f"medalla:{medal_id}",
                    _COFRE_POR_MEDALLA.get(int(medal_id), "cofre-expedicion"), texto)
    except Exception:  # noqa: BLE001
        db.rollback()


def cumbre(db: Session, pseudo_id: str, medallas: list) -> list:
    """Los 8 tramos con su medalla-portada, sus hitos y QUÉ FALTA para cada uno.

    `medallas` es la lista de medallas tal como la devuelve el motor de logros (con `progress` y
    `falta_evidencia`), no solo los ids: sin eso el tramo puede decir que está incompleto pero no
    qué hacer, que es justo lo que preguntaba quien lo miraba.
    """
    por_id = {int(m["id"]): m for m in (medallas or []) if isinstance(m, dict) and m.get("id")}
    out = []
    for orden, (asset, nombre, ids) in enumerate(TRAMOS, start=1):
        hitos = [por_id.get(i, {"id": i}) for i in ids]
        listos = [h for h in hitos if h.get("unlocked")]
        # Solo el SIGUIENTE hito sin conseguir: listar los dos a la vez daba dos "Acumula X XP más"
        # seguidos y lo que se necesita es un próximo paso, no un inventario de deudas.
        siguiente = next((h for h in hitos if not h.get("unlocked")), None)
        falta, preparacion = [], []
        if siguiente:
            if siguiente.get("falta_xp"):
                falta.append(f"Acumula {siguiente['falta_xp']} XP más")
            for t in (siguiente.get("falta_evidencia") or []):
                (preparacion if "en preparación" in t else falta).append(t)
        prog = round(sum(h.get("progress", 0) for h in hitos) / len(hitos)) if hitos else 0
        out.append({"orden": orden, "id": asset, "nombre": nombre,
                    "asset128": f"assets/medals/png-128/{asset}.png",
                    "asset512": f"assets/medals/png-512/{asset}.png",
                    "hitos": len(ids), "logrados": len(listos),
                    "completo": len(listos) == len(ids),
                    "progreso": 100 if len(listos) == len(ids) else prog,
                    "medallas": [{"id": h.get("id"), "slug": h.get("slug"),
                                  "unlocked": bool(h.get("unlocked")), "progress": h.get("progress", 0)}
                                 for h in hitos],
                    "falta": falta[:4],
                    # Señales que el motor todavía no mide: se dicen, no se esconden. Un tramo que
                    # depende solo de ellas no se puede completar hoy y el estudiante merece saberlo.
                    "en_preparacion": [t.replace(" (en preparación)", "") for t in preparacion[:3]],
                    "alcanzable": not preparacion})
    return out


# Las reglas del juego, en el idioma del estudiante. Viven aquí y no en la pantalla para que la
# app no pueda contar una versión distinta de la que el servidor aplica.
def reglas() -> dict:
    return {
        "principio": "Una medalla exige puntos Y evidencia de que aprendiste. Los puntos solos nunca "
                     "desbloquean nada, y abrir la app no suma.",
        "acciones": [
            {"id": "consulta", "titulo": "Pregúntale a Runi y marca tu confianza",
             "detalle": "Cuando resuelvas una duda, dile si quedaste con confianza baja, media o alta. "
                        "Ahí tu consulta se vuelve un episodio de aprendizaje y Runi te programa una "
                        "comprobación a 7 días.",
             "xp": "10–25 XP", "cta": "runi"},
            {"id": "repaso", "titulo": "Haz un repaso de 5 minutos",
             "detalle": "Tres preguntas sobre un tema tuyo, sin mirar apuntes. Al terminar, el episodio "
                        "queda verificado en el momento.",
             "xp": "10–25 XP", "cta": "repaso"},
            {"id": "diferida", "titulo": "Responde la comprobación cuando Runi te avise",
             "detalle": "A los días te pregunta si todavía lo recuerdas. Esa respuesta es la que prueba "
                        "que aprendiste de verdad, y es la que más suma.",
             "xp": "25 XP", "cta": "repaso"},
            {"id": "error", "titulo": "Corrige algo que dabas por seguro",
             "detalle": "Si marcaste alta confianza y estaba mal, volver sobre ese tema y acertar es lo "
                        "que más vale de todo.",
             "xp": "30 XP", "cta": "repaso"},
            {"id": "plan", "titulo": "Ponte tu propia meta de la semana",
             "detalle": "Tú decides cuántos repasos quieres cerrar. Cumplir tu propio plan dos "
                        "semanas es lo que abre «Rumbo propio». Si no llegas, no pierdes nada.",
             "xp": "Meta propia", "cta": "plan"},
            {"id": "pandilla", "titulo": "Ayuda a tu Pandilla y que te lo reconozcan",
             "detalle": "La ayuda cuenta cuando quien la recibió la valida. Máximo dos al día, para que "
                        "sea ayuda de verdad y no un intercambio de favores.",
             "xp": "20 XP", "cta": "pandilla"},
        ],
        "no_suma": ["Abrir la app o dejarla abierta", "Repetir la misma evidencia una y otra vez",
                    "Responder sin haberlo intentado"],
        "sin_castigo": "Si pierdes una racha no te quitamos nada: empiezas otra y conservas todo lo tuyo.",
        "lumis": "Cada medalla te da 40 Lumis y un cofre donde eliges una de tres. Los Lumis solo compran "
                 "cosas para verte bien: nunca notas, ni pistas, ni prioridad con tu profe.",
    }
