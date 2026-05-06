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

# CORS — allow_origins=["*"] es incompatible con allow_credentials=True.
# Para demo pública usamos allow_origins=["*"] y allow_credentials=False.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["health"])
def root():
    return {"service": "evidentra-backend-mvp", "status": "ok"}

