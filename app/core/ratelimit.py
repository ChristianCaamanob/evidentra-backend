"""Rate limiting (anti fuerza-bruta) para los endpoints sensibles (login/registro/reset).

Clave por IP real del cliente (respeta X-Forwarded-For detrás del proxy de Render). Se puede
apagar con RATELIMIT_ENABLED=false (p. ej. en CI para no chocar con logins repetidos de tests).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def client_ip(request) -> str:
    # Detrás del proxy de Render, la IP real viene en X-Forwarded-For (primer valor).
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip, enabled=settings.ratelimit_enabled)


def limit(spec: str):
    """Aplica el límite `spec` (p. ej. '8/minute') SOLO si el rate limiting está habilitado;
    si no (CI/tests), devuelve un decorador no-op. Robusto e independiente del flag interno
    de slowapi."""
    def deco(fn):
        return limiter.limit(spec)(fn) if settings.ratelimit_enabled else fn
    return deco
