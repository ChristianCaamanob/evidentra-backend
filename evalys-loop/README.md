# Evalys — Loop de avance autónomo

Andamiaje para que Evalys avance **sin que tengas que estar mirando cada 30 minutos**.

La idea de fondo es simple y es la que hace posible dejarlo corriendo solo:
un loop puede correr sin ti **solo si sabe verificarse solo**. Por eso el trabajo
de verdad no es automatizar el *hacer*, sino automatizar el *comprobar*. Cada hito
tiene una Definition of Done comprobable (tests), toda la corrida respeta guardas
de gobernanza, y cuando algo no pasa **no hay commit y no se marca como hecho**.

---

## Qué es cada pieza

```
evalys-loop/
├── estados.json          # El ledger: la fuente de verdad. Hitos + dependencias + DoD + gates + gobernanza.
├── orchestrator.py       # El loop. Elige el siguiente hito, ejecuta, verifica, commitea o escala.
├── loop_config.json      # Motor, modelos, presupuesto, aprobaciones de gates, ruta al repo.
├── checks/
│   ├── check_seudonimizacion.py   # Guarda G2: ningún nombre/RUT/correo llega a la IA.
│   ├── check_propositiva.py       # Guarda G6: lenguaje propositivo, no auditor.
│   └── run_all_checks.py          # Corre todas las guardas (el loop las llama cada iteración).
├── tests/
│   ├── test_baseline.py           # Suite verde: consistencia del ledger (DoD del hito F0-git).
│   └── test_datos_shape.py        # Spec del contrato `datos` (se activa al implementar E1).
├── fixtures/             # Ejemplos malos a propósito para el self-test de las guardas.
├── reportes/             # Artefactos que el loop deja para tu revisión en los gates humanos.
├── PROGRESS.md           # Vista humana del avance (se regenera sola).
├── ESCALATION.md         # Donde el loop te avisa cuando se atasca o llega a un gate.
└── loop_log.jsonl        # Bitácora estructurada de todo lo que hizo.
```

---

## Cómo se usa

```bash
# Ver el estado de los hitos
python orchestrator.py --status

# PREVIEW seguro (por defecto): recorre el mapa sin ejecutar el agente ni commitear.
# Muestra el orden y dónde están los gates humanos.
python orchestrator.py

# Correr DE VERDAD (agente + verificación + commits):
python orchestrator.py --run

# Regenerar la vista de avance / reiniciar el ledger
python orchestrator.py --progress
python orchestrator.py --reset
```

**Por defecto corre en dry-run** (no toca nada). Recién con `--run` ejecuta el agente
y hace commits.

### Antes de correr `--run`

1. **Apunta `code_root`** en `loop_config.json` al repo real de Evalys
   (backend/front). Por defecto es `.` para poder probar el dry-run desde acá.

2. **Elige el motor** (`engine` en la config):
   - `claude_code` (recomendado): delega en Claude Code, que ya sabe editar
     archivos, correr comandos y tests en loop. Necesitas Claude Code instalado.
   - `api`: orquesta la API de Claude directamente (necesitas `ANTHROPIC_API_KEY`
     y `pip install anthropic`). El esqueleto está; para que edite archivos hay que
     completarle el bucle de herramientas (tool-use).

3. **Trabaja con git** en el repo Evalys. Es lo que hace que "destruir y reconstruir"
   sea **reversible**: puedes ser todo lo agresivo que quieras porque siempre puedes
   volver atrás.

---

## Los gates de gobernanza (no negociables)

Salen directo de tu doc de gobernanza (Ley 21.719). El loop **no puede eludirlos**:

| Gate | Regla | Cómo se aplica |
|---|---|---|
| **G1** IA no decide | La IA pre-califica; la nota final es del docente (indelegable). | Todo hito que califica lleva **gate humano**: no se cierra sin tu validación. |
| **G2** Seudonimización | Ningún dato identificatorio viaja a la IA. | Check automático **en cada iteración**; si un identificador real llega a un call, la iteración falla. |
| **G3** Export ética | Exports de investigación requieren IRB. | Gate humano en esos hitos. |
| **G4** Consentimiento | Features de IA/investigación requieren opt-in. | Flag verificado. |
| **G5** Audit + RLS | Acceso registrado y protegido. | Invariante. |
| **G6** Propositiva | Nada de "auditar el currículo". | Check automático de lenguaje. |

Los hitos con gate humano (`C3`, `E2`, `F2`, `F3`) **no avanzan** hasta que los revisas
tú y agregas su id a `human_approvals` en `loop_config.json`. Ejemplo:

```json
"human_approvals": ["C3-tag-items"]
```

Mientras tanto el loop **hace todo lo demás** y te deja los gates marcados como
`needs_review` en `ESCALATION.md`.

---

## Los modelos

En `loop_config.json > models`:
- `exec` → modelo de ejecución para el grueso del trabajo (por defecto **Sonnet 5**).
- `planner` → modelo más potente para los pasos difíciles (por defecto **Opus 4.8**).

Cada hito declara su `model_tier`. Los hitos de arquitectura/juicio pedagógico
(etiquetado RA/Bloom, generación rica, pre-calificación) usan `planner`.

**Sobre Fable 5:** es una opción válida para `planner`, pero trae salvaguardas —algunas
consultas se redirigen a Opus 4.8— y es más nuevo/menos disponible. Por eso el default
de `planner` es Opus 4.8: un loop no debería depender de que siempre conteste Fable.
Puedes cambiarlo a `claude-fable-5` cuando quieras. Verifica strings de modelo y
disponibilidad en la documentación de la API.

### Escalamiento adaptativo (Sonnet 5 → Opus 4.8)

Además del ruteo por hito, el loop **sube de modelo solo cuando un hito `exec` se
atasca**. Config: `budget.escalate_model_after` en `loop_config.json`.

- Con `escalate_model_after: 1` y `max_repairs: 2` (3 intentos): el hito arranca en
  Sonnet 5; si el primer intento falla (guardas o aceptación en rojo), los intentos
  restantes corren en Opus 4.8.
- Los hitos que ya son `planner` no escalan (ya están en el modelo más fuerte).
- `escalate_model_after: 0` desactiva el escalamiento.

Así lo barato corre en Sonnet mientras alcance, y solo pagas Opus donde de verdad se
traba. Cada subida queda en el log como `MODEL_ESCALATION`. La lógica está cubierta por
`tests/test_model_escalation.py`.

---

## Cómo se logra "sin estar cada 30 minutos"

Cuatro cosas, juntas:

1. **Auto-verificación**: cada hito se da por hecho solo si sus tests pasan. Eso
   reemplaza tus ojos.
2. **Guardas de gobernanza en cada iteración**: el loop no puede "mejorarse" hacia una
   violación (mandar un RUT a la IA, meter lenguaje auditor).
3. **Gates humanos solo donde importa**: calificaciones, mapeos pedagógicos, exports.
   No cada 30 min: solo en esos puntos.
4. **Parada + escalamiento**: topes de iteraciones/tiempo, y si se atasca **te avisa**
   (ESCALATION.md o webhook) en vez de quemar tokens en círculos.

---

## Qué está construido y qué falta (honesto)

**Construido y probado en dry-run:** el ledger completo (12 hitos aterrizados en tu
roadmap y gobernanza), las guardas G2 y G6 ejecutables, el orquestador (máquina de
estados + gates + presupuesto + escalamiento + git + tests), la vista de avance y la
suite baseline en verde.

**Lo que necesita tu entorno:** el "cerebro" (`agent_step`) que produce el código de
cada hito. Es el único punto que requiere tu `ANTHROPIC_API_KEY` o Claude Code
instalado. Está como *seam* limpio y documentado.

**Lo que todavía no existe:** la implementación real de cada hito (el modelo RA/Bloom,
el endpoint `datos`, la generación rica, el módulo de desarrollo). Eso lo produce el
agente cuando corras `--run`. Acá está el **arnés que lo conduce con red**, no los
hitos en sí. Es a propósito: el arnés es lo difícil y lo que te deja soltar el loop
sin miedo; el resto es trabajo que el loop ya sabe cómo verificar.

---

## Primer blanco listo: el test de aceptación de C1

En `acceptance/` está el primer criterio de aceptación real, `test_model_ra_bloom.py`,
que define el "done" del hito `C1-model-ra-bloom` contra el modelo real `AnswerKeyItem`.

Está **probado**: contra el modelo actual da 3 rojos + 1 skip (los campos RA/Bloom no
existen); con los tres campos nullable + la migración, da 4 verdes. Es el gate que el
agente tiene que poner en verde cuando implemente C1.

Cópialo a `<repo Evalys>/tests/` (ver `acceptance/README.md`). El ledger ya apunta C1 a
`pytest -q tests/test_model_ra_bloom.py`.
