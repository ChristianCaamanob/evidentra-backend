from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.db import create_db_and_seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_seed()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# CORS — en producción acepta cualquier origen para permitir el HTML estático
cors_origins = settings.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r".*" if "*" in cors_origins else None,
    allow_credentials="*" not in cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["health"])
def root():
    """Ruta raíz — confirma que el servidor está vivo."""
    return {"service": "evidentra-backend-mvp", "status": "ok"}

