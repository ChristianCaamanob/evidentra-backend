"""
Playlists de estudio por curso.

El CEO preguntó si se puede articular música desde Spotify o Apple Music. Dentro de la app no:
el Web Playback SDK de Spotify no corre en Safari de iPhone y exige Premium, y MusicKit de Apple
exige suscripción de cada oyente. Lo que sí funciona en todos los teléfonos es abrir la app que la
estudiante ya usa, con la playlist que eligió su profesor.

De ahí el único riesgo real de esta función: **ese enlace lo abre el teléfono de una estudiante**.
Si se aceptara cualquier URL, el docente —o quien lograra escribir en su configuración— podría
lanzarla a cualquier sitio desde dentro de Runi.
"""
from __future__ import annotations

from app.services import silabo_service as sil


def test_acepta_los_servicios_conocidos():
    m = sil.limpiar_musica({
        "spotify": "https://open.spotify.com/playlist/37i9dQZF1DX8Uebhn9wzrS",
        "apple": "https://music.apple.com/cl/playlist/study/pl.abc123",
        "youtube": "https://music.youtube.com/playlist?list=RDCLAK5uy_l",
    })
    assert set(m) == {"spotify", "apple", "youtube"}


def test_descarta_cualquier_otro_dominio():
    """El caso que importa: un enlace que no es de música y que se abriría en su teléfono."""
    m = sil.limpiar_musica({
        "spotify": "https://open.spotify.com.attacker.example/playlist/1",
        "apple": "https://evil.example/pl",
        "youtube": "https://youtube.com.phishing.example/watch?v=1",
    })
    assert m == {}


def test_exige_https():
    assert sil.limpiar_musica({"spotify": "http://open.spotify.com/playlist/1"}) == {}
    assert sil.limpiar_musica({"spotify": "javascript:alert(1)"}) == {}
    assert sil.limpiar_musica({"spotify": "spotify:playlist:1"}) == {}


def test_sin_musica_no_se_cae():
    for v in (None, {}, {"spotify": ""}, {"otro": "https://open.spotify.com/x"}):
        assert sil.limpiar_musica(v) == {}
