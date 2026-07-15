from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.db import create_db_and_seed
from app.core.ratelimit import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_seed()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Rate limiting (anti fuerza-bruta) — activo por defecto; los endpoints sensibles lo declaran.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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

