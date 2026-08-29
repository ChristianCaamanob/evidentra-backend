"""
Enlaces de video con previsualización (TikTok, YouTube, Instagram, Vimeo).

Se usa **oEmbed**, el mecanismo público que las propias plataformas ofrecen para esto: se
pregunta por la URL y devuelven título, autor y miniatura. No se descarga el video ni se
sortea nada — es la vía prevista y no depende de que el docente pegue nada más que el link.

La miniatura se **guarda con nosotros**, no se enlaza. Las URL de miniatura de TikTok van
firmadas y caducan: una tarjeta que hoy se ve bien aparecería rota en unos días. Además,
guardarla evita depender de que el CDN permita usarla desde otro dominio.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import urllib.parse
import urllib.request

from app.core.errors import unprocessable

_LOG = logging.getLogger("evalys")
_TIMEOUT = 12
_MAX_THUMB = 900 * 1024          # una miniatura no debería pesar más que esto
_UA = "Mozilla/5.0 (compatible; Evalys/1.0; +https://evalys.cl)"

# oEmbed público de cada plataforma. El orden no importa: se elige por el dominio.
_PROVEEDORES = [
    ("TikTok", r"tiktok\.com", "https://www.tiktok.com/oembed?url="),
    ("YouTube", r"(youtube\.com|youtu\.be)", "https://www.youtube.com/oembed?format=json&url="),
    ("Vimeo", r"vimeo\.com", "https://vimeo.com/api/oembed.json?url="),
    ("Instagram", r"instagram\.com", "https://graph.facebook.com/v16.0/instagram_oembed?url="),
]


def proveedor_de(url: str):
    u = str(url or "")
    for nombre, patron, endpoint in _PROVEEDORES:
        if re.search(patron, u, re.I):
            return nombre, endpoint
    return None, None


def _pedir(url: str, limite: int | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.read(limite) if limite else r.read()


def resolver(url: str) -> dict:
    """Devuelve {proveedor, titulo, autor, thumb_data_url} para un enlace de video."""
    u = str(url or "").strip()
    if not u.startswith(("http://", "https://")):
        raise unprocessable("Pega el enlace completo del video (empieza con https://).")
    nombre, endpoint = proveedor_de(u)
    if not nombre:
        raise unprocessable(
            "Por ahora reconozco enlaces de TikTok, YouTube, Vimeo e Instagram. "
            "Si es de otra parte, compártelo como enlace normal.")

    try:
        crudo = _pedir(endpoint + urllib.parse.quote(u, safe=""))
        d = json.loads(crudo.decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        _LOG.warning("video_link: %s no respondió para %s: %s", nombre, u[:80], e)
        raise unprocessable(
            f"{nombre} no me dio la información de ese video. Revisa que el enlace sea "
            "público y esté completo.")

    titulo = str(d.get("title") or "").strip()[:200] or f"Video de {nombre}"
    autor = str(d.get("author_name") or "").strip()[:120] or None

    # La miniatura se guarda con nosotros (ver el docstring del módulo).
    thumb = None
    turl = d.get("thumbnail_url")
    if turl:
        try:
            datos = _pedir(str(turl), _MAX_THUMB + 1)
            if len(datos) <= _MAX_THUMB:
                mime = "image/jpeg"
                if datos[:8].startswith(b"\x89PNG"):
                    mime = "image/png"
                elif datos[:4] == b"RIFF":
                    mime = "image/webp"
                thumb = "data:" + mime + ";base64," + base64.b64encode(datos).decode()
        except Exception as e:  # noqa: BLE001
            _LOG.warning("video_link: no se pudo traer la miniatura: %s", e)

    return {"proveedor": nombre, "titulo": titulo, "autor": autor,
            "thumb_data_url": thumb, "url": u}
