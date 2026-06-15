from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse

logger = logging.getLogger(__name__)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import timezone

from agent.core.concurrency import can_start_pipeline
from agent.core.database import AgentRun, AudioFile, Channel, CriticReport, MediaAsset, Project, Publication, Scenario, Video, get_db
from agent.skills.media.progress import compute_media_progress
from agent.core.pipeline_launcher import enqueue_pipeline, request_pipeline_cancel
from agent.core.pipeline_reset import PIPELINE_STEPS, cleanup_from_step, delete_project_completely
from api.models import (
    AudioFileResponse,
    CriticReportResponse,
    FinalPreviewResponse,
    MediaAssetResponse,
    MediaProgressResponse,
    MediaValidationBriefResponse,
    MediaValidationOverrideBody,
    ProjectConfigUpdate,
    ProjectCreate,
    ProjectResponse,
    PublishRequest,
    RegenerateMediaValidationResponse,
    ResearchBriefResponse,
    ScenarioResponse,
    VideoResponse,
)

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
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectResponse]:
    query = (
        select(Project, Channel.name)
        .join(Channel, Channel.id == Project.channel_id)
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

    await enqueue_pipeline(project_id)
    return {"message": "Pipeline lancé", "project_id": str(project_id)}


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
) -> FileResponse | RedirectResponse:
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
    from agent.core.final_preview import resolve_preview_video, subtitles_available_for_video

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    if project_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")

    video = await resolve_preview_video(db, project_id)
    if video is None:
        return FinalPreviewResponse(
            video=None,
            stream_url=None,
            subtitles_available=False,
            subtitles_download_url=None,
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
    )


@router.get("/{project_id}/subtitles/download", response_model=None)
async def download_project_subtitles(
    project_id: uuid.UUID,
    video_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    from agent.core.subtitle_paths import resolve_project_srt_path

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")

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
async def stop_pipeline(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")
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
    if project.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pipeline déjà en cours")

    if not await can_start_pipeline(project.channel_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slot pipeline occupé pour cette chaîne (1 max en parallèle)",
        )

    project.status = "pending"
    project.error_message = None
    await db.commit()

    await enqueue_pipeline(project_id)
    return {"message": "Pipeline relancé", "project_id": str(project_id)}


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
    if project.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pipeline déjà en cours")

    report_result = await db.execute(
        select(CriticReport)
        .join(Video, Video.id == CriticReport.video_id)
        .where(CriticReport.id == report_id, Video.project_id == project_id)
    )
    report = report_result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rapport critique introuvable pour ce projet")

    if not await can_start_pipeline(project.channel_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slot pipeline occupé pour cette chaîne (1 max en parallèle)",
        )

    critic_feedback = report.requested_changes or []
    critic_start_from: str = (report.feedback or {}).get("start_from") or "media_agent"

    project.status = "pending"
    project.error_message = None
    await db.commit()

    await enqueue_pipeline(
        project_id,
        critic_feedback=critic_feedback,
        critic_start_from=critic_start_from,
    )
    return {
        "message": f"Pipeline relancé (itération {report.iteration}, depuis {critic_start_from})",
        "project_id": str(project_id),
        "report_id": str(report_id),
        "critic_start_from": critic_start_from,
    }


@router.post("/{project_id}/run-from/{step}", status_code=status.HTTP_202_ACCEPTED)
async def run_from_step(
    project_id: uuid.UUID, step: str, db: AsyncSession = Depends(get_db)
) -> dict:
    if step not in PIPELINE_STEPS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Étape inconnue : {step!r}. Valeurs : {PIPELINE_STEPS}",
        )

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")

    # Cancel any running pipeline in the worker before re-launching
    await request_pipeline_cancel(project_id)

    if not await can_start_pipeline(project.channel_id, exclude_project_id=project_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slot pipeline occupé pour cette chaîne (1 max en parallèle)",
        )

    # Clean artifacts from this step onwards
    await cleanup_from_step(project_id, step, db)

    project.status = "pending"
    project.error_message = None
    await db.commit()

    await enqueue_pipeline(project_id, start_from=step)
    return {"message": f"Pipeline relancé depuis {step}", "project_id": str(project_id)}


@router.patch("/{project_id}/config", response_model=ProjectResponse)
async def update_project_config(
    project_id: uuid.UUID, body: ProjectConfigUpdate, db: AsyncSession = Depends(get_db)
) -> ProjectResponse:
    result = await db.execute(
        select(Project, Channel.name)
        .join(Channel, Channel.id == Project.channel_id)
        .where(Project.id == project_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")
    project, channel_name = row
    config = dict(project.config or {})
    if body.max_critic_iterations is not None:
        if body.max_critic_iterations < 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="max_critic_iterations doit être ≥ 1")
        config["max_critic_iterations"] = body.max_critic_iterations
    if body.media_validation_override is not None:
        config["media_validation_override"] = body.media_validation_override
    project.config = config
    await db.commit()
    await db.refresh(project)
    return _project_response(project, channel_name)


@router.get("/{project_id}/scenario", response_model=ScenarioResponse | None)
async def get_project_scenario(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ScenarioResponse | None:
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


def _brief_to_response(
    brief: "MediaValidationBrief",
    *,
    override: dict | None = None,
    source: str = "resolved",
) -> MediaValidationBriefResponse:
    from agent.core.media_validation import MediaValidationBrief

    segments_out = {
        str(k): v.model_dump() for k, v in brief.segments.items()
    }
    override_body = None
    if override:
        override_body = MediaValidationOverrideBody.model_validate(override)
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
        override=override_body,
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
    override = (project.config or {}).get("media_validation_override")
    return _brief_to_response(brief, override=override if isinstance(override, dict) else None)


@router.patch("/{project_id}/media-validation", response_model=MediaValidationBriefResponse)
async def update_project_media_validation(
    project_id: uuid.UUID,
    body: MediaValidationOverrideBody,
    db: AsyncSession = Depends(get_db),
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

    if project.status not in ("pending", "stopped", "failed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Override validation média possible uniquement avant exécution active du pipeline",
        )

    config = dict(project.config or {})
    config["media_validation_override"] = body.model_dump(exclude_none=True)
    project.config = config
    await db.commit()
    await db.refresh(project)

    scenario_result = await db.execute(
        select(Scenario)
        .where(Scenario.project_id == project_id)
        .order_by(Scenario.created_at.desc())
        .limit(1)
    )
    scenario = scenario_result.scalar_one_or_none()
    brief = resolve_validation_brief(
        channel_config=channel.config or {},
        project_config=project.config or {},
        scenario_segments=scenario.segments if scenario else [],
        theme_category=channel.theme_category,
    )
    return _brief_to_response(brief, override=body.model_dump(exclude_none=True), source="override")


@router.post(
    "/{project_id}/media-validation/regenerate",
    response_model=RegenerateMediaValidationResponse,
)
async def regenerate_project_media_validation(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> RegenerateMediaValidationResponse:
    from agent.core.media_validation import attach_brief_to_segments
    from agent.skills.media.validation_brief import build_validation_brief

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
    if not scenario or not scenario.segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun scénario — lancez d'abord le scenario_agent",
        )

    brief = await build_validation_brief(
        theme=project.theme,
        theme_category=channel.theme_category,
        segments=scenario.segments,
        creative_brief=channel.creative_brief or "",
    )
    config = dict(project.config or {})
    config["media_validation_brief"] = brief.to_dict()
    project.config = config
    scenario.segments = attach_brief_to_segments(scenario.segments, brief)
    await db.commit()
    await db.refresh(project)

    from agent.core.media_validation import resolve_validation_brief

    resolved = resolve_validation_brief(
        channel_config=channel.config or {},
        project_config=project.config or {},
        scenario_segments=scenario.segments,
        theme_category=channel.theme_category,
    )
    override = config.get("media_validation_override")
    return RegenerateMediaValidationResponse(
        brief=_brief_to_response(
            resolved,
            override=override if isinstance(override, dict) else None,
            source="regenerated",
        ),
        message="Brief de validation régénéré",
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
) -> FileResponse | RedirectResponse:
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


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")
    if project.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Impossible de supprimer un projet en cours d'exécution")
    await delete_project_completely(project_id, db)
    await db.delete(project)
    await db.commit()
