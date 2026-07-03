# Inventario de pendientes · Evalys
## Estado actual de la maqueta vs. lo prometido al Director

**Fecha:** 19 mayo 2026  
**Versión revisada:** evalys-app.html · commit `bedf14b` + eliminación tabla redundante

---

## A · Lo que YA está construido y funciona

### A.1 · Estructura general
- Portada / login con tres perfiles (estudiante, docente, investigador)
- Símbolo Evalys clickeable → vuelve a la portada
- Sidebar con 6 items: Dashboard, Cursos, Escaneo, Pauta, Resultados, Briefings
- Dashboard con 9 tarjetas de acción (limpio, sin tabla redundante)
- Sistema de navegación entre 13 pantallas

### A.2 · Módulo 1 · Estudiante (Briefings)
- Navegación estratificada curso → prueba → estudiante → informe
- Archivo de informes por prueba con folio, estado, acciones, filtros
- Informe doctoral completo del caso Tomás Rojas (14 secciones)
- Gráficos D3 funcionales: distribución del curso + radar de Bloom
- Mapa de 25 preguntas pregunta por pregunta
- 4 bloques de brechas con casos pedagógicos
- Plan de 6 sesiones detallado
- Nota privada del docente editable
- Metadata institucional (folio, hash, calibración, modelo IA)

### A.3 · Gobernanza visible
- Política de gobernanza v1.0 documentada (Anexo II del dossier)
- Estado de entrega persistido (localStorage demo)
- Trazabilidad por informe (timestamps, hash, calibración)

---

## B · Lo que está construido PERO no es funcional sin backend

### B.1 · Pantalla "Mis cursos" (`screen-course`)
**Estado:** Spinner "Cargando cursos..." infinito sin backend.  
**Razón:** depende de `fetch /courses/`.  
**Gap:** sin fallback demo cuando backend no responde.

### B.2 · Pantalla "Detalle de curso" (`screen-course-detail`)
**Estado:** Estructura con tabs (Evaluaciones / Estudiantes / Reportes) pero cargada con `fetch`.  
**Gap:** sin fallback demo.

### B.3 · Pantalla "Nueva evaluación" (`screen-assessment`)
**Estado:** Formulario completo y funcional visualmente.  
**Gap:** sin fallback demo de evaluaciones pre-creadas.

### B.4 · Pantalla "Pauta" (`screen-answerkey`)
**Estado:** Grilla interactiva para marcar respuestas A/B/C/D/E, persistencia localStorage.  
**Gap:** funciona en demo, pero no muestra pauta "ya cargada" del Certamen N°1 de Tomás.

### B.5 · Pantalla "Escaneo" (`screen-scan`)
**Estado:** UI completa, captura por cámara o archivo, queue de revisiones.  
**Gap crítico:** No hay OCR funcional en frontend. Sin backend, no escanea nada.

### B.6 · Pantalla "Resultados" (`screen-result`)
**Estado:** Tabla y gráficos, dependientes de backend.  
**Gap:** sin fallback demo.

---

## C · Lo que ESTÁ PROMETIDO pero NO está construido

### C.1 · Módulo 2 · DOCENTE (lo que más promete el blueprint)
El blueprint lámina 03 promete: "Analítica de curso y prueba" con:
- ❌ **Psicometría completa con interpretación IA** (KR20, biserial, distractores)
- ❌ **Análisis de distractores por error conceptual**
- ❌ **Validación de tabla de especificaciones**
- ❌ **Alerta temprana de estudiantes en riesgo** (parcial: hay filtro en archivo)
- ❌ **Mapa de calor RA × Estudiante**
- ❌ **Reporte ejecutivo IA con hallazgos clave**

**Hoy existe en su lugar:** el tab "Briefing académico" con texto plano (4 párrafos).

### C.2 · Módulo 3 · INVESTIGADOR (lámina 03)
- ⚠️ Pantalla `dataset` existe pero plana
- ⚠️ Pantalla `analytics` existe pero plana
- ❌ **IRT (1PL/2PL/3PL)** — no implementado
- ❌ **Análisis factorial EFA/CFA** — no implementado
- ❌ **Cohortes y trayectorias longitudinales** — no implementado
- ❌ **DIF · Mokken · Generalizability** — no implementado
- ❌ **Exportadores Q1 (tablas APA, código reproducible)** — no implementado
- ❌ **Pre-registro OSF / DOI Zenodo** — no implementado

### C.3 · Calibración multicapa (lámina 05)
- ❌ **Capa A · Parámetros + corpus pedagógico**: subir material del docente
- ❌ **Capa B · Ejemplos few-shot**: subir pruebas ya corregidas
- ⚠️ **Capa C · Rúbrica + RA + perfil**: parcial (los datos están, pero no editables)
- ❌ **Panel de validación docente** (ligera/media/profunda)

### C.4 · Pruebas de desarrollo (Fase F del roadmap)
Todo el módulo. Es la Fase F completa, está fuera de scope para el piloto Q3.

### C.5 · Vista del docente diferenciada
- ❌ Toggle "Vista docente / Vista del estudiante" en el informe
- ❌ Ficha sintética del docente (resumen rápido del estudiante)
- ❌ Acciones de gestión que el docente necesita ver agrupadas

### C.6 · Sistema de cohorte / Briefing académico real
- ❌ Gráfico de distribución de la cohorte
- ❌ Heatmap de RA × estudiantes
- ❌ Lista de "preguntas problemáticas" del instrumento
- ❌ Alertas tempranas con criterios automáticos

### C.7 · Modelo curricular operativo (Fase C, 70%)
- ⚠️ Perfil de egreso (estructura existe, no importable)
- ⚠️ Resultados de aprendizaje (mockeado en BRIEFING_UNIVERSE)
- ❌ Importador desde Word/Excel del programa oficial
- ❌ Vinculador RA ↔ ítem (interfaz)
- ❌ Validador de tabla de especificaciones

---

## D · Lo que ESTÁ FRÁGIL y conviene reforzar

### D.1 · Coherencia del caso de demo
- **Dashboard dice "Morfología Humana"** pero **Briefings tiene Derecho Penal I como caso destacado**
- El docente Rojas Saavedra (?) vs. la prof. Cárdenas vs. Caamaño (?)
- Hay que decidir: ¿el docente logueado es de Ciencias (Morfología) o de Derecho?

### D.2 · Persistencia
- Todo el estado vive en localStorage
- Recargar limpia algunos estados, conserva otros
- No es multi-dispositivo

### D.3 · Estados vacíos
- Si no hay datos, varias pantallas quedan vacías sin guía
- No hay onboarding visible "¿qué hago primero?"

### D.4 · Coherencia visual entre pantallas
- El dashboard usa tarjetas oscuras
- Los módulos internos usan diseño claro
- El informe usa otro estilo (con header gradient)
- No es inconsistente pero podría unificarse mejor

---

## E · Lo que NO tiene maqueta pero es CRÍTICO para el piloto

### E.1 · Sistema de consentimiento del estudiante
- ❌ Pantalla de consentimiento informado al ingresar
- ❌ Panel "Mis datos y consentimientos" del estudiante
- ❌ Derechos ARCO+ operacionalizados
- **Crítico para piloto:** Comité de Ética lo exigirá

### E.2 · Vista del estudiante (M·01 desde el lado del estudiante)
- Hoy solo el docente ve el informe del estudiante
- ❌ Falta la pantalla "Mis evaluaciones" para el estudiante
- ❌ Falta la recepción del informe (notificación, link, primera apertura)
- ❌ Falta el panel de seguimiento del estudiante de sus brechas y plan

### E.3 · Integración con LMS / SSO
- ❌ Login institucional (no solo email/contraseña)
- ❌ Importación de cursos desde el sistema USS
- ❌ Sincronización de calificaciones (write-back)

---

## RESUMEN EJECUTIVO

| Frente | Para PILOTO Q3 | Para FONDO ModUSS | Prioridad |
|---|---|---|---|
| Módulo docente real (M·02) | **CRÍTICO** | **CRÍTICO** | 🔴 ALTA |
| Vista del estudiante (M·01 lado E) | **CRÍTICO** | Importante | 🔴 ALTA |
| Consentimiento informado | **OBLIGATORIO** (Ética) | Importante | 🔴 ALTA |
| Vista docente diferenciada (toggle) | Mejora UX | **Importante** | 🟡 MEDIA |
| Coherencia caso de demo | Demo limpia | **Importante** | 🟡 MEDIA |
| Fallback demo sin backend | Robustez piloto | Demo limpia | 🟡 MEDIA |
| Módulo investigador M·03 | No requerido | **Importante** | 🟡 MEDIA |
| Calibración multicapa A/B | No requerido | Diferenciador | 🟢 BAJA |
| Pruebas de desarrollo (F) | No requerido | Plan futuro | 🟢 BAJA |
| Integración LMS | No requerido | Plan futuro | 🟢 BAJA |

---

## PROPUESTA DE SPRINTS

### Sprint 1 · Coherencia y vista docente (3-4 sesiones)
- Resolver caso de demo (Morfología + Derecho como cursos del mismo docente)
- Vista docente diferenciada con toggle al informe del estudiante
- Ficha sintética del docente con acciones agrupadas

### Sprint 2 · Módulo docente real (M·02) (4-5 sesiones)
- Briefing académico enriquecido con gráficos
- Mapa de calor RA × estudiantes
- Análisis de distractores
- Alerta temprana automática

### Sprint 3 · Vista del estudiante (M·01 lado E) (3-4 sesiones)
- Pantalla "Mis evaluaciones" para estudiante
- Recepción del informe con interactividad
- Panel de seguimiento del plan de consolidación
- Sistema de consentimiento

### Sprint 4 · Estabilidad demo (2 sesiones)
- Fallback demo en todas las pantallas backend-dependientes
- Estados vacíos con guía
- Onboarding mínimo

### Sprint 5 · Stub del módulo investigador (M·03) (2-3 sesiones)
- Pantalla navegable con visualizaciones simuladas
- Suficiente para presentación a Vicerrectoría
- No implementación real de IRT/factorial todavía

### Sprint 6 · Postulación al fondo ModUSS (2-3 sesiones · documental)
- Documento formal de postulación
- Presupuesto
- Cronograma
- Indicadores y verificadores

---

**Próxima decisión:** ¿con qué sprint arrancamos?
