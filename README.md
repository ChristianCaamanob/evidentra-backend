# Evidentra Backend MVP

Backend scaffold del flujo núcleo de Evidentra:

Curso → Evaluación → Pauta → Escaneo → Resultado → Feedback

## Stack
- FastAPI
- SQLAlchemy 2
- Pydantic v2
- SQLite por defecto para levantar rápido
- PostgreSQL configurable vía `DATABASE_URL`

## Endpoints del MVP
- `GET /api/v1/health`
- `GET /api/v1/courses/{course_id}`
- `GET /api/v1/courses/{course_id}/readiness`
- `POST /api/v1/courses/{course_id}/complete-structure`
- `POST /api/v1/courses/{course_id}/activate`
- `GET /api/v1/assessments/{assessment_id}`
- `GET /api/v1/assessments/{assessment_id}/readiness`
- `POST /api/v1/assessments/{assessment_id}/attach-document`
- `POST /api/v1/assessments/{assessment_id}/activate`
- `GET /api/v1/answer-keys/{assessment_id}/validation`
- `POST /api/v1/answer-keys/{assessment_id}/validate`
- `GET /api/v1/scans/{scan_id}/review`
- `POST /api/v1/scans/{scan_id}/resolve-review`
- `GET /api/v1/results/{scan_id}`
- `GET /api/v1/feedback/{assessment_id}?artifact=academic|student|quality|research`

## Levantar localmente
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## Notas
- En el arranque se crean tablas y se siembra un dataset mínimo del MVP si no existe.
- Por defecto usa SQLite para que puedas probarlo al instante.
- Para PostgreSQL, cambia `DATABASE_URL` en `.env`.
