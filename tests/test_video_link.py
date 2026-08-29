"""Enlaces de video con vista previa (TikTok, YouTube…).

El CEO quiere compartir sus explicaciones anatómicas de TikTok y que se vean con imagen.
Se usa oEmbed —el mecanismo público que las plataformas ofrecen para esto— y la miniatura
se guarda con nosotros: las URL de miniatura de TikTok van firmadas y caducan, así que
enlazarlas dejaría tarjetas rotas a los pocos días.
"""
from __future__ import annotations

import base64
import json

import pytest

from app.services import video_link_service as vl


_JPEG = b"\xff\xd8\xff\xe0" + b"x" * 500


def _falso(oembed: dict, thumb: bytes = _JPEG):
    def _pedir(url, limite=None):
        if "oembed" in url or "api/oembed" in url:
            return json.dumps(oembed).encode()
        return thumb
    return _pedir


@pytest.mark.parametrize("url,esperado", [
    ("https://www.tiktok.com/@dr/video/123", "TikTok"),
    ("https://youtu.be/abc123", "YouTube"),
    ("https://www.youtube.com/watch?v=abc", "YouTube"),
    ("https://vimeo.com/123", "Vimeo"),
    ("https://www.instagram.com/reel/xyz/", "Instagram"),
])
def test_reconoce_las_plataformas(url, esperado):
    assert vl.proveedor_de(url)[0] == esperado


def test_resuelve_titulo_autor_y_miniatura(monkeypatch):
    monkeypatch.setattr(vl, "_pedir", _falso({
        "title": "Diafragma pélvico en 60 segundos",
        "author_name": "Dr. Caamaño",
        "thumbnail_url": "https://p19.tiktokcdn.com/firmada.jpg?x-expires=123",
    }))
    d = vl.resolver("https://www.tiktok.com/@drcaamano/video/999")
    assert d["proveedor"] == "TikTok"
    assert d["titulo"] == "Diafragma pélvico en 60 segundos"
    assert d["autor"] == "Dr. Caamaño"
    assert d["thumb_data_url"].startswith("data:image/jpeg;base64,")
    # la miniatura queda GUARDADA, no enlazada a la URL firmada que caduca
    assert "tiktokcdn" not in d["thumb_data_url"]
    assert base64.b64decode(d["thumb_data_url"].split(",", 1)[1])[:2] == b"\xff\xd8"


def test_sin_miniatura_igual_sirve(monkeypatch):
    """Si la plataforma no da imagen, el video se agrega igual: no es motivo para fallar."""
    monkeypatch.setattr(vl, "_pedir", _falso({"title": "Clase 1", "author_name": "Yo"}))
    d = vl.resolver("https://youtu.be/abc")
    assert d["titulo"] == "Clase 1" and d["thumb_data_url"] is None


def test_enlace_de_otra_parte_lo_dice_claro():
    with pytest.raises(Exception) as e:
        vl.resolver("https://misitio.cl/video.mp4")
    assert "TikTok" in str(e.value), "hay que decir qué SÍ se reconoce"


def test_enlace_incompleto():
    with pytest.raises(Exception) as e:
        vl.resolver("tiktok.com/@x/video/1")
    assert "enlace completo" in str(e.value)


def test_si_la_plataforma_no_responde_no_se_culpa_al_docente(monkeypatch):
    def _revienta(url, limite=None):
        raise RuntimeError("timeout")
    monkeypatch.setattr(vl, "_pedir", _revienta)
    with pytest.raises(Exception) as e:
        vl.resolver("https://www.tiktok.com/@x/video/1")
    msg = str(e.value)
    assert "público" in msg and "timeout" not in msg, "no se filtra el error crudo"


def test_una_miniatura_gigante_no_se_guarda(monkeypatch):
    """Una portada de megas inflaría la tarjeta sin aportar nada."""
    monkeypatch.setattr(vl, "_pedir", _falso(
        {"title": "X", "thumbnail_url": "https://x/y.jpg"}, thumb=b"\xff\xd8" + b"z" * (2 * 1024 * 1024)))
    d = vl.resolver("https://www.tiktok.com/@x/video/1")
    assert d["thumb_data_url"] is None and d["titulo"] == "X"


# ── El pie de TikTok no sirve como título ─────────────────────────────────────────────
@pytest.mark.parametrize("bruto,esperado", [
    ("ANATOMÍA DE PAREDES DE PELVIS. #anatomia #pelvis #perineo", "ANATOMÍA DE PAREDES DE PELVIS"),
    ("Diafragma pélvico en 60 segundos", "Diafragma pélvico en 60 segundos"),
])
def test_titulo_se_corta_en_los_hashtags(bruto, esperado):
    assert vl._titulo_limpio(bruto, "TikTok") == esperado


def test_si_es_solo_hashtags_se_arma_un_titulo_igual():
    """Hay videos cuyo pie son puras etiquetas: dejarlo sin nombre sería peor."""
    t = vl._titulo_limpio("#pisopelvico #elevadordelano #anatomia", "TikTok")
    assert "Pisopelvico" in t and "#" not in t


def test_titulo_muy_largo_se_recorta():
    t = vl._titulo_limpio("A" * 400, "TikTok")
    assert len(t) <= 121 and t.endswith("…")


def test_el_tipo_video_ya_es_valido():
    """Sin esto quedaba como 'otro' y por eso no se mostraba la portada."""
    from app.services import material_curso_service as mc
    assert mc._tipo("video") == "video"
