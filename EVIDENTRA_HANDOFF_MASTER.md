# EVIDENTRA_HANDOFF_MASTER

## 1. Qué es Evidentra

**Evidentra** es una **plataforma de inteligencia académica e investigación**.  
No debe entenderse como una simple app de notas, dashboard genérico o sistema aislado de evaluación.

Su propósito es **transformar programas, evaluaciones, pautas, resultados, briefings y trazabilidad del logro de resultados de aprendizaje en evidencia útil para la toma de decisiones**.

## 2. Lógica central del proyecto

Evidentra tiene una lógica de **doble horizonte**:

### A. Corto plazo
Orientado a la asignatura y al estudiante que la cursa:
- detectar brechas por unidad, tópico, resultado de aprendizaje o competencia
- apoyar la retroalimentación diferenciada
- focalizar reforzamiento y apoyo oportuno
- orientar decisiones docentes durante el desarrollo del curso

### B. Mediano y largo plazo
Orientado a gestión académica y mejora curricular:
- identificar patrones persistentes de bajo logro
- revisar contenidos sensibles
- sustentar reformulación de programas
- ajustar estrategias de enseñanza y evaluación
- fortalecer la coherencia entre resultados de aprendizaje, perfil de egreso y exigencias del entorno profesional y disciplinar
- apoyar aseguramiento de la calidad y mejoramiento continuo

## 3. Posicionamiento institucional

El proyecto debe mantenerse alineado con dos marcos estratégicos:

### Fondo Concursable IA USS 2026
El proyecto fue alineado especialmente con el área:

**C. Innovación, procesos y gestión basada en IA**

Esto significa que Evidentra se presenta como:
- herramienta / sistema basado en IA
- optimizador de procesos académicos
- generador de evidencia
- apoyo a la toma de decisiones
- piloto institucional factible y escalable

### Proyecto Educativo USS
El proyecto se articula con estos ejes:
- experiencia del estudiante
- logro de aprendizajes y desempeños esperados al egresar
- formación integral
- efectividad educativa
- aseguramiento de la calidad
- mejoramiento continuo
- perfil de egreso
- pertinencia con el entorno profesional y disciplinar

## 4. Qué NO debe pasar

Quien continúe este proyecto **no debe**:

- reducir Evidentra a una app de notas
- simplificarlo como un LMS
- convertirlo en un dashboard académico genérico
- eliminar la capa Research autónoma
- romper la lógica premium/institucional del diseño
- perder la lógica de doble horizonte (apoyo inmediato + mejora estructural)
- banalizar su dimensión institucional, curricular o estratégica

## 5. Identidad visual y UX

La versión visual más actual está en el canvas y en el archivo:

**Evidentra Landing App Preview**

Rasgos clave:
- estética premium e institucional
- layout de 3 paneles:
  - fuentes / contexto
  - workspace principal
  - studio / artefactos
- fuerte uso de microinteracciones
- narrativa de producto serio, avanzado y escalable
- mezcla equilibrada entre académico e investigador
- cada módulo debe sentirse como parte del mismo ecosistema

## 6. Flujo núcleo del MVP

El recorrido principal del MVP quedó definido así:

1. Curso  
2. Nómina  
3. Evaluación  
4. Pauta  
5. Escaneo  
6. Resultado inmediato  
7. Retroalimentación  
8. Historial  
9. Dataset de investigación  
10. Analítica  
11. Exportación  

Además, existe una **Ruta del MVP** visible dentro de la preview para reforzar el recorrido:

**Curso → Evaluación → Pauta → Escaneo → Resultado → Briefing**

## 7. Estado actual del proyecto

### Ya existe:
- preview avanzada en canvas
- versión visual/conceptual muy desarrollada
- frontend modular
- backend MVP FastAPI
- conexión conceptual frontend-backend
- narrativa institucional bastante consolidada
- alineación estratégica con fondo IA USS y Proyecto Educativo USS

### Frontend
Existe un scaffold del frontend conectado al backend MVP.

### Backend
Existe un backend MVP en FastAPI con módulos base:
- courses
- assessments
- answer_keys
- scans
- results
- feedback

## 8. Decisiones técnicas ya tomadas

### Frontend
- React / Next
- TypeScript
- Tailwind
- Framer Motion
- Zustand
- TanStack Query

### Backend
- FastAPI
- SQLAlchemy / Pydantic
- modular por dominios
- readiness calculado
- flujo MVP acotado
- bootstrap seed para pruebas

### Principio clave
El frontend no debería inventar estados críticos de negocio.
Los estados centrales deben venir del backend o quedar claramente alineados con él.

## 9. Módulos conceptuales clave

### Curso
Unidad madre de configuración académica:
- programa
- RA
- competencias
- unidades
- escala
- exigencia
- herencia hacia evaluación

### Nómina
Base para:
- escaneo
- historial
- trazabilidad
- exportación
- seguimiento longitudinal

### Evaluación
Debe resolver:
- duplicación de evaluaciones
- escala / exigencia
- documento fuente
- versiones
- vínculo con pauta
- vínculo con briefing

### Pauta
Debe resolver:
- anulaciones
- ponderaciones
- múltiples versiones
- parciales
- validación estructural

### Escaneo
Momento wow del producto:
- lectura de hoja
- detección de versión
- ambigüedad real
- revisión docente solo cuando corresponde

### Resultado
No solo nota:
- puntaje
- porcentaje
- nota
- percentil
- lectura comparativa
- habilitación de briefings, historial y exportación

### Retroalimentación
Corazón diferencial del producto:
- briefing académico
- briefing estudiantil
- informe de calidad
- capa research

### Historial
Seguimiento longitudinal:
- trayectoria individual
- trayectoria de cohorte
- impacto de intervenciones
- base para calidad e investigación

### Dataset de investigación
Módulo autónomo:
- no depende de cursos
- no depende de nóminas
- no depende de evaluación académica
- permite importar datos externos y operar como producto Research dentro del ecosistema

### Analítica
Debe entregar:
- filtros
- estadísticas
- figuras
- discusión preliminar
- conclusiones tentativas

### Exportación
Debe separar:
- salida académica
- salida research
- salida de calidad

## 10. Qué valor ofrece realmente Evidentra

La ventaja real no está solo en ver datos.

La ventaja está en reducir trabajo de:
- limpieza
- organización
- comparación
- visualización
- reporte
- interpretación
- transformación de resultados en decisiones

En el perfil investigador, además, debe ayudar a:
- confrontar hallazgos con literatura
- generar focos de discusión
- producir conclusiones tentativas
- acelerar manuscritos, informes, posters o presentaciones

## 11. Estado de los archivos principales

### Archivos a compartir
1. `evidentra-mvp-frontend-connected.zip`
2. `evidentra-backend-mvp.zip`
3. `Evidentra-Landing-App-Preview-latest.tsx`
4. `Bases-FFCC-IA-2026.pdf`
5. `PROYECTO_EDUCATIVO_2023.pdf`

## 12. Prioridades de continuidad

La continuidad ideal debe seguir este orden:

### Prioridad 1
Preservar identidad conceptual y visual del proyecto.

### Prioridad 2
No simplificar la propuesta de valor institucional.

### Prioridad 3
Fortalecer frontend real y consistencia entre módulos.

### Prioridad 4
Conectar y estabilizar integración backend-frontend.

### Prioridad 5
Seguir ampliando lógica académica, longitudinal y research sin romper foco del MVP.

## 13. Cómo debe trabajar quien continúe esto

Antes de programar, debe:
1. resumir qué entendió del proyecto
2. identificar qué ya está resuelto
3. detectar huecos técnicos y conceptuales
4. proponer un plan
5. ejecutar sin degradar identidad ni alcance

## 14. Prompt maestro sugerido para continuidad

Quiero que continúes el desarrollo de mi proyecto Evidentra con máxima fidelidad conceptual, técnica y estratégica.

Evidentra no es solo una plataforma de evaluación. Es una plataforma de inteligencia académica e investigación orientada a transformar programas, evaluaciones, pautas, resultados, briefings y trazabilidad del logro de resultados de aprendizaje en evidencia útil para la toma de decisiones.

El proyecto tiene una lógica de doble horizonte:
1. corto plazo: apoyo al estudiante, reforzamiento, retroalimentación y decisiones docentes dentro de la asignatura en curso;
2. mediano y largo plazo: revisión de programas, ajuste de estrategias de enseñanza y evaluación, fortalecimiento del logro de resultados de aprendizaje, coherencia con perfil de egreso y aseguramiento de la calidad.

Contexto institucional:
- El proyecto debe alinearse con el Fondo Concursable IA USS 2026, especialmente con el área C: Innovación, procesos y gestión basada en IA.
- También debe alinearse con el Proyecto Educativo USS: experiencia del estudiante, logro de aprendizajes y desempeños esperados al egresar, formación integral, efectividad educativa, aseguramiento de la calidad y mejoramiento continuo.

Estado actual:
- Existe una versión visual avanzada en canvas llamada “Evidentra Landing App Preview”.
- Existe un frontend modular conectado conceptualmente al backend.
- Existe un backend MVP en FastAPI.
- La estética premium, la narrativa institucional y la lógica del MVP ya están bastante definidas.

Flujo núcleo del MVP:
Curso → Nómina → Evaluación → Pauta → Escaneo → Resultado inmediato → Retroalimentación → Historial → Dataset Research → Analítica → Exportación.

Lo que necesito de ti:
1. Primero, resume tu comprensión del proyecto en términos de propósito, arquitectura, UX, negocio e institucionalidad.
2. Luego identifica qué está ya resuelto, qué está incompleto y qué riesgos ves.
3. Después continúa el trabajo sin simplificar el producto ni banalizar su propuesta de valor.
4. Mantén el lenguaje institucional, académico y estratégico del proyecto.
5. No lo reduzcas a una app de notas ni a un dashboard genérico.
6. Respeta la coexistencia de dos perfiles fuertes:
   - perfil académico/docente
   - perfil investigador autónomo
7. Si propones cambios, explícame cómo impactan arquitectura, UX, factibilidad y alineación institucional.

Tu prioridad es preservar la identidad del proyecto y hacerlo avanzar con criterio de producto serio, premium, institucional y escalable.
