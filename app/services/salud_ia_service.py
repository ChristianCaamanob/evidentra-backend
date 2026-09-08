"""
¿Está viva la IA de Runi? Una sola respuesta, cacheada, para todo el que necesite saberlo.

Nació de repetirse tres veces en el piloto: clave inválida, cuenta sin saldo y clave rechazada. Las
tres veces Runi dejó de responder A TODO el curso, y las tres veces el docente se enteró porque una
estudiante le mostró la pantalla. Un producto que depende de una credencial externa tiene que avisar
cuando esa credencial se cae, sin que nadie tenga que ir a mirar.

Se cachea porque el chequeo cuesta una llamada real al proveedor: pintar el panel del profesor no
puede gastar una por visita.
"""
from __future__ import annotations

import os
import time

_TTL_OK = 300          # 5 min cuando todo está bien
_TTL_MAL = 60          # 1 min cuando está caído: al rotar la clave, que se note pronto
_cache: dict = {}


def _ping() -> None:
    """La llamada real al proveedor, aislada a propósito.

    Separarla deja que lo que de verdad importa —traducir el fallo a algo accionable— se pueda
    probar sin el SDK instalado y sin gastar una llamada.
    """
    import anthropic
    from app.services import correccion_experta_service as ce
    anthropic.Anthropic().messages.create(
        model=ce.MODELO_EXPERTO, max_tokens=4,
        messages=[{"role": "user", "content": "ping"}])


def _diagnosticar() -> dict:
    clave = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not clave:
        return {"ok": False, "estado": "sin_clave",
                "detalle": "No hay clave de IA configurada en el servidor.",
                "que_hacer": "Define ANTHROPIC_API_KEY en las variables de entorno de Render."}
    try:
        _ping()
        return {"ok": True, "estado": "ok"}
    except Exception as e:  # noqa: BLE001
        b = str(e).lower()
        if "credit balance" in b or "billing" in b or "quota" in b:
            return {"ok": False, "estado": "sin_saldo",
                    "detalle": "La cuenta de Anthropic no tiene saldo.",
                    "que_hacer": "Recarga en console.anthropic.com → Plans & Billing."}
        if "authentication" in b or "401" in b or "invalid x-api-key" in b:
            return {"ok": False, "estado": "clave_invalida",
                    "detalle": "La clave existe pero el proveedor la rechaza.",
                    "que_hacer": "Crea una clave nueva en console.anthropic.com y actualiza "
                                 "ANTHROPIC_API_KEY en Render."}
        if "not_found" in b or "does not exist" in b:
            return {"ok": False, "estado": "modelo_invalido",
                    "detalle": "El modelo configurado no está disponible para esta cuenta.",
                    "que_hacer": "Revisa EVALYS_EXPERTO_MODEL en Render."}
        if "rate_limit" in b or "429" in b:
            return {"ok": False, "estado": "limite",
                    "detalle": "Límite de peticiones alcanzado.",
                    "que_hacer": "Se recupera solo en unos minutos."}
        if "overloaded" in b or "529" in b:
            return {"ok": False, "estado": "sobrecargado",
                    "detalle": "El proveedor está sobrecargado.",
                    "que_hacer": "Se recupera solo; no hay nada que hacer."}
        return {"ok": False, "estado": "error", "detalle": str(e)[:300],
                "que_hacer": "Revisa los registros del servidor."}


def estado(forzar: bool = False) -> dict:
    """El estado de la IA. Cacheado; `forzar` salta la caché (para el botón «reintentar»)."""
    ahora = time.time()
    if not forzar and _cache.get("hasta", 0) > ahora:
        return dict(_cache["valor"], cacheado=True)
    v = _diagnosticar()
    _cache["valor"] = v
    _cache["hasta"] = ahora + (_TTL_OK if v.get("ok") else _TTL_MAL)
    return dict(v, cacheado=False)
