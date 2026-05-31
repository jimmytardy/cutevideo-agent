from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.core.config import settings
from agent.core.queue import queue
from api.routes import (
    agents,
    analytics,
    channel_onboarding,
    channels,
    config,
    content_planning,
    distribution,
    engagement,
    media,
    media_serve,
    projects,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(
    title="CuteVideo Agent API",
    description="Pipeline IA multi-agents de génération de vidéos éducatives",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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


@app.on_event("startup")
async def startup() -> None:
    await queue.connect()
    logging.getLogger(__name__).info("API démarrée — Redis connecté")


@app.on_event("shutdown")
async def shutdown() -> None:
    await queue.disconnect()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
