"""
Runi Reward System v1 — cofres, elección, inventario y libro mayor de Lumis.

Lo que estos tests protegen es lo que la directiva del paquete llama criterios de aceptación, y que
en la práctica son las tres formas en que un sistema de recompensas se rompe y deja de ser justo:
duplicar una recompensa al recargar, cambiar las tres opciones bajo los pies de quien está
eligiendo, y un saldo que no cuadra entre dos teléfonos.
"""
from __future__ import annotations

import importlib
import pkgutil

import app.models as _M
for _m in pkgutil.iter_modules(_M.__path__):
    importlib.import_module("app.models." + _m.name)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.services import recompensa_service as rw

PS = "stu:pseudo-1"


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


# ── catálogo ─────────────────────────────────────────────────────────────────────────
def test_el_catalogo_trae_las_39_recompensas_del_paquete():
    c = rw.catalogo()
    por_cat = {}
    for i in c["items"]:
        por_cat[i["category"]] = por_cat.get(i["category"], 0) + 1
    assert por_cat == {"medals": 8, "accessories": 12, "frames": 6, "trophies": 3, "titles": 6, "auras": 4}
    assert len(c["chests"]) == 4


def test_los_nombres_del_catalogo_son_los_del_paquete():
    """La directiva lo exige literalmente: no renombrar títulos ni recompensas."""
    nombres = {i["id"]: i["name"] for i in rw.catalogo()["items"]}
    assert nombres["conquistadora-cumbre"] == "Conquistadora de la Cumbre"
    assert nombres["08-la-cumbre"] == "La Cumbre"
    assert nombres["capa-aurora"] == "Capa Aurora"


def test_las_medallas_no_salen_en_cofres():
    """Una medalla se gana con evidencia verificada. Sortearla vaciaría su significado."""
    assert not [i for i in rw._obtenibles() if i["category"] in ("medals", "trophies")]


# ── libro mayor ──────────────────────────────────────────────────────────────────────
def test_el_saldo_sale_de_la_suma_no_de_un_contador(db):
    rw.acreditar(db, PS, "medalla", "medalla:1")
    rw.acreditar(db, PS, "medalla", "medalla:2")
    assert rw.saldo(db, PS) == 80


def test_la_misma_ref_no_acredita_dos_veces(db):
    rw.acreditar(db, PS, "medalla", "medalla:1")
    r = rw.acreditar(db, PS, "medalla", "medalla:1")
    assert r["acreditado"] == 0 and r.get("duplicado")
    assert rw.saldo(db, PS) == 40


def test_el_tope_diario_limita_lo_repetible_pero_no_los_hitos(db):
    for i in range(20):                       # 20 × 20 = 400, muy por encima del tope diario
        rw.acreditar(db, PS, "colaboracion", f"colab:{i}")
    repetible = rw.saldo(db, PS)
    assert repetible == rw._TOPE_DIARIO
    # Una medalla es un hito permanente: no se puede repetir, así que no entra al tope.
    rw.acreditar(db, PS, "medalla", "medalla:7")
    assert rw.saldo(db, PS) == repetible + 40


# ── cofres ───────────────────────────────────────────────────────────────────────────
def test_un_mismo_hito_no_genera_dos_cofres(db):
    a = rw.abrir_cofre(db, PS, "medalla:1", "cofre-expedicion")
    b = rw.abrir_cofre(db, PS, "medalla:1", "cofre-expedicion")
    assert a.id == b.id
    assert len(rw.pendientes(db, PS)["pendientes"]) == 1


def test_las_tres_opciones_no_cambian_al_recargar(db):
    a = rw.abrir_cofre(db, PS, "medalla:3", "cofre-expedicion")
    primeras = [o["id"] for o in a.opciones]
    assert len(primeras) == 3 and len(set(primeras)) == 3
    b = rw.abrir_cofre(db, PS, "medalla:3", "cofre-expedicion")
    assert [o["id"] for o in b.opciones] == primeras


def test_el_cofre_legendario_ofrece_tres_legendarias(db):
    p = rw.abrir_cofre(db, PS, "medalla:12", "cofre-legendario")
    assert [o["rarity"] for o in p.opciones] == ["legendary"] * 3


def test_el_cofre_glaciar_garantiza_al_menos_una_rara(db):
    p = rw.abrir_cofre(db, PS, "medalla:4", "cofre-glaciar")
    assert any(rw._ORDEN_RAREZA[o["rarity"]] >= rw._ORDEN_RAREZA["rare"] for o in p.opciones)


def test_reclamar_entrega_una_sola_vez(db):
    p = rw.abrir_cofre(db, PS, "medalla:1", "cofre-expedicion")
    elegido = p.opciones[0]["id"]
    r1 = rw.reclamar(db, PS, p.id, elegido)
    r2 = rw.reclamar(db, PS, p.id, elegido)
    assert r1["elegido"] == elegido
    assert r2.get("ya_reclamado")
    inv = rw.inventario(db, PS)
    assert sum(1 for i in inv["items"] if i["owned"]) == 1


def test_no_se_puede_reclamar_algo_que_no_estaba_en_el_cofre(db):
    p = rw.abrir_cofre(db, PS, "medalla:1", "cofre-expedicion")
    fuera = next(i["id"] for i in rw._obtenibles() if i["id"] not in {o["id"] for o in p.opciones})
    with pytest.raises(Exception):
        rw.reclamar(db, PS, p.id, fuera)


def test_un_cofre_ajeno_no_se_puede_reclamar(db):
    p = rw.abrir_cofre(db, PS, "medalla:1", "cofre-expedicion")
    with pytest.raises(Exception):
        rw.reclamar(db, "stu:otra-persona", p.id, p.opciones[0]["id"])


def test_las_opciones_priorizan_lo_que_no_tiene(db):
    p1 = rw.abrir_cofre(db, PS, "medalla:1", "cofre-expedicion")
    ganado = p1.opciones[0]["id"]
    rw.reclamar(db, PS, p1.id, ganado)
    p2 = rw.abrir_cofre(db, PS, "medalla:2", "cofre-expedicion")
    assert ganado not in {o["id"] for o in p2.opciones}


def test_si_ya_lo_tiene_todo_el_cofre_paga_lumis(db):
    for i in rw._obtenibles():
        rw.otorgar(db, PS, i["id"], origen="test")
    p = rw.abrir_cofre(db, PS, "medalla:5", "cofre-glaciar")
    assert p.opciones == []
    r = rw.reclamar(db, PS, p.id, None)
    assert r["elegido"] == "lumin" and r["lumis"] > 0
    assert rw.saldo(db, PS) == r["lumis"]


# ── equipamiento ─────────────────────────────────────────────────────────────────────
def test_no_se_equipa_lo_que_no_se_tiene(db):
    with pytest.raises(Exception):
        rw.equipar(db, PS, "aura", "aura-cumbre")


def test_una_sola_cosa_por_ranura(db):
    rw.otorgar(db, PS, "aura-cumbre"); rw.otorgar(db, PS, "aura-aurora")
    rw.equipar(db, PS, "aura", "aura-cumbre")
    rw.equipar(db, PS, "aura", "aura-aurora")
    assert rw._equipado(db, PS)["aura"] == "aura-aurora"
    rw.equipar(db, PS, "aura", None)
    assert "aura" not in rw._equipado(db, PS)


def test_un_accesorio_no_entra_en_la_ranura_de_otro(db):
    rw.otorgar(db, PS, "corona-laurel")
    with pytest.raises(Exception):
        rw.equipar(db, PS, "aura", "corona-laurel")


# ── tienda ───────────────────────────────────────────────────────────────────────────
def test_comprar_descuenta_y_entrega(db):
    rw.acreditar(db, PS, "medalla", "seed", 900)
    r = rw.comprar(db, PS, "marco-sendero")
    precio = next(i["price"] for i in rw.catalogo()["items"] if i["id"] == "marco-sendero")
    assert r["comprado"] == "marco-sendero"
    assert rw.saldo(db, PS) == 900 - precio
    assert "marco-sendero" in rw._tiene(db, PS)


def test_sin_saldo_no_hay_compra(db):
    with pytest.raises(Exception):
        rw.comprar(db, PS, "aura-cumbre")
    assert not rw._tiene(db, PS)


def test_comprar_dos_veces_no_cobra_dos_veces(db):
    rw.acreditar(db, PS, "medalla", "seed", 900)
    rw.comprar(db, PS, "marco-sendero")
    saldo = rw.saldo(db, PS)
    r = rw.comprar(db, PS, "marco-sendero")
    assert r.get("ya_lo_tienes") and rw.saldo(db, PS) == saldo


def test_una_medalla_no_se_compra(db):
    rw.acreditar(db, PS, "medalla", "seed", 5000)
    with pytest.raises(Exception):
        rw.comprar(db, PS, "08-la-cumbre")


# ── la Cumbre (los 8 tramos) ─────────────────────────────────────────────────────────
def test_los_ocho_tramos_cubren_las_doce_medallas():
    cubiertas = sorted(m for _a, _n, ms in rw.TRAMOS for m in ms)
    assert cubiertas == list(range(1, 13))
    assert len(rw.TRAMOS) == 8


def test_el_tramo_se_completa_con_todos_sus_hitos(db):
    t = rw.cumbre(db, PS, [3])                      # el tramo 3 tiene las medallas 3 y 4
    tramo3 = t[2]
    assert tramo3["logrados"] == 1 and not tramo3["completo"]
    assert rw.cumbre(db, PS, [3, 4])[2]["completo"]


def test_cada_medalla_abre_el_cofre_de_su_altura(db):
    rw.al_desbloquear_medalla(db, PS, 1, "primer-impulso")
    rw.al_desbloquear_medalla(db, PS, 12, "maestria-runi")
    cofres = {p["chestId"] for p in rw.pendientes(db, PS)["pendientes"]}
    assert cofres == {"cofre-expedicion", "cofre-legendario"}
    assert rw.saldo(db, PS) == 80                   # 40 Lumis por medalla, una sola vez cada una


def test_el_enganche_es_idempotente(db):
    for _ in range(3):
        rw.al_desbloquear_medalla(db, PS, 1, "primer-impulso")
    assert len(rw.pendientes(db, PS)["pendientes"]) == 1
    assert rw.saldo(db, PS) == 40


# ── medallas y trofeos: se derivan del motor de logros, no del inventario ────────────
def _desbloquear(db, *ids):
    """Escribe recibos de medalla como lo haría el motor de logros."""
    import uuid as _u
    from app.models.logros import MedalUnlock
    for i in ids:
        db.add(MedalUnlock(id=_u.uuid4().hex[:32], pseudo_id=PS, medal_id=i, slug=f"m{i}",
                           rule_version="3.0.0", xp_at_unlock=0, evidence={}))
    db.commit()


def test_la_medalla_del_tramo_se_tiene_al_completarlo(db):
    inv = rw.inventario(db, PS)
    assert not [i for i in inv["items"] if i["category"] == "medals" and i["owned"]]
    _desbloquear(db, 3)                       # el tramo 3 pide las medallas 3 Y 4
    tiene = {i["id"] for i in rw.inventario(db, PS)["items"] if i["owned"]}
    assert "03-bosque-conocimiento" not in tiene
    _desbloquear(db, 4)
    tiene = {i["id"] for i in rw.inventario(db, PS)["items"] if i["owned"]}
    assert "03-bosque-conocimiento" in tiene


def test_los_trofeos_marcan_3_6_y_8_tramos(db):
    _desbloquear(db, 1, 2, 3, 4)              # tramos 1, 2 y 3 completos
    tiene = {i["id"] for i in rw.inventario(db, PS)["items"] if i["owned"]}
    assert "trofeo-bronce" in tiene and "trofeo-plata" not in tiene
    _desbloquear(db, 5, 6, 7, 8, 9)           # + tramos 4, 5 y 6 → seis completos
    tiene = {i["id"] for i in rw.inventario(db, PS)["items"] if i["owned"]}
    assert "trofeo-plata" in tiene and "trofeo-oro" not in tiene
    _desbloquear(db, 10, 11, 12)              # los ocho
    assert "trofeo-oro" in {i["id"] for i in rw.inventario(db, PS)["items"] if i["owned"]}


def test_la_coleccion_cuenta_las_39(db):
    assert rw.inventario(db, PS)["coleccion_total"] == 39
