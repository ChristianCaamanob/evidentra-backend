"""
Generador de preguntas alineado a C3 (RA -> Bloom): produce items de alternativas a partir
de un Resultado de Aprendizaje, un nivel de Bloom y una dificultad objetivo.

Misma arquitectura de seam que F2 (coder_llm), para ser testeable sin API key y degradar
con gracia:

  1. construir_prompt_generacion(...)  -> (system, user)   [PURO, testeable]
  2. parsear_preguntas(texto, n_alt)   -> list[dict]        [PURO, valida el JSON del modelo]
  3. generar_con(llamar, ...)          -> list[dict]        [inyecta `llamar(system,user)->str`]

`generar_preguntas` usa el LLM si hay ANTHROPIC_API_KEY; si no (o ante cualquier error) cae
a una PLANTILLA determinista: andamios que referencian el RA para que el docente complete.
Nunca inventa en silencio: los andamios quedan marcados origen='plantilla'.

Gobernanza: todo lo generado es BORRADOR (borrador=True). La IA PROPONE; el item entra a la
pauta solo tras la aprobacion del docente (G1). Alineado a C3: cada pregunta lleva su RA y
su nivel de Bloom, para trazar la cobertura curricular.
"""
from __future__ import annotations

import json
import os

MODELO_DEFECTO = os.environ.get("EVALYS_GEN_MODEL", "claude-sonnet-5")

# Verbos por nivel de Bloom, para orientar la redaccion del enunciado.
BLOOM_VERBOS = {
    "recordar": "identificar, nombrar, listar, definir",
    "comprender": "explicar, describir, interpretar, resumir",
    "aplicar": "aplicar, resolver, usar, calcular en un caso nuevo",
    "analizar": "analizar, comparar, diferenciar, relacionar causas",
    "evaluar": "evaluar, justificar, argumentar, criticar",
    "crear": "disenar, proponer, formular una solucion",
}
_DIFICULTAD = {
    "facil": "DIFICULTAD FACIL: un distractor obvio; la clave es reconocible con el concepto base.",
    "media": "DIFICULTAD MEDIA: distractores plausibles que reflejan errores conceptuales comunes.",
    "dificil": "DIFICULTAD DIFICIL: distractores muy cercanos a la clave; exige discriminar matices.",
}
_LETRAS = "ABCDEFGH"


def _norm(txt) -> str:
    return str(txt or "").strip().lower()


def construir_prompt_generacion(ra_texto: str, bloom: str, n: int, dificultad: str,
                                n_alternativas: int = 4, norma: str | None = None,
                                contexto: str | None = None) -> tuple[str, str]:
    """Arma (system, user) para generar `n` preguntas de alternativas. Funcion pura."""
    bloom_n = _norm(bloom)
    verbos = BLOOM_VERBOS.get(bloom_n, "aplicar el concepto")
    letras = ", ".join(_LETRAS[:n_alternativas])

    system = (
        "Eres un experto en evaluacion educativa y redaccion de items de opcion multiple. "
        "Generas preguntas alineadas a un Resultado de Aprendizaje (RA) y a un nivel de la "
        "taxonomia de Bloom. Cada pregunta tiene UNA sola alternativa correcta y distractores "
        "plausibles (no absurdos), sin 'todas las anteriores' ni 'ninguna de las anteriores'. "
        "Respondes SOLO con un arreglo JSON, sin texto adicional.")

    partes = [
        f"RESULTADO DE APRENDIZAJE (preservalo como referencia, no lo cites literal en el enunciado):\n\"{ra_texto}\"",
        f"NIVEL DE BLOOM: {bloom_n or 'aplicar'} (usa verbos como: {verbos}).",
        _DIFICULTAD.get(_norm(dificultad), _DIFICULTAD["media"]),
        f"Genera EXACTAMENTE {n} preguntas, cada una con {n_alternativas} alternativas ({letras}).",
    ]
    if norma:
        partes.append(f"NORMA TERMINOLOGICA: usa la terminologia de la norma {norma}.")
    if contexto:
        partes.append(f"CONTEXTO/TEMA especifico a cubrir: {contexto}.")
    partes.append(
        "\nDevuelve SOLO este JSON (un arreglo):\n"
        '[{"enunciado": "<pregunta>", '
        '"alternativas": {"A": "<texto>", "B": "<texto>", ...}, '
        '"correcta": "<letra>", '
        '"justificacion": "<por que la correcta lo es, en una frase>", '
        '"distractores": {"<letra>": "<que error refleja>", ...}}]')
    return system, "\n".join(partes)


def _validar_pregunta(obj: dict, n_alternativas: int) -> dict | None:
    """Normaliza una pregunta del modelo; None si es inservible."""
    enun = str(obj.get("enunciado", "")).strip()
    alts_in = obj.get("alternativas") or {}
    if not enun or not isinstance(alts_in, dict):
        return None
    alternativas: dict[str, str] = {}
    for letra in _LETRAS[:n_alternativas]:
        val = alts_in.get(letra) or alts_in.get(letra.lower())
        if val is None:
            continue
        alternativas[letra] = str(val).strip()
    if len(alternativas) < 2:
        return None
    correcta = str(obj.get("correcta", "")).strip().upper()[:1]
    if correcta not in alternativas:
        return None
    return {
        "enunciado": enun,
        "alternativas": alternativas,
        "correcta": correcta,
        "justificacion": str(obj.get("justificacion", ""))[:400],
        "distractores": {k: str(v)[:200] for k, v in (obj.get("distractores") or {}).items()
                         if k in alternativas and k != correcta},
    }


def parsear_preguntas(texto: str, n_alternativas: int = 4) -> list[dict]:
    """Extrae y valida el arreglo JSON del modelo -> lista de preguntas normalizadas."""
    t = (texto or "").strip()
    i, j = t.find("["), t.rfind("]")
    if i == -1 or j == -1 or j < i:
        raise ValueError("La respuesta del modelo no contiene un arreglo JSON.")
    data = json.loads(t[i:j + 1])
    if not isinstance(data, list):
        raise ValueError("Se esperaba un arreglo de preguntas.")
    preguntas = [p for p in (_validar_pregunta(o, n_alternativas) for o in data if isinstance(o, dict)) if p]
    if not preguntas:
        raise ValueError("El modelo no devolvio preguntas validas.")
    return preguntas


def _con_meta(q: dict, ra_code, bloom, dificultad, origen) -> dict:
    """Adjunta la trazabilidad C3 y marca el item como borrador (G1)."""
    return {**q, "ra_code": ra_code, "bloom": _norm(bloom) or None,
            "dificultad": _norm(dificultad) or "media", "origen": origen, "borrador": True}


def _plantilla(ra_texto, bloom, n, dificultad, n_alternativas, ra_code) -> list[dict]:
    """Andamio determinista cuando no hay LLM: el docente completa. Honesto, no inventa."""
    letras = _LETRAS[:n_alternativas]
    verbo = BLOOM_VERBOS.get(_norm(bloom), "aplicar").split(",")[0]
    salida = []
    for k in range(1, n + 1):
        alternativas = {letras[0]: "(completa la alternativa correcta)"}
        for L in letras[1:]:
            alternativas[L] = "(completa un distractor plausible)"
        q = {
            "enunciado": f"(Borrador {k}) Redacta una pregunta para «{verbo}» sobre: "
                         f"{ra_texto[:160]}",
            "alternativas": alternativas,
            "correcta": letras[0],
            "justificacion": "(completa: por que la correcta lo es)",
            "distractores": {},
        }
        salida.append(_con_meta(q, ra_code, bloom, dificultad, "plantilla"))
    return salida


def _llamar_anthropic(modelo: str = MODELO_DEFECTO):
    def _llamar(system: str, user: str) -> str:  # pragma: no cover (requiere API)
        import anthropic
        cliente = anthropic.Anthropic()
        msg = cliente.messages.create(
            model=modelo, max_tokens=350, system=system,
            messages=[{"role": "user", "content": user}])
        return msg.content[0].text
    return _llamar


def generador_por_defecto():
    """`llamar` real si hay ANTHROPIC_API_KEY; si no None -> se usa la plantilla."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _llamar_anthropic()
    return None


def generar_preguntas(ra_texto: str, bloom: str, n: int = 5, dificultad: str = "media", *,
                      ra_code=None, n_alternativas: int = 4, norma: str | None = None,
                      contexto: str | None = None, llamar=None) -> dict:
    """Genera `n` preguntas alineadas a C3. LLM si hay key; plantilla en su defecto.

    Devuelve siempre {preguntas, meta, origen}. `preguntas` son BORRADORES: requieren
    aprobacion docente antes de entrar a la pauta (G1).
    """
    n = max(1, min(20, int(n)))
    n_alternativas = max(2, min(len(_LETRAS), int(n_alternativas)))
    if not str(ra_texto or "").strip():
        from app.core.errors import unprocessable
        raise unprocessable("Falta el texto del Resultado de Aprendizaje (RA).")

    llamar = llamar or generador_por_defecto()
    origen = "ia"
    if llamar is None:
        preguntas = _plantilla(ra_texto, bloom, n, dificultad, n_alternativas, ra_code)
        origen = "plantilla"
    else:
        try:
            system, user = construir_prompt_generacion(
                ra_texto, bloom, n, dificultad, n_alternativas, norma, contexto)
            crudas = parsear_preguntas(llamar(system, user), n_alternativas)
            preguntas = [_con_meta(q, ra_code, bloom, dificultad, "ia") for q in crudas][:n]
        except Exception:
            preguntas = _plantilla(ra_texto, bloom, n, dificultad, n_alternativas, ra_code)
            origen = "plantilla"

    return {
        "preguntas": preguntas,
        "meta": {"ra_code": ra_code, "bloom": _norm(bloom) or None,
                 "dificultad": _norm(dificultad) or "media",
                 "n_solicitadas": n, "n_generadas": len(preguntas),
                 "n_alternativas": n_alternativas},
        "origen": origen,
        "aviso": "Borradores generados por IA: requieren revision y aprobacion del docente "
                 "antes de incorporarse a una pauta (G1). Cada pregunta queda trazada a su RA "
                 "y nivel de Bloom (C3).",
    }
