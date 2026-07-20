"""
Registro de PLANES como unica fuente de verdad (mismo patron que las escalas).

Rol != Plan: el rol (RBAC) es QUIEN eres; el plan es QUE pagaste. El acceso a una feature
premium exige que el rol lo permita Y que el plan la incluya (entitlement). El creador pasa
siempre.

Politica de entrada (decidida): al registrarse, el profesor obtiene un TRIAL de las features
premium (plan `profesor_pro`) por EVALYS_TRIAL_DIAS dias; al vencer, cae a `free` sin perder
datos (solo se bloquean las features premium).
"""
from __future__ import annotations

import os

# Claves de features (entitlements). Se referencian desde requiere_plan(...).
F_CORRECCION = "correccion"                 # OCR + correccion basica (siempre, incl. free)
F_EN_VIVO = "en_vivo"                        # quiz sincronico (Socrative)
F_BANCO_IA = "banco_ia"                      # generador de preguntas con IA (C3)
F_LIBRO_NOTAS = "libro_notas"                # libro de notas unificado
F_PSICOMETRIA = "psicometria_avanzada"       # Rasch/MFRM/DINA/... (Investigador)
F_PUBLICACION = "exportacion_publicacion"    # paquete de publicacion APA
F_EQUIDAD = "dif_equidad"                     # DIF / invarianza
F_PANELES = "paneles_agregados"              # dashboards por carrera/facultad (Enterprise)
F_DIRECCION = "rol_director_panel"           # panel de direccion
F_SLA = "sla"                                 # soporte/continuidad institucional

_BASE = {F_CORRECCION}
_PRO = _BASE | {F_EN_VIVO, F_BANCO_IA, F_LIBRO_NOTAS}
_INV = _PRO | {F_PSICOMETRIA, F_PUBLICACION, F_EQUIDAD}
_ENT = _INV | {F_PANELES, F_DIRECCION, F_SLA}

# precio_clp None = a cotizar. periodo en dias (mensual=30, anual=365). free no expira.
PLANES = {
    "free":         {"nombre": "Free", "precio_clp": 0, "periodo_dias": None, "entitlements": _BASE},
    "profesor_pro": {"nombre": "Profesor Pro", "precio_clp": 7990, "periodo_dias": 30, "entitlements": _PRO},
    "investigador": {"nombre": "Investigador", "precio_clp": 29990, "periodo_dias": 30, "entitlements": _INV},
    "enterprise":   {"nombre": "Enterprise", "precio_clp": None, "periodo_dias": 365, "entitlements": _ENT},
}

# El trial muestra las features de este plan (premium del nivel Profesor).
TRIAL_PLAN = os.environ.get("EVALYS_TRIAL_PLAN", "profesor_pro")
TRIAL_DIAS = int(os.environ.get("EVALYS_TRIAL_DIAS", "30"))


def es_plan_valido(plan: str) -> bool:
    return plan in PLANES


def periodo_dias(plan: str) -> int | None:
    return PLANES.get(plan, PLANES["free"])["periodo_dias"]


def entitlements_de_plan(plan: str) -> set[str]:
    return set(PLANES.get(plan, PLANES["free"])["entitlements"])


def precio_clp(plan: str) -> int | None:
    return PLANES.get(plan, PLANES["free"])["precio_clp"]


def listar_planes() -> dict:
    """Metadata publica (para pantallas de precios). Entitlements como lista ordenada."""
    return {k: {"nombre": v["nombre"], "precio_clp": v["precio_clp"],
                "periodo_dias": v["periodo_dias"],
                "entitlements": sorted(v["entitlements"])}
            for k, v in PLANES.items()}
