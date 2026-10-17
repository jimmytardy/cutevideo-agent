from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

logger = logging.getLogger(__name__)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, UTC

from agent.core.database import Channel, CriticReport, Project, Publication, Scenario, User, Video, get_db
from agent.core.subscription import QuotaExceededError, check_can_create_project
from agent.skills.pipeline_progress import AgentProgressData, compute_pipeline_progress
from agent.core.pipeline_launcher import dequeue_pipeline, enqueue_pipeline, request_pipeline_cancel
from agent.core.pipeline_queue import PipelineAlreadyQueuedError, get_queue_status, is_queued, remove_from_queue
from agent.core.pipeline_reset import delete_project_completely
from agent.scheduler.cleanup import ACTIVE_PROJECT_STATUSES, purge_project_files
from api.authorization import channel_owner_clause, get_user_channel, get_user_project
from api.deps import get_current_user
from api.models import (
    CriticReportResponse,
    AgentProgressItem,
    PipelineProgressResponse,
    PipelineQueueStatusResponse,
    ProjectConfigUpdate,
    ProjectCostResponse,
    ProjectCreate,
    ProjectResponse,
    PublishRequest,
    ProjectMetadataResponse,
    ScenarioResponse,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def _project_response(project: Project, channel_name: str | None = None) -> ProjectResponse:
    config = project.config or {}
    queued_at_raw = config.get("queued_at")
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
        queued_at=datetime.fromisoformat(queued_at_raw) if queued_at_raw else None,
    )


async def _project_response_with_queue(
    project: Project,
    channel_name: str | None = None,
) -> ProjectResponse:
    response = _project_response(project, channel_name)
    if project.status == "queued":
        try:
            status = await get_queue_status(project.id)
            response.queue_position = status.position
            response.queue_length = status.queue_length
            response.queued_at = status.queued_at
        except ValueError:
            pass
    return response


def _queue_enqueue_response(project_id: uuid.UUID, status: object) -> dict:
    return {
        "message": "Pipeline ajouté à la file d'attente",
        "project_id": str(project_id),
        "queue_position": status.position,
        "queue_length": status.queue_length,
        "priority": status.priority,
    }


async def _ensure_enqueue_allowed(project: Project) -> None:
    if project.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pipeline déjà en cours")
    if project.status == "queued" or await is_queued(project.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Projet déjà en file d'attente",
        )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    channel_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProjectResponse]:
    query = (
        select(Project, Channel.name)
        .join(Channel, Channel.id == Project.channel_id)
        .where(channel_owner_clause(current_user))
        .order_by(Project.created_at.desc())
        .limit(limit)
    )
    if channel_id:
        query = query.where(Project.channel_id == channel_id)
    if status:
        query = query.where(Project.status == status)

    result = await db.execute(query)
    return [_project_response(p, name) for p, name in result.all()]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    try:
        await check_can_create_project(db, current_user)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    channel = await get_user_channel(db, body.channel_id, current_user)
    if not channel.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chaîne inactive")

    project_config = dict(body.config or {})
    if (
        body.target_duration_seconds <= 120
        and project_config.get("format") not in ("short_standalone", "short", "long")
    ):
        project_config["format"] = "short_standalone"

    project = Project(
        channel_id=body.channel_id,
        theme=body.theme,
        target_duration_seconds=body.target_duration_seconds,
        config=project_config or None,
        status="pending",
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return _project_response(project, channel.name)


@router.get("/check-similarity")
async def check_topic_similarity(
    channel_id: uuid.UUID = Query(...),
    theme: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await get_user_channel(db, channel_id, current_user)
    from agent.scheduler.content_planning import load_topic_history
    from agent.skills.content_planning.heuristic_planner import find_similar_in_history
    history = await load_topic_history(channel_id)
    similar = find_similar_in_history(theme, history)
    return {"is_duplicate": len(similar) > 0, "similar_topics": similar}


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    project = await get_user_project(db, project_id, current_user)
    channel_result = await db.execute(select(Channel.name).where(Channel.id == project.channel_id))
    channel_name = channel_result.scalar_one_or_none()
    return await _project_response_with_queue(project, channel_name)


@router.get("/{project_id}/queue-status", response_model=PipelineQueueStatusResponse)
async def get_project_queue_status(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PipelineQueueStatusResponse:
    await get_user_project(db, project_id, current_user)
    try:
        queue_status = await get_queue_status(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PipelineQueueStatusResponse(
        position=queue_status.position,
        queue_length=queue_status.queue_length,
        priority=queue_status.priority,
        queued_at=queue_status.queued_at,
        blocked_reason=queue_status.blocked_reason,
    )


@router.delete("/{project_id}/queue", status_code=status.HTTP_200_OK)
async def remove_project_from_queue(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = await get_user_project(db, project_id, current_user)
    if project.status != "queued" and not await is_queued(project_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Le projet n'est pas en file d'attente",
        )
    removed = await dequeue_pipeline(project_id)
    if not removed:
        await db.refresh(project)
        if project.status == "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Le pipeline vient de démarrer — utilisez Arrêter",
            )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Projet absent de la file")
    return {"message": "Projet retiré de la file d'attente", "project_id": str(project_id)}

@router.post("/{project_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_pipeline(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = await get_user_project(db, project_id, current_user)
    await _ensure_enqueue_allowed(project)

    try:
        queue_status = await enqueue_pipeline(project_id, user_id=current_user.id)
    except PipelineAlreadyQueuedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _queue_enqueue_response(project_id, queue_status)


@router.post("/{project_id}/publish", status_code=status.HTTP_202_ACCEPTED)
async def publish_project(
    project_id: uuid.UUID,
    body: PublishRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = await get_user_project(db, project_id, current_user)
    if project.status != "approved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Le projet n'est pas approuvé")

    # Studio exporte un Video `short_<plateforme>` par plateforme activée.
    video_result = await db.execute(
        select(Video)
        .where(
            Video.project_id == project_id,
            Video.video_type == f"short_{body.platform}",
            Video.file_purged_at.is_(None),
        )
        .order_by(Video.created_at.desc())
        .limit(1)
    )
    video = video_result.scalar_one_or_none()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Aucune vidéo {body.platform} pour ce projet",
        )
    already = await db.execute(
        select(Publication.id).where(
            Publication.video_id == video.id,
            Publication.platform == body.platform,
            Publication.status.in_(("scheduled", "publishing", "published")),
        )
    )
    if already.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Publication {body.platform} déjà planifiée ou publiée",
        )

    pub = Publication(
        video_id=video.id,
        channel_id=project.channel_id,
        platform=body.platform,
        status="scheduled",
        scheduled_at=datetime.now(UTC),
    )
    db.add(pub)
    await db.commit()
    return {"message": f"Publication {body.platform} créée", "publication_id": str(pub.id)}


@router.get("/{project_id}/critic-reports", response_model=list[CriticReportResponse])
async def list_critic_reports(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CriticReportResponse]:
    await get_user_project(db, project_id, current_user)
    result = await db.execute(
        select(CriticReport)
        .join(Video, Video.id == CriticReport.video_id)
        .where(Video.project_id == project_id)
        .order_by(CriticReport.created_at.asc())
    )
    return [CriticReportResponse.model_validate(r) for r in result.scalars().all()]


@router.get("/{project_id}/cost", response_model=ProjectCostResponse)
async def get_project_cost(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectCostResponse:
    from agent.core.channel_config import resolve_channel_config
    from agent.core.project_cost import project_cost_breakdown
    from agent.core.subscription import get_user_subscription_limits, resolve_effective_max_critic_iterations

    project = await get_user_project(db, project_id, current_user)
    channel = await get_user_channel(db, project.channel_id, current_user)
    limits = await get_user_subscription_limits(db, current_user.id)
    cfg = resolve_channel_config(channel, subscription_limits=limits)
    max_iterations = resolve_effective_max_critic_iterations(
        project_config=project.config or {},
        channel_max=cfg.max_critic_iterations,
        limits=limits,
    ) or cfg.max_critic_iterations
    breakdown = await project_cost_breakdown(
        project_id,
        cap_usd=cfg.cost_max_per_video_usd,
        max_iterations=max_iterations,
    )
    return ProjectCostResponse(
        project_id=breakdown.project_id,
        total_usd=breakdown.total_usd,
        cap_usd=breakdown.cap_usd,
        iterations_used=breakdown.iterations_used,
        max_iterations=breakdown.max_iterations,
        stop_reason=breakdown.stop_reason,
        by_agent=[row.model_dump() for row in breakdown.by_agent],
        by_iteration=[row.model_dump() for row in breakdown.by_iteration],
        elapsed_s=breakdown.elapsed_s,
    )


@router.post("/{project_id}/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_pipeline(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = await get_user_project(db, project_id, current_user)
    if project.status == "queued" or await is_queued(project_id):
        removed = await dequeue_pipeline(project_id)
        if not removed:
            await db.refresh(project)
            if project.status == "running":
                await request_pipeline_cancel(project_id)
                project.status = "stopped"
                project.error_message = "Arrêté manuellement"
                await db.commit()
                return {"message": "Pipeline arrêté", "project_id": str(project_id)}
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Projet absent de la file")
        return {"message": "Projet retiré de la file d'attente", "project_id": str(project_id)}

    if project.status == "paused":
        # En pause (limite d'usage Claude) : rien ne tourne, on annule seulement la reprise prévue.
        project.status = "stopped"
        project.error_message = "Arrêté manuellement"
        await db.commit()
        return {"message": "Pipeline arrêté", "project_id": str(project_id)}
    if project.status != "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pipeline non actif")

    await request_pipeline_cancel(project_id)

    project.status = "stopped"
    project.error_message = "Arrêté manuellement"
    await db.commit()
    return {"message": "Pipeline arrêté", "project_id": str(project_id)}


@router.post("/{project_id}/restart", status_code=status.HTTP_202_ACCEPTED)
async def restart_pipeline(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = await get_user_project(db, project_id, current_user)
    await _ensure_enqueue_allowed(project)
    # Les fichiers de la création précédente partent dès le clic (le run les efface aussi au démarrage).
    await purge_project_files(project_id)

    try:
        queue_status = await enqueue_pipeline(project_id)
    except PipelineAlreadyQueuedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _queue_enqueue_response(project_id, queue_status)


@router.delete("/{project_id}/files")
async def delete_project_files(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Supprime les fichiers du projet (travail + vidéos non publiées) ; les publiées sont gardées."""
    project = await get_user_project(db, project_id, current_user)
    if project.status in ACTIVE_PROJECT_STATUSES or await is_queued(project_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Impossible de supprimer les fichiers d'un projet en cours ou en file d'attente",
        )
    report = await purge_project_files(project_id)
    return report.to_dict()


@router.patch("/{project_id}/config", response_model=ProjectResponse)
async def update_project_config(
    project_id: uuid.UUID,
    body: ProjectConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    from agent.core.subscription import get_user_subscription_limits

    project = await get_user_project(db, project_id, current_user)
    result = await db.execute(
        select(Channel.name).where(Channel.id == project.channel_id)
    )
    channel_name = result.scalar_one()
    limits = await get_user_subscription_limits(db, current_user.id)
    config = dict(project.config or {})
    if "max_critic_iterations" in body.model_fields_set:
        if body.max_critic_iterations is None:
            if not limits.unlimited_critic_iterations:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Seuls les comptes admin peuvent retirer le plafond d'itérations",
                )
            config.pop("max_critic_iterations", None)
        else:
            if body.max_critic_iterations < 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="max_critic_iterations doit être ≥ 1",
                )
            capped = body.max_critic_iterations
            if not limits.unlimited_critic_iterations:
                capped = min(capped, limits.max_critic_iterations)
            config["max_critic_iterations"] = capped
    project.config = config
    await db.commit()
    await db.refresh(project)
    return _project_response(project, channel_name)


@router.get("/{project_id}/scenario", response_model=ScenarioResponse | None)
async def get_project_scenario(
    project_id: uuid.UUID,
    scenario_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScenarioResponse | None:
    await get_user_project(db, project_id, current_user)
    resolved_id = scenario_id
    if resolved_id is not None:
        row = await db.get(Scenario, resolved_id)
        if row is None or row.project_id != project_id:
            return None
        return ScenarioResponse.model_validate(row)

    result = await db.execute(
        select(Scenario)
        .where(Scenario.project_id == project_id)
        .order_by(Scenario.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return ScenarioResponse.model_validate(row) if row else None


@router.get("/{project_id}/metadata", response_model=ProjectMetadataResponse | None)
async def get_project_metadata(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectMetadataResponse | None:
    project = await get_user_project(db, project_id, current_user)
    metadata = (project.config or {}).get("youtube_metadata")
    if not metadata or not isinstance(metadata, dict):
        return None
    return ProjectMetadataResponse.model_validate(metadata)


def _progress_item(data: AgentProgressData) -> AgentProgressItem:
    return AgentProgressItem(
        done=data.done,
        total=data.total,
        percent=data.percent,
        detail=data.detail,
        segments_done=data.segments_done,
        segments_total=data.segments_total,
    )


@router.get("/{project_id}/pipeline-progress", response_model=PipelineProgressResponse)
async def get_project_pipeline_progress(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PipelineProgressResponse:
    await get_user_project(db, project_id, current_user)
    try:
        snapshot = await compute_pipeline_progress(db, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PipelineProgressResponse(
        preparation={
            name: _progress_item(item) for name, item in snapshot.preparation.items()
        },
        iterations={
            str(iteration): {
                name: _progress_item(item) for name, item in agents.items()
            }
            for iteration, agents in snapshot.iterations.items()
        },
        post_production={
            name: _progress_item(item) for name, item in snapshot.post_production.items()
        },
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    project = await get_user_project(db, project_id, current_user)
    if project.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Impossible de supprimer un projet en cours d'exécution")
    # Retirer le projet de la file Redis avant suppression, sinon son entrée
    # ZSET + payload deviennent orphelins et bloquent la tête de file.
    await remove_from_queue(project_id)
    await delete_project_completely(project_id, db)
    await db.delete(project)
    await db.commit()
