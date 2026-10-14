"""Pipeline de création « Claude Studio » : Claude Code (CLI headless) produit le Short.

L'orchestrateur Python ne fait plus que :
1. écrire `brief.json` dans un run dir à partir du `PipelineContext` ;
2. lancer `claude -p /make-video` (cf. `studio/launcher.py`) qui orchestre les
   sous-agents scénariste → voix → monteur → miniaturiste → critique ;
3. refléter la progression en DB (`AgentRun`) et Redis (statut temps réel) ;
4. persister le résultat : Scenario, Video (short_master + exports plateformes),
   CriticReport, métadonnées de publication et miniature dans `Project.config`.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import update

from agent.core.database import (
    AgentRun,
    AsyncSessionFactory,
    CriticReport,
    Project,
    Scenario,
    Video,
)
from studio.contracts import (
    Brief,
    ContractError,
    Critique,
    Scenario as StudioScenario,
    StudioResult,
    Thumbnail,
    load_contract,
    read_json,
)
from studio.launcher import ClaudeRunError, default_runs_dir, prepare_run_dir, run_claude

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

# Rôle Claude → nom d'agent historique (dashboard, AgentRun, statuts Redis).
ROLE_AGENT_NAMES = {
    "scenariste": "scenario_agent",
    "voix": "narrator_agent",
    "monteur": "editor_agent",
    "miniaturiste": "thumbnail_agent",
    "critique": "critic_agent",
}
STUDIO_AGENT_ORDER = list(ROLE_AGENT_NAMES.values())
PLATFORMS = ("youtube", "tiktok", "instagram")
OUTPUT_ROOT = Path("./output/studio")
_MAX_LOGGED_CHARS = 4000


def build_brief(ctx: "PipelineContext") -> Brief:
    cfg = ctx.channel_config
    plan = ctx.content_plan or {}
    return Brief(
        theme=ctx.theme,
        niche=ctx.niche_prompt,
        angle=str(plan.get("angle") or plan.get("hook") or ""),
        language=cfg.content_language or "fr",
        target_duration_s=max(15, min(int(ctx.target_duration_seconds or cfg.short_duration_s), 180)),
        voice=cfg.tts_short.voice or cfg.tts_voice,
        tts_engine=cfg.tts_short.engine or cfg.tts_engine,
        max_iterations=max(1, min(ctx.max_critic_iterations or cfg.quality_max_iterations, 6)),
        min_score=cfg.min_critic_score,
        editorial_tone=cfg.editorial_tone,
        creative_brief=(ctx.channel.creative_brief or "").strip(),
        content_plan=plan or None,
        animations=cfg.studio_animations,
        max_ai_images=cfg.ai_fallback.max_ai_images_per_video if cfg.ai_fallback.enabled else 0,
    )


class _ProgressRecorder:
    """Reflète les événements du stream Claude en AgentRun + statuts Redis."""

    def __init__(self, project_id: uuid.UUID) -> None:
        self.project_id = project_id
        self.pid = str(project_id)
        self.iteration = 1
        self.runs: dict[str, uuid.UUID] = {}
        self.result: dict[str, Any] | None = None

    async def __call__(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "agent_start":
            await self._start(data)
        elif kind == "agent_end":
            await self._end(data)
        elif kind == "result":
            self.result = data

    async def _start(self, data: dict[str, Any]) -> None:
        name = ROLE_AGENT_NAMES.get(data["role"])
        if not name:
            return
        async with AsyncSessionFactory() as session:
            run = AgentRun(
                project_id=self.project_id,
                agent_name=name,
                status="running",
                iteration=self.iteration,
                input_json={
                    "description": data.get("description", ""),
                    "prompt": str(data.get("prompt", ""))[:_MAX_LOGGED_CHARS],
                },
                started_at=datetime.now(timezone.utc),
                llm_model="claude-code",
            )
            session.add(run)
            await session.commit()
            self.runs[data["id"]] = run.id

    async def _end(self, data: dict[str, Any]) -> None:
        name = ROLE_AGENT_NAMES.get(data["role"])
        run_id = self.runs.pop(data["id"], None)
        if not name or run_id is None:
            return
        status = "failed" if data["is_error"] else "success"
        output = str(data.get("output", ""))[:_MAX_LOGGED_CHARS]
        async with AsyncSessionFactory() as session:
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == run_id)
                .values(
                    status=status,
                    output_json={"summary": output},
                    error=output if data["is_error"] else None,
                    ended_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
        if data["role"] == "critique" and not data["is_error"]:
            self.iteration += 1

    async def close_dangling(self, status: str, reason: str) -> None:
        """Clôt les AgentRun restés ouverts (session interrompue)."""
        if not self.runs:
            return
        async with AsyncSessionFactory() as session:
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id.in_(list(self.runs.values())))
                .values(status=status, error=reason, ended_at=datetime.now(timezone.utc))
            )
            await session.commit()
        self.runs.clear()


class ClaudeStudioRunner:
    def __init__(self, ctx: "PipelineContext") -> None:
        self.ctx = ctx
        self.run_dir = default_runs_dir() / str(ctx.project_id)
        self.output_dir = OUTPUT_ROOT / str(ctx.project_id)

    async def run(self) -> Video:
        from agent.core.pipeline_reset import clear_creation_artifacts

        brief = build_brief(self.ctx)
        # Relance complète : on repart d'un état propre (DB et run dir).
        async with AsyncSessionFactory() as session:
            await clear_creation_artifacts(self.ctx.project_id, session)
            await session.commit()
        for directory in (self.run_dir, self.output_dir):
            if directory.exists():
                shutil.rmtree(directory)
        prepare_run_dir(self.run_dir, brief)
        logger.info("Claude Studio — projet %s, run dir %s", self.ctx.project_id, self.run_dir)

        recorder = _ProgressRecorder(self.ctx.project_id)
        try:
            session_result = await run_claude(self.run_dir, on_event=recorder)
        except BaseException as exc:
            await recorder.close_dangling("stopped" if not isinstance(exc, Exception) else "failed", str(exc)[:500])
            raise
        await recorder.close_dangling("failed", "sous-agent non terminé")

        try:
            result = load_contract(self.run_dir / "result.json", StudioResult)
        except ContractError as exc:
            raise ClaudeRunError(f"Claude Studio n'a pas produit de résultat exploitable : {exc}") from exc
        if result.status == "failed" or not result.final_video:
            raise ClaudeRunError(f"Claude Studio a échoué : {result.notes or 'aucune vidéo finale'}")

        return await self._persist(result, session_result)

    # ── persistance ──────────────────────────────────────────────────────

    async def _persist(self, result: StudioResult, session_result: dict[str, Any]) -> Video:
        from studio.media import probe_media

        run_dir = self.run_dir
        scenario = load_contract(run_dir / "scenario.json", StudioScenario)
        final_src = run_dir / result.final_video
        if not final_src.exists():
            raise ClaudeRunError(f"vidéo finale introuvable : {result.final_video}")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        master_path = self.output_dir / "short_master.mp4"
        shutil.copy2(final_src, master_path)
        duration = (await probe_media(master_path))["duration_s"]
        critiques = self._load_critiques()
        credits = self._load_credits(final_src)

        async with AsyncSessionFactory() as session:
            session.add(Scenario(
                project_id=self.ctx.project_id,
                segments=[b.model_dump() for b in scenario.beats],
                total_duration_s=int(round(duration)),
                iteration=result.iterations,
            ))
            master = Video(
                project_id=self.ctx.project_id,
                video_type="short_master",
                local_path=str(master_path),
                duration_s=duration,
                iteration=result.iterations,
                status="draft",
            )
            session.add(master)
            await session.flush()
            for critique in critiques:
                session.add(CriticReport(
                    video_id=master.id,
                    iteration=critique.iteration,
                    decision=critique.decision,
                    global_score=critique.score,
                    feedback={
                        "summary": critique.summary,
                        "strengths": critique.strengths,
                        "issues": critique.issues,
                        "video": critique.video,
                    },
                    requested_changes=[c.model_dump() for c in critique.changes],
                ))
            await session.commit()
            await session.refresh(master)

        await self._export_platforms(master_path, duration, result.iterations)
        await self._update_project_config(scenario, credits, result, session_result, critiques)
        shutil.rmtree(run_dir / "media" / ".cache", ignore_errors=True)
        return master

    async def _export_platforms(self, master_path: Path, duration: float, iteration: int) -> None:
        """Un Video `short_<plateforme>` par plateforme activée (file Distribution)."""
        from agent.core.storage import persist_video_to_storage

        enabled = [p for p in PLATFORMS if p in set(self.ctx.channel_config.enabled_platforms)]
        for platform in enabled:
            out = self.output_dir / f"short_{platform}.mp4"
            shutil.copy2(master_path, out)
            async with AsyncSessionFactory() as session:
                video = Video(
                    project_id=self.ctx.project_id,
                    video_type=f"short_{platform}",
                    local_path=str(out),
                    duration_s=duration,
                    iteration=iteration,
                    status="draft",
                )
                session.add(video)
                await session.commit()
                await session.refresh(video)
            await persist_video_to_storage(video, self.ctx.channel_slug, out, delete_local=False)

    def _load_critiques(self) -> list[Critique]:
        critiques: list[Critique] = []
        for path in sorted(self.run_dir.glob("critique_*.json")):
            try:
                critiques.append(load_contract(path, Critique))
            except ContractError as exc:
                logger.warning("Critique ignorée (%s) : %s", path.name, exc)
        return sorted(critiques, key=lambda c: c.iteration)

    @staticmethod
    def _load_credits(final_video: Path) -> list[dict[str, Any]]:
        return list(read_json(final_video.with_suffix(".render.json"), {}).get("credits") or [])

    def _thumbnail_config(self) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        try:
            thumb = load_contract(self.run_dir / "thumbnail.json", Thumbnail)
        except ContractError as exc:
            logger.warning("Miniature absente ou invalide : %s", exc)
            return None, []
        candidates: list[dict[str, Any]] = []
        # La 16:9 sert de miniature YouTube ; la 9:16 reste disponible (cover TikTok/Reels).
        for key, rel, aspect in (("horizontal", thumb.horizontal, "16:9"), ("vertical", thumb.vertical, "9:16")):
            if not rel or not (self.run_dir / rel).exists():
                continue
            dest = self.output_dir / f"thumbnail_{key}{Path(rel).suffix}"
            shutil.copy2(self.run_dir / rel, dest)
            candidates.append({
                "local_path": str(dest),
                "prompt": f"{aspect} — {' '.join(thumb.text.split('|'))}" if thumb.text else aspect,
                "attribution": thumb.background or None,
                "primary": not candidates,
            })
        return (candidates[0] if candidates else None), candidates

    async def _update_project_config(
        self,
        scenario: StudioScenario,
        credits: list[dict[str, Any]],
        result: StudioResult,
        session_result: dict[str, Any],
        critiques: list[Critique],
    ) -> None:
        primary_thumb, thumb_candidates = self._thumbnail_config()
        hashtags = [h if h.startswith("#") else f"#{h}" for h in scenario.publish.hashtags]
        description = scenario.publish.description.strip()
        credit_lines = [c.get("attribution") for c in credits if c.get("attribution")]
        if hashtags:
            description += "\n\n" + " ".join(hashtags)
        if credit_lines:
            description += "\n\nCrédits :\n" + "\n".join(f"- {line}" for line in credit_lines)
        metadata = {
            "title": scenario.publish.title,
            "description": description,
            "tags": [h.lstrip("#") for h in hashtags],
            "source": "claude_studio",
        }
        studio_info = {
            "run_dir": str(self.run_dir),
            "status": result.status,
            "iterations": result.iterations,
            "final_video": result.final_video,
            "scores": [c.score for c in critiques],
            "notes": result.notes,
            "cost_usd": session_result.get("total_cost_usd"),
            "num_turns": session_result.get("num_turns"),
            "credits": credits,
        }
        async with AsyncSessionFactory() as session:
            project = await session.get(Project, self.ctx.project_id)
            if project is None:
                return
            config = dict(project.config or {})
            config["youtube_metadata"] = metadata
            config["claude_studio"] = studio_info
            if primary_thumb:
                config["thumbnail"] = primary_thumb
                config["thumbnail_candidates"] = thumb_candidates
            await session.execute(
                update(Project)
                .where(Project.id == self.ctx.project_id)
                .values(config=config, title=scenario.publish.title)
            )
            await session.commit()
