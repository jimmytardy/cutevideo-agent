from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

logger = logging.getLogger(__name__)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import timezone

from agent.core.concurrency import can_start_pipeline
from agent.core.database import Channel, Project, Publication, Video, get_db
from agent.core.orchestrator import Orchestrator
from api.models import ProjectCreate, ProjectResponse, PublishRequest, VideoResponse

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def _project_response(project: Project, channel_name: str | None = None) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        channel_id=project.channel_id,
        channel_name=channel_name,
        theme=project.theme,
        title=project.title,
        target_duration_seconds=project.target_duration_seconds,
        status=project.status,
        error_message=project.error_message,
        config=project.config,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    channel_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectResponse]:
    query = (
        select(Project, Channel.name)
        .join(Channel, Channel.id == Project.channel_id)
        .order_by(Project.created_at.desc())
    )
    if channel_id:
        query = query.where(Project.channel_id == channel_id)

    result = await db.execute(query)
    return [_project_response(p, name) for p, name in result.all()]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, db: AsyncSession = Depends(get_db)
) -> ProjectResponse:
    channel_result = await db.execute(select(Channel).where(Channel.id == body.channel_id))
    channel = channel_result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chaîne introuvable")
    if not channel.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chaîne inactive")

    project = Project(
        channel_id=body.channel_id,
        theme=body.theme,
        target_duration_seconds=body.target_duration_seconds,
        config=body.config,
        status="pending",
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return _project_response(project, channel.name)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ProjectResponse:
    result = await db.execute(
        select(Project, Channel.name)
        .join(Channel, Channel.id == Project.channel_id)
        .where(Project.id == project_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")
    project, channel_name = row
    return _project_response(project, channel_name)


@router.post("/{project_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_pipeline(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")
    if project.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pipeline déjà en cours")

    if not await can_start_pipeline(project.channel_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slot pipeline occupé pour cette chaîne (1 max en parallèle)",
        )

    task = asyncio.create_task(
        Orchestrator().run_pipeline(project_id),
        name=f"pipeline-{project_id}",
    )
    task.add_done_callback(
        lambda t: logger.error("Pipeline %s échoué : %s", project_id, t.exception())
        if not t.cancelled() and t.exception()
        else None
    )
    return {"message": "Pipeline lancé", "project_id": str(project_id)}


@router.get("/{project_id}/videos", response_model=list[VideoResponse])
async def list_project_videos(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[VideoResponse]:
    result = await db.execute(
        select(Video).where(Video.project_id == project_id).order_by(Video.created_at.desc())
    )
    return [VideoResponse.model_validate(v) for v in result.scalars().all()]


@router.post("/{project_id}/publish", status_code=status.HTTP_202_ACCEPTED)
async def publish_project(
    project_id: uuid.UUID, body: PublishRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")

    video_result = await db.execute(
        select(Video)
        .where(Video.project_id == project_id, Video.status == "approved")
        .order_by(Video.created_at.desc())
        .limit(1)
    )
    video = video_result.scalar_one_or_none()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune vidéo approuvée pour ce projet",
        )

    pub = Publication(
        video_id=video.id,
        channel_id=project.channel_id,
        platform=body.platform,
        status="scheduled",
        scheduled_at=__import__("datetime").datetime.now(timezone.utc),
    )
    db.add(pub)
    await db.commit()
    return {"message": f"Publication {body.platform} créée", "publication_id": str(pub.id)}


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")
    await db.delete(project)
    await db.commit()
