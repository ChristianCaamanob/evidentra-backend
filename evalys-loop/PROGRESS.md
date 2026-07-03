# Evalys - Estado de avance (2026-07-03T20:29:51+00:00)

**Objetivo:** Plataforma de inteligencia academica (Estudiante / Profesor / Investigador) que supera visiblemente a GradeCam. Horizonte cercano: reporte individual 'Nivel Evalys' -> vinculo curricular RA/Bloom -> motor de evaluacion de respuestas de desarrollo. El MVP de correccion (OCR seleccion multiple) se REUSA y se extiende; no se reescribe.

**Progreso:** 7/12 hitos


## Fundacion
- [x] **F0-git** Repositorio bajo control de versiones + CI de tests
- [x] **F0-guardas** Guardas de gobernanza automatizadas (seudonimizacion + lenguaje propositivo)

## C - Modelo curricular
- [x] **C1-model-ra-bloom** Modelo: RA + nivel Bloom + unidad por item/pregunta + migracion
- [x] **C2-import-curriculo** Importar programa / RA / tabla de especificaciones (texto original preservado)
- [?] **C3-tag-items** Etiquetado item -> RA -> Bloom (DMOR0030, 30 items) + validacion del especialista (gate humano)

## E - Reporte individual
- [x] **E1-datos-endpoint** Endpoint que ensambla el contrato `datos`
- [?] **E2-generacion-rica** Generacion cualitativa rica (brechas + plan + dimensiones Bloom) (gate humano)
- [x] **E3-render-informe** Render renderInformeIndividual(datos) en el front (Estandar Evalys)
- [ ] **E4-e2e** End-to-end verde: escaneo -> correccion -> informe individual

## F - Respuestas de desarrollo (meta)
- [x] **F1-rubric-model** Modelo de rubrica: question.type=open_response + rubric_criterion
- [?] **F2-precalifica-desarrollo** IA pre-califica respuestas de desarrollo con calibracion (parametros + corpus + few-shot) (gate humano)
- [?] **F3-validacion-docente** UI de validacion graduada del docente (auditoria ligera/media/profunda) + trazabilidad (gate humano)
