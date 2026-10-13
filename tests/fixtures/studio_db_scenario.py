"""Scénario applicatif complet, lancé en sous-processus par `tests/test_studio_pipeline_db.py`.

DATABASE_URL / REDIS_URL pointent sur l'infra de TEST et CLAUDE_BIN sur le faux
CLI : rien n'est patché côté Claude. Seul S3 est bouchonné (aucun envoi réel).
Affiche un JSON de constats sur la dernière ligne de stdout.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from unittest.mock import patch

S3_DELETED: list[str] = []


async def fake_persist(video, channel_slug, local_path, *, delete_local=None):
    from sqlalchemy import update

    from agent.core.database import AsyncSessionFactory, Video

    async with AsyncSessionFactory() as session:
        await session.execute(
            update(Video).where(Video.id == video.id).values(storage_key=f"test/{video.id}.mp4")
        )
        await session.commit()
    return video


async def fake_delete(key: str) -> None:
    S3_DELETED.append(key)


async def main() -> dict:
    from sqlalchemy import func, select

    from agent.core.claude_studio import OUTPUT_ROOT
    from agent.core.database import (
        AgentRun,
        AsyncSessionFactory,
        Channel,
        CriticReport,
        Project,
        Scenario,
        SubscriptionPlan,
        User,
        Video,
    )
    from agent.core.final_preview import resolve_preview_video
    from agent.core.orchestrator import Orchestrator
    from agent.core.pipeline_reset import delete_project_completely
    from agent.core.queue import queue
    from agent.skills.pipeline_progress import compute_pipeline_progress
    from studio.launcher import default_runs_dir

    await queue.connect()
    async with AsyncSessionFactory() as session:
        plan = (await session.execute(select(SubscriptionPlan).order_by(SubscriptionPlan.name))).scalars().first()
        user = User(google_sub=f"test-{uuid.uuid4()}", email=f"{uuid.uuid4()}@test.local", subscription_id=plan.id)
        session.add(user)
        await session.flush()
        channel = Channel(
            user_id=user.id, slug=f"test-{uuid.uuid4().hex[:8]}", name="Test", theme_category="animaux",
            composio_user_id="test", niche_prompt="vulgarisation animale",
            config={"publishing": {"enabled_platforms": ["youtube", "tiktok"]}},
        )
        session.add(channel)
        await session.flush()
        project = Project(channel_id=channel.id, theme="Pourquoi les flamants roses sont roses",
                          target_duration_seconds=15, status="pending")
        session.add(project)
        await session.commit()
        pid = project.id

    facts: dict = {}
    with patch("agent.core.storage.persist_video_to_storage", fake_persist), \
         patch("agent.core.pipeline_reset.delete_s3_object", fake_delete):
        await Orchestrator().run_pipeline(pid)
        # Relance : doit repartir d'un état propre, sans doublons.
        async with AsyncSessionFactory() as session:
            (await session.get(Project, pid)).status = "pending"
            await session.commit()
        await Orchestrator().run_pipeline(pid)

        async with AsyncSessionFactory() as session:
            project = await session.get(Project, pid)
            videos = (await session.execute(select(Video).where(Video.project_id == pid))).scalars().all()
            reports = (await session.execute(
                select(CriticReport).join(Video, CriticReport.video_id == Video.id)
                .where(Video.project_id == pid).order_by(CriticReport.iteration)
            )).scalars().all()
            runs = (await session.execute(select(AgentRun).where(AgentRun.project_id == pid))).scalars().all()
            progress = await compute_pipeline_progress(session, pid)
            preview = await resolve_preview_video(session, pid)
            facts.update({
                "status": project.status,
                "title": project.title,
                "video_types": sorted(v.video_type for v in videos),
                "platform_videos_stored": all(v.storage_key for v in videos if v.video_type != "short_master"),
                "master_duration": next(v.duration_s for v in videos if v.video_type == "short_master"),
                "critiques": [[r.iteration, r.global_score, r.decision] for r in reports],
                "scenarios": (await session.execute(
                    select(func.count()).select_from(Scenario).where(Scenario.project_id == pid))).scalar(),
                "runs": sorted([r.agent_name, r.status, r.iteration] for r in runs),
                "progress": {str(it): {k: v.percent for k, v in a.items()} for it, a in progress.iterations.items()},
                "metadata": project.config.get("youtube_metadata"),
                "thumbnail": project.config.get("thumbnail"),
                "studio": project.config.get("claude_studio"),
                "preview_type": preview.video_type if preview else None,
                "s3_deleted_on_restart": len(S3_DELETED),
            })
            thumb = project.config.get("thumbnail") or {}
            facts["thumbnail_exists"] = Path(str(thumb.get("local_path", ""))).is_file()

        async with AsyncSessionFactory() as session:
            await delete_project_completely(pid, session)
            await session.commit()
            facts["videos_after_delete"] = (await session.execute(
                select(func.count()).select_from(Video).where(Video.project_id == pid))).scalar()
            await session.delete(await session.get(Project, pid))
            await session.delete(await session.get(Channel, channel.id))
            await session.delete(await session.get(User, user.id))
            await session.commit()
    facts["dirs_after_delete"] = [
        (OUTPUT_ROOT / str(pid)).exists(), (default_runs_dir() / str(pid)).exists(),
    ]
    return facts


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, default=str))
