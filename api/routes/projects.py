from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse

logger = logging.getLogger(__name__)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone

from agent.core.database import AgentRun, AudioFile, Channel, CriticReport, MediaAsset, MontagePlan, Project, Publication, Scenario, User, Video, get_db
from agent.core.subscription import QuotaExceededError, check_can_create_project
from agent.skills.media.progress import compute_media_progress
from agent.skills.pipeline_progress import AgentProgressData, compute_pipeline_progress
from agent.core.pipeline_launcher import dequeue_pipeline, enqueue_pipeline, request_pipeline_cancel
from agent.core.pipeline_queue import PipelineAlreadyQueuedError, get_queue_status, is_queued, remove_from_queue
from agent.core.pipeline_restart import critic_rework_iteration
from agent.core.pipeline_reset import PIPELINE_STEPS, RUN_FROM_STEPS, cleanup_from_step, delete_project_completely
from api.authorization import channel_owner_clause, get_user_channel, get_user_project
from api.deps import get_current_user
from api.models import (
    AudioFileResponse,
    CriticReportResponse,
    FinalPreviewResponse,
    MediaAssetResponse,
    MediaProgressResponse,
    MediaValidationBriefResponse,
    MontagePlanResponse,
    AgentProgressItem,
    PipelinePlanResponse,
    PipelineProgressResponse,
    PipelineQueueStatusResponse,
    SegmentMontagePlanResponse,
    ProjectConfigUpdate,
    ProjectCreate,
    ProjectResponse,
    PublishRequest,
    OutlineResponse,
    ProjectMetadataResponse,
    ResearchBriefResponse,
    ScenarioResponse,
    ThumbnailCandidateResponse,
    VideoResponse,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


async def _owned_project(db: AsyncSession, project_id: uuid.UUID, user: User) -> Project:
    return await get_user_project(db, project_id, user)


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
) -> dict:
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
        status = await get_queue_status(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PipelineQueueStatusResponse(
        position=status.position,
        queue_length=status.queue_length,
        priority=status.priority,
        queued_at=status.queued_at,
        blocked_reason=status.blocked_reason,
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


@router.get("/{project_id}/videos", response_model=list[VideoResponse])
async def list_project_videos(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[VideoResponse]:
    result = await db.execute(
        select(Video).where(Video.project_id == project_id).order_by(Video.created_at.desc())
    )
    return [VideoResponse.model_validate(v) for v in result.scalars().all()]


@router.get("/{project_id}/videos/{video_id}/stream", response_model=None)
async def stream_video(
    project_id: uuid.UUID,
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse | RedirectResponse:
    await get_user_project(db, project_id, current_user)
    result = await db.execute(
        select(Video).where(Video.id == video_id, Video.project_id == project_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vidéo introuvable")

    if video.local_path:
        local = Path(video.local_path)
        if local.exists():
            return FileResponse(str(local), media_type="video/mp4")

    if video.storage_key:
        from agent.core.storage import generate_presigned_url
        url = await generate_presigned_url(video.storage_key)
        return RedirectResponse(url)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier vidéo introuvable (ni local ni S3)")


@router.get("/{project_id}/final-preview", response_model=FinalPreviewResponse)
async def get_final_preview(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> FinalPreviewResponse:
    from agent.core.final_preview import (
        build_duration_warnings,
        resolve_preview_video,
        subtitles_available_for_video,
    )
    from agent.core.channel_config import resolve_channel_config

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")

    video = await resolve_preview_video(db, project_id)
    if video is None:
        return FinalPreviewResponse(
            video=None,
            stream_url=None,
            subtitles_available=False,
            subtitles_download_url=None,
            duration_warnings=[],
        )

    channel_result = await db.execute(select(Channel).where(Channel.id == project.channel_id))
    channel = channel_result.scalar_one_or_none()
    duration_warnings: list[str] = []
    if channel is not None:
        channel_config = resolve_channel_config(channel)
        duration_warnings = build_duration_warnings(
            video,
            min_duration_tiktok=channel_config.min_duration_tiktok,
        )

    stream_url = f"/api/v1/projects/{project_id}/videos/{video.id}/stream"
    subs_available = subtitles_available_for_video(video, project_id)
    subs_url = f"/api/v1/projects/{project_id}/subtitles/download" if subs_available else None
    subs_note = (
        "Sous-titres au format .srt (non incrustés dans la vidéo longue). "
        "À associer à la vidéo lors de la publication YouTube."
        if subs_available and video.video_type == "long"
        else None
    )

    return FinalPreviewResponse(
        video=VideoResponse.model_validate(video),
        stream_url=stream_url,
        subtitles_available=subs_available,
        subtitles_download_url=subs_url,
        subtitles_note=subs_note,
        duration_warnings=duration_warnings,
    )


@router.get("/{project_id}/subtitles/download", response_model=None)
async def download_project_subtitles(
    project_id: uuid.UUID,
    video_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    from agent.core.subtitle_paths import resolve_project_srt_path

    project = await get_user_project(db, project_id, current_user)

    if video_id is not None:
        video_result = await db.execute(
            select(Video).where(Video.id == video_id, Video.project_id == project_id)
        )
        if video_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vidéo introuvable")

    srt_path = resolve_project_srt_path(project_id, video_id=video_id)
    if srt_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier sous-titres introuvable")

    slug = (project.title or project.theme or str(project_id)).strip()
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in slug)[:80].strip()
    filename = f"{safe_name or project_id}_subtitles.srt"

    return FileResponse(
        str(srt_path),
        media_type="application/x-subrip",
        filename=filename,
    )


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


@router.get("/{project_id}/critic-reports", response_model=list[CriticReportResponse])
async def list_critic_reports(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[CriticReportResponse]:
    result = await db.execute(
        select(CriticReport)
        .join(Video, Video.id == CriticReport.video_id)
        .where(Video.project_id == project_id)
        .order_by(CriticReport.created_at.asc())
    )
    return [CriticReportResponse.model_validate(r) for r in result.scalars().all()]


@router.post("/{project_id}/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_pipeline(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = await _owned_project(db, project_id, current_user)
    if project.status == "queued" or await is_queued(project_id):
        removed = await dequeue_pipeline(project_id)
        if not removed:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Projet absent de la file")
        return {"message": "Projet retiré de la file d'attente", "project_id": str(project_id)}

    if project.status != "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pipeline non actif")

    await request_pipeline_cancel(project_id)

    project.status = "stopped"
    project.error_message = "Arrêté manuellement"
    await db.commit()
    return {"message": "Pipeline arrêté", "project_id": str(project_id)}


@router.post("/{project_id}/restart", status_code=status.HTTP_202_ACCEPTED)
async def restart_pipeline(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")
    await _ensure_enqueue_allowed(project)

    try:
        queue_status = await enqueue_pipeline(project_id)
    except PipelineAlreadyQueuedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _queue_enqueue_response(project_id, queue_status)


@router.post("/{project_id}/restart-from-critic/{report_id}", status_code=status.HTTP_202_ACCEPTED)
async def restart_from_critic_iteration(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Relance le pipeline en injectant les corrections d'un rapport critique spécifique."""
    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")

    await _ensure_enqueue_allowed(project)

    report_result = await db.execute(
        select(CriticReport)
        .join(Video, Video.id == CriticReport.video_id)
        .where(CriticReport.id == report_id, Video.project_id == project_id)
    )
    report = report_result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rapport critique introuvable pour ce projet")

    critic_feedback = report.requested_changes or []
    critic_start_from: str = (report.feedback or {}).get("start_from") or "media_agent"
    resume_iteration = critic_rework_iteration(report.iteration)

    try:
        queue_status = await enqueue_pipeline(
            project_id,
            critic_feedback=critic_feedback,
            critic_start_from=critic_start_from,
            resume_iteration=resume_iteration,
        )
    except PipelineAlreadyQueuedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {
        **_queue_enqueue_response(project_id, queue_status),
        "report_id": str(report_id),
        "critic_start_from": critic_start_from,
    }


@router.post("/{project_id}/run-from/{step}", status_code=status.HTTP_202_ACCEPTED)
async def run_from_step(
    project_id: uuid.UUID, step: str, db: AsyncSession = Depends(get_db)
) -> dict:
    if step not in RUN_FROM_STEPS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Étape inconnue : {step!r}. Valeurs : {sorted(RUN_FROM_STEPS)}",
        )

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")

    if project.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pipeline déjà en cours")

    await _ensure_enqueue_allowed(project)

    # Cancel any running pipeline in the worker before re-launching
    await request_pipeline_cancel(project_id)

    critic_feedback: list | None = None
    critic_start_from: str | None = None
    resume_iteration: int | None = None
    cleanup_step = step
    enqueue_start_from: str | None = step

    if step == "revision_agent":
        report_result = await db.execute(
            select(CriticReport)
            .join(Video, Video.id == CriticReport.video_id)
            .where(Video.project_id == project_id)
            .order_by(CriticReport.created_at.desc())
            .limit(1)
        )
        report = report_result.scalar_one_or_none()
        if not report:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Aucun rapport critique — impossible de reprendre l'agent révision",
            )
        critic_feedback = report.requested_changes or []
        critic_start_from = (report.feedback or {}).get("start_from") or "media_agent"
        resume_iteration = critic_rework_iteration(report.iteration)
        cleanup_step = "media_agent"
        enqueue_start_from = None

    # Clean artifacts from this step onwards
    await cleanup_from_step(project_id, cleanup_step, db)

    try:
        queue_status = await enqueue_pipeline(
            project_id,
            start_from=enqueue_start_from,
            critic_feedback=critic_feedback,
            critic_start_from=critic_start_from,
            resume_iteration=resume_iteration,
        )
    except PipelineAlreadyQueuedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {
        **_queue_enqueue_response(project_id, queue_status),
        "step": step,
    }


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
    at_agent: str | None = Query(default=None),
    iteration: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> ScenarioResponse | None:
    from agent.core.scenario_snapshot import resolve_scenario_id_for_agent_run

    resolved_id = scenario_id
    if resolved_id is None and at_agent:
        run_query = (
            select(AgentRun)
            .where(
                AgentRun.project_id == project_id,
                AgentRun.agent_name == at_agent,
                AgentRun.status == "success",
            )
        )
        if iteration is not None:
            run_query = run_query.where(AgentRun.iteration == iteration)
        run_result = await db.execute(
            run_query.order_by(AgentRun.ended_at.desc()).limit(1)
        )
        run = run_result.scalar_one_or_none()
        resolved_id = await resolve_scenario_id_for_agent_run(run, project_id, db)

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


@router.get("/{project_id}/research", response_model=ResearchBriefResponse | None)
async def get_project_research(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ResearchBriefResponse | None:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    brief = (project.config or {}).get("research_brief")
    if not brief or not isinstance(brief, dict):
        return None
    return ResearchBriefResponse.model_validate(brief)


@router.get("/{project_id}/outline", response_model=OutlineResponse | None)
async def get_project_outline(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> OutlineResponse | None:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    outline = (project.config or {}).get("scenario_outline")
    if not outline or not isinstance(outline, dict) or not outline.get("segments"):
        return None
    return OutlineResponse.model_validate(outline)


@router.get("/{project_id}/metadata", response_model=ProjectMetadataResponse | None)
async def get_project_metadata(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ProjectMetadataResponse | None:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    metadata = (project.config or {}).get("youtube_metadata")
    if not metadata or not isinstance(metadata, dict):
        return None
    return ProjectMetadataResponse.model_validate(metadata)


@router.get("/{project_id}/thumbnails", response_model=list[ThumbnailCandidateResponse])
async def get_project_thumbnails(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[ThumbnailCandidateResponse]:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    raw = (project.config or {}).get("thumbnail_candidates")
    if not isinstance(raw, list):
        return []
    return [ThumbnailCandidateResponse.model_validate(item) for item in raw if isinstance(item, dict)]


def _brief_to_response(
    brief: "MediaValidationBrief",
    *,
    source: str = "resolved",
    scenario_segments: list | None = None,
) -> MediaValidationBriefResponse:
    from agent.core.beat_validation import resolve_beats_for_response
    from agent.core.media_validation import MediaValidationBrief
    from api.models import BeatValidationResolved

    segments_out = {
        str(k): v.model_dump() for k, v in brief.segments.items()
    }
    resolved_raw = resolve_beats_for_response(brief, scenario_segments)
    resolved_beats = [BeatValidationResolved.model_validate(item) for item in resolved_raw]
    return MediaValidationBriefResponse(
        subject_entity=brief.subject_entity,
        subject_type=brief.subject_type,
        must_include=brief.must_include,
        must_exclude=brief.must_exclude,
        ambiguity_warnings=brief.ambiguity_warnings,
        validation_prompt=brief.validation_prompt,
        min_relevance_score=brief.min_relevance_score,
        niche_risk=brief.niche_risk,
        segments=segments_out,
        resolved_beats=resolved_beats,
        source=source,
    )


@router.get("/{project_id}/media-validation", response_model=MediaValidationBriefResponse)
async def get_project_media_validation(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> MediaValidationBriefResponse:
    from agent.core.media_validation import resolve_validation_brief

    result = await db.execute(
        select(Project, Channel)
        .join(Channel, Channel.id == Project.channel_id)
        .where(Project.id == project_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")
    project, channel = row

    scenario_result = await db.execute(
        select(Scenario)
        .where(Scenario.project_id == project_id)
        .order_by(Scenario.created_at.desc())
        .limit(1)
    )
    scenario = scenario_result.scalar_one_or_none()
    segments = scenario.segments if scenario else []

    brief = resolve_validation_brief(
        channel_config=channel.config or {},
        project_config=project.config or {},
        scenario_segments=segments or [],
        theme_category=channel.theme_category,
    )
    return _brief_to_response(
        brief,
        scenario_segments=segments or [],
    )


@router.get("/{project_id}/media-progress", response_model=MediaProgressResponse)
async def get_project_media_progress(
    project_id: uuid.UUID,
    iteration: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> MediaProgressResponse:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")
    try:
        progress = await compute_media_progress(db, project_id, iteration=iteration)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return MediaProgressResponse(
        iteration=progress.iteration,
        found=progress.found,
        total=progress.total,
        percent=progress.percent,
        segments_done=progress.segments_done,
        segments_total=progress.segments_total,
        agent_status=progress.agent_status,
    )


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
) -> PipelineProgressResponse:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")
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


@router.get("/{project_id}/pipeline-plan", response_model=PipelinePlanResponse)
async def get_project_pipeline_plan(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PipelinePlanResponse:
    from agent.core.channel_config import resolve_channel_config
    from agent.core.pipeline_plan import plan_pipeline
    from agent.core.subscription import (
        get_user_subscription_limits,
        resolve_effective_max_critic_iterations,
    )

    project = await get_user_project(db, project_id, current_user)
    channel = await get_user_channel(db, project.channel_id, current_user)

    limits = await get_user_subscription_limits(db, current_user.id)
    channel_config = resolve_channel_config(channel, subscription_limits=limits)

    config = project.config or {}
    effective_max = resolve_effective_max_critic_iterations(
        project_config=config,
        channel_max=channel_config.max_critic_iterations,
        limits=limits,
    )
    plan = plan_pipeline(
        channel_config,
        project_format=config.get("format"),
        target_duration_seconds=project.target_duration_seconds,
        effective_max=effective_max,
    )
    return PipelinePlanResponse(**plan)


@router.get("/{project_id}/media-assets", response_model=list[MediaAssetResponse])
async def list_project_media_assets(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[MediaAssetResponse]:
    result = await db.execute(
        select(MediaAsset)
        .where(MediaAsset.project_id == project_id)
        .order_by(MediaAsset.segment_order, MediaAsset.beat_index, MediaAsset.created_at)
    )
    return [MediaAssetResponse.model_validate(a) for a in result.scalars().all()]


_MEDIA_TYPE_BY_EXT: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def _media_type_for_path(path: Path) -> str:
    return _MEDIA_TYPE_BY_EXT.get(path.suffix.lower(), "application/octet-stream")


@router.get("/{project_id}/media-assets/{asset_id}/stream", response_model=None)
async def stream_media_asset(
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse | RedirectResponse:
    await get_user_project(db, project_id, current_user)
    result = await db.execute(
        select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.project_id == project_id,
        )
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Média introuvable")

    if asset.local_path:
        local = Path(asset.local_path)
        if local.exists():
            return FileResponse(str(local), media_type=_media_type_for_path(local))

    if asset.source_url and asset.source_url.startswith("http"):
        return RedirectResponse(asset.source_url)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier média introuvable")


@router.get("/{project_id}/media-assets/{asset_id}/preview", response_model=None)
async def preview_media_asset_with_labels(
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Preview image avec diagram_labels superposés (ffmpeg drawtext)."""
    from agent.core.api_keys import fetch_api_key
    from agent.core.channel_config import resolve_channel_config
    from agent.core.subscription import get_user_subscription_limits
    from agent.skills.video.media_asset_preview import (
        find_beat_labels,
        preview_cache_path,
        render_media_asset_label_preview,
    )

    project = await get_user_project(db, project_id, current_user)
    result = await db.execute(
        select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.project_id == project_id,
        )
    )
    asset = result.scalar_one_or_none()
    if not asset or not asset.local_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Média introuvable")

    local = Path(asset.local_path)
    if not local.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier média introuvable")

    scenario_result = await db.execute(
        select(Scenario)
        .where(Scenario.project_id == project_id)
        .order_by(Scenario.created_at.desc())
        .limit(1)
    )
    scenario = scenario_result.scalar_one_or_none()
    labels, narration, visual_type = find_beat_labels(
        scenario.segments if scenario else None,
        segment_order=int(asset.segment_order or 0),
        beat_index=int(asset.beat_index or 0),
    )
    if not labels:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Aucun diagram_label pour cet asset",
        )

    channel_result = await db.execute(select(Channel).where(Channel.id == project.channel_id))
    channel = channel_result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chaîne introuvable")

    limits = await get_user_subscription_limits(db, current_user.id)
    channel_cfg = resolve_channel_config(channel, subscription_limits=limits)
    gemini_ctx = await fetch_api_key(
        current_user.id, "gemini", purpose="diagram_layout", tier="free"
    )

    out_path = preview_cache_path(project_id, asset_id)
    try:
        await render_media_asset_label_preview(
            local,
            out_path,
            labels=labels,
            narration_excerpt=narration,
            language=channel_cfg.content_language,
            visual_type=visual_type or (asset.visual_type or ""),
            gemini_api_key=gemini_ctx.key,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("Preview labels asset %s : %s", asset_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Échec génération preview avec labels",
        ) from exc

    return FileResponse(str(out_path), media_type=_media_type_for_path(out_path))


@router.get("/{project_id}/audio", response_model=list[AudioFileResponse])
async def list_project_audio_files(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[AudioFileResponse]:
    result = await db.execute(
        select(AudioFile)
        .where(AudioFile.project_id == project_id)
        .order_by(AudioFile.segment_order)
    )
    return [AudioFileResponse.model_validate(a) for a in result.scalars().all()]


def _montage_plan_response(row: MontagePlan) -> MontagePlanResponse:
    plan_data = row.plan_data if isinstance(row.plan_data, dict) else {}
    segments_raw = plan_data.get("segments") or []
    segments = [SegmentMontagePlanResponse.model_validate(seg) for seg in segments_raw]
    return MontagePlanResponse(
        id=row.id,
        project_id=row.project_id,
        iteration=row.iteration,
        segments=segments,
        planner_notes=str(plan_data.get("planner_notes") or ""),
        created_at=row.created_at,
    )


@router.get("/{project_id}/montage-plan", response_model=MontagePlanResponse | None)
async def get_project_montage_plan(
    project_id: uuid.UUID,
    iteration: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> MontagePlanResponse | None:
    query = select(MontagePlan).where(MontagePlan.project_id == project_id)
    if iteration is not None:
        query = query.where(MontagePlan.iteration == iteration)
    result = await db.execute(
        query.order_by(MontagePlan.iteration.desc(), MontagePlan.created_at.desc()).limit(1)
    )
    row = result.scalar_one_or_none()
    return _montage_plan_response(row) if row else None


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    project = await _owned_project(db, project_id, current_user)
    if project.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Impossible de supprimer un projet en cours d'exécution")
    # Retirer le projet de la file Redis avant suppression, sinon son entrée
    # ZSET + payload deviennent orphelins et bloquent la tête de file.
    await remove_from_queue(project_id)
    await delete_project_completely(project_id, db)
    await db.delete(project)
    await db.commit()
