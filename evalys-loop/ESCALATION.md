# Evalys - Escalamiento (gates humanos)

_Actualizado: 2026-07-03T20:29:50+00:00_

Estos hitos NO avanzan sin tu validacion (gobernanza Ley 21.719). Para habilitar
cada uno, agrega su id a `human_approvals` en `loop_config.json` tras revisarlo.

| Hito | Gate | Por que requiere tu validacion |
|---|---|---|
| **C3-tag-items** | G1 | El mapeo item->RA->Bloom es juicio pedagogico: la IA lo propone, el especialista lo valida. |
| **E2-generacion-rica** | G1+G2 | Retroalimentacion rica con IA: requiere vista seudonimizada (G2) y validacion docente del contenido (G1). |
| **F2-precalifica-desarrollo** | G1+G2+G4 | La IA pre-califica desarrollo; la nota queda PENDIENTE de validacion docente (indelegable) + consentimiento (G4). |
| **F3-validacion-docente** | G1+G5 | Flujo de aprobacion docente con trazabilidad; depende de F2. |

> **E4-e2e** queda `pending`: depende de E2 (gate humano). Se desbloquea cuando validas E2.
