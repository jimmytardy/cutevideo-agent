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


@app.get("/storage/stats")
async def storage_stats() -> dict:
    from agent.core.config import get_storage_settings
    from agent.core.storage import get_used_bytes

    cfg = get_storage_settings()
    used = await get_used_bytes()
    max_bytes = cfg.max_storage_bytes
    return {
        "used_bytes": used,
        "max_bytes": max_bytes,
        "used_pct": round(used / max_bytes * 100, 1) if max_bytes else 0,
        "bucket": cfg.bucket or None,
    }


@app.get("/health")
async def health() -> dict:
    from agent.core.storage import check_s3_connectivity

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
    s3_ok, s3_detail = await check_s3_connectivity()
    overall = "ok" if db_ok and redis_ok and s3_ok else "degraded"
    return {
        "status": overall,
        "database": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "scheduler": "running" if scheduler_service.running else "stopped",
        "s3": "ok" if s3_ok else "error",
        "s3_detail": s3_detail,
    }
