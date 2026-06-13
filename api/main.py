from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from agent.core.config import settings
from agent.core.database import AsyncSessionFactory
from agent.core.queue import queue
from agent.scheduler.service import scheduler_service
from api.routes import (
    agents,
    analytics,
    channel_onboarding,
    channels,
    config,
    content_planning,
    distribution,
    engagement,
    markets,
    media,
    media_serve,
    projects,
    scheduler,
    cost,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await queue.connect()
    if settings.scheduler_enabled:
        await scheduler_service.start()
    logger.info("API démarrée — Redis connecté")
    yield
    await scheduler_service.stop()
    await queue.disconnect()


app = FastAPI(
    title="CuteVideo Agent API",
    description="Pipeline IA multi-agents de génération de vidéos éducatives",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    redirect_slashes=False,
)

_cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(channel_onboarding.router)
app.include_router(channels.router)
app.include_router(projects.router)
if settings.storage_backend == "local":
    app.include_router(media_serve.router)
app.include_router(agents.router)
app.include_router(media.router)
app.include_router(analytics.router)
app.include_router(content_planning.router)
app.include_router(distribution.router)
app.include_router(engagement.router)
app.include_router(config.router)
app.include_router(scheduler.router)
app.include_router(cost.router)
app.include_router(markets.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Erreur non gérée %s %s : %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


@app.get("/health")
async def health() -> dict:
    db_ok = False
    redis_ok = False
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        pass
    try:
        await queue.client.ping()
        redis_ok = True
    except Exception:
        pass
    status = "ok" if db_ok and redis_ok else "degraded"
    return {
        "status": status,
        "database": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "scheduler": "running" if scheduler_service.running else "stopped",
    }
