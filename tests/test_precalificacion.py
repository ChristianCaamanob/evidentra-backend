"""
Test del motor de pre-calificacion de desarrollo (F2).
Verifica que el nivel de exigencia cambia la correccion, que las anclas calibran, que la
confianza escala a revision docente, y que la nota queda pendiente (G1). Mas QWK.
"""
from __future__ import annotations

from app.services import precalificacion_service as pc

CRIT_BASE = {
    "name": "Función del urotelio", "peso": 1.0,
    "sinonimos": ["distensibilidad"], "umbral_confianza": 0.4,
    "anclas": [
        {"texto": "Permite que la vejiga se distienda al llenarse", "nivel": "logrado"},
        {"texto": "Deja pasar la orina", "nivel": "parcial"},
        {"texto": "Protege de la abrasion", "nivel": "no_logrado"},
    ],
}
R_LOGRADO = "La vejiga se distienda porque la pared permite estirarse al llenarse"
R_NO = "Protege de la abrasion intensa"


def _crit(**over):
    c = dict(CRIT_BASE); c.update(over); return c


def test_tolerante_reconoce_logrado():
    r = pc.precalificar_criterio(R_LOGRADO, _crit(nivel_exigencia="tolerante"))
    assert r["nivel"] == "logrado"
    assert r["requiere_revision"] is False


def test_estricto_baja_si_falta_termino_canonico():
    # 'distiende' aparece pero no el termino canonico 'distensibilidad'
    r = pc.precalificar_criterio(R_LOGRADO, _crit(nivel_exigencia="estricto"))
    assert r["nivel"] == "parcial"
    assert "canonico" in r["justificacion"].lower() or "canónico" in r["justificacion"].lower()


def test_no_logrado_detectado():
    r = pc.precalificar_criterio(R_NO, _crit(nivel_exigencia="tolerante"))
    assert r["nivel"] == "no_logrado"


def test_flexible_marca_respuesta_creativa():
    creativa = "Funciona como un globo que se agranda progresivamente al recibir contenido"
    r = pc.precalificar_criterio(creativa, _crit(nivel_exigencia="flexible", umbral_confianza=0.3))
    assert r["requiere_revision"] is True   # se marca para el docente, no se reprueba a ciegas


def test_umbral_confianza_escala_a_revision():
    r = pc.precalificar_criterio(R_LOGRADO, _crit(nivel_exigencia="tolerante", umbral_confianza=0.99))
    assert r["requiere_revision"] is True


def test_respuesta_completa_nota_pendiente():
    crit2 = _crit(name="Menciona células en cúpula", peso=0.5,
                  anclas=[{"texto": "Tiene células paraguas en cupula", "nivel": "logrado"}])
    out = pc.precalificar_respuesta(R_LOGRADO, [_crit(peso=0.5), crit2],
                                    norma_terminologica="TA2 (IFAA)")
    assert out["estado_nota"] == "pendiente_validacion_docente"   # G1
    assert out["seudonimizado"] is True                            # G2
    assert 0.0 <= out["puntaje_propuesto"] <= 1.0
    assert len(out["criterios"]) == 2
    assert out["norma_terminologica"] == "TA2 (IFAA)"


def test_seam_coder_llm():
    def coder(resp, crit):
        return {"nivel": "logrado", "confianza": 0.9, "evidencia": "…", "justificacion": "modelo"}
    r = pc.precalificar_criterio("cualquier cosa", _crit(), coder=coder)
    assert r["nivel"] == "logrado" and r["justificacion"] == "modelo"


def test_qwk():
    niveles = ["no_logrado", "parcial", "logrado", "logrado"]
    assert pc.qwk(niveles, niveles) == 1.0                 # acuerdo perfecto
    peor = ["logrado", "logrado", "no_logrado", "no_logrado"]
    assert pc.qwk(niveles, peor) < 0.5                     # desacuerdo fuerte
