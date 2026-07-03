# PLAN 14 DÍAS · EVALYS → 6 DE JUNIO 2026

**Dos entregas obligatorias el 6 de junio:**
1. **Dossier ModUSS** entregado (formulario + documento + carta decano)
2. **App lista para piloto** con docentes reales del Depto. de Ciencias

**Decisión de alcance del motor de prueba abierta:** flujo demostrable de punta a punta
con 1 caso real bien hecho (no el motor industrial completo, que es Fase F-G post-piloto).

---

## PRINCIPIO RECTOR (leer cada mañana)

> Todo lo que no sea (a) el dossier, (b) el camino feliz de selección múltiple, o
> (c) el flujo demostrable de prueba abierta con informe nivel Rojas — **se posterga sin culpa.**

NO se construye en estos 14 días: motor multicapa robusto, auditoría graduada completa,
módulo investigador (IRT/factorial), las 8 plantillas, refactor a Vite, rediseño visual masivo.
Todo eso es post-piloto y el dossier ya lo documenta como Fase F-G.

---

## LO QUE YA ESTÁ LISTO (confirmado en sesiones)

- Backend FastAPI vivo en Railway (auth, courses, assessments, answer-keys, scans, results, feedback)
- Login real funcionando (fix AbortController contra Grammarly)
- CRUD de cursos contra backend (persiste, sobrevive recarga)
- Estudiantes: importar Excel + agregar manual (fix de visualización aplicado, falta confirmar)
- Informe caso Rojas: plantilla HTML impecable (hoy estática/hardcodeada)
- Gobernanza de datos documentada (9 capas, Ley 21.719, postura propositiva)
- Dossier al Director ya redactado (v1.0) — base para el dossier del fondo

---

## LOS TRES FRENTES DE TRABAJO

### FRENTE A · Camino feliz selección múltiple (la base del piloto)
Curso → nómina → evaluación → pauta → escaneo OCR → resultados → informe.
Estado: cursos y estudiantes OK; falta verificar evaluación, pauta, escaneo, resultados.

### FRENTE B · Flujo demostrable de prueba abierta (el diferenciador)
Especialista parametriza (rúbrica + RA + corpus) → IA califica 1 caso real →
informe cuali-cuanti nivel Rojas. Es lo más nuevo; hay que construirlo.

### FRENTE C · Dossier ModUSS (entrega con fecha dura)
Redacción conforme a bases del fondo: problema, solución, objetivos del piloto,
metodología, impacto (retención/progresión/calidad docente), presupuesto mensual,
carta decano. Apoyado en el dossier al Director ya existente.

---

## CRONOGRAMA DÍA POR DÍA

### BLOQUE 1 · Cerrar la base técnica (días 1-5: 23-27 may)

**Día 1 · sáb 23 may (HOY)**
- [x] Diagnóstico estratégico y plan maestro (este documento)
- [ ] Descargar fix de estudiantes, confirmar que se ven los 3 estudiantes
- [ ] Commit + push del fix de estudiantes

**Día 2 · dom 24 may**
- [ ] Recorrer camino feliz selección múltiple: crear evaluación en Morfología Humana
- [ ] Verificar carga de pauta (answer-key)
- [ ] Anotar qué funciona y qué se rompe

**Día 3 · lun 25 may**
- [ ] Probar escaneo OCR con material real (hojas de respuesta reales)
- [ ] Verificar pantalla de resultados
- [ ] Reparar lo que el recorrido haya revelado roto

**Día 4 · mar 26 may**
- [ ] Cerrar bugs del camino feliz selección múltiple
- [ ] Confirmar recorrido completo de punta a punta sin trabarse
- [ ] Commit estable "camino feliz selección múltiple completo"

**Día 5 · mié 27 may**
- [ ] Diseñar el flujo de parametrización de prueba abierta (rúbrica + RA + corpus)
- [ ] Definir contrato de datos del informe dinámico (qué reemplaza al Rojas hardcodeado)

### BLOQUE 2 · Flujo de prueba abierta + arranque dossier (días 6-10: 28 may-1 jun)

**Día 6 · jue 28 may**
- [ ] Construir UI de parametrización de prueba abierta (formulario especialista)
- [ ] Conectar con backend (o definir cómo se persiste la rúbrica/corpus)

**Día 7 · vie 29 may**
- [ ] Conectar calificación con IA para 1 caso real (1 estudiante, 1 prueba abierta)
- [ ] Refactor del informe Rojas: de hardcodeado a renderInformeIndividual(datos)

**Día 8 · sáb 30 may**
- [ ] Generar el primer informe cuali-cuanti dinámico de prueba abierta
- [ ] Validar que el nivel de calidad iguala al caso Rojas
- [ ] Commit "flujo demostrable prueba abierta"

**Día 9 · dom 31 may**
- [ ] DOSSIER: redactar borrador completo (problema, solución, objetivos, metodología)
- [ ] Confirmar carta del decano

**Día 10 · lun 1 jun**
- [ ] DOSSIER: presupuesto mensual + impacto ModUSS + replicabilidad
- [ ] Revisar conformidad con Gobernanza (9 capas, postura propositiva)

### BLOQUE 3 · Prueba real y pulido final (días 11-14: 2-5 jun)

**Día 11 · mar 2 jun**
- [ ] Prueba real con un docente del piloto: recorrido completo con su material
- [ ] Anotar fricciones reales

**Día 12 · mié 3 jun**
- [ ] Pulir app según fricciones detectadas
- [ ] Blindar contra Grammarly; ocultar jerga técnica ("Configurar endpoint")
- [ ] Limpiar cursos de prueba

**Día 13 · jue 4 jun**
- [ ] Revisión final dossier (lectura completa, coherencia, formato)
- [ ] Revisión final app (recorrido completo una vez más)

**Día 14 · vie 5 jun**
- [ ] Margen / imprevistos / últimos ajustes
- [ ] Preparar entrega

**SÁB 6 JUN · ENTREGA**

---

## RIESGOS Y MITIGACIONES

| Riesgo | Mitigación |
|---|---|
| El flujo de prueba abierta es lo más incierto | Limitarlo a 1 caso real bien hecho; no generalizar |
| El escaneo OCR puede fallar con material real | Probar temprano (día 3); si falla, priorizar |
| Bugs ocultos en el camino feliz | Recorrido completo temprano para descubrirlos ya |
| Grammarly rompe login en docentes del piloto | Blindaje día 12 + nota de recomendación |
| Dossier se come el tiempo técnico | Tiene bloque propio (días 9-10) y fecha dura |

---

## NOTAS DE GOBERNANZA (innegociables en todo lo que se construya)

- Postura propositiva, no auditora (lenguaje del informe y la UI)
- Ley 21.719: datos de estudiantes protegidos, consentimiento informado
- Disclaimer metodológico en cada informe (como el del caso Rojas)
- Backend manda: datos centralizados en Railway, no en navegadores aislados
- El informe es "evidencia parcial", no veredicto curricular ni administrativo
