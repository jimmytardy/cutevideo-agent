"""Pipeline de création « Claude Studio » : Claude Code (CLI headless) produit le Short.

L'orchestrateur Python ne fait plus que :
1. écrire `brief.json` dans un run dir à partir du `PipelineContext` ;
2. lancer `claude -p /make-video` (cf. `studio/launcher.py`) qui orchestre les
   sous-agents scénariste → voix → monteur → critique en boucle, puis le miniaturiste
   une fois sur la vidéo finale ;
3. refléter la progression en DB (`AgentRun`) et Redis (statut temps réel) ;
4. persister le résultat : Scenario, Video (short_master + exports plateformes),
   CriticReport, métadonnées de publication et miniature dans `Project.config`.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from sqlalchemy import func, select, update

from agent.core.database import (
    AgentRun,
    AsyncSessionFactory,
    CriticReport,
    Project,
    Scenario,
    Video,
)
from agent.core.pipeline_cancel import is_worker_shutdown
from agent.core import studio_resume
from agent.skills.media_sources.ai.registry import models_up_to
from studio.agent_stream import coalesce, encode, trim
from studio.contracts import (
    PublishMetadata,
    VOICE_CACHE_DIR,
    Brief,
    ContractError,
    Critique,
    Scenario as StudioScenario,
    ScenarioCritique,
    StudioResult,
    Thumbnail,
    load_contract,
    read_json,
    resolve_in_run_dir,
    write_json,
)
from studio.launcher import (
    ClaudeRunError,
    background_tasks_stopped,
    default_runs_dir,
    prepare_run_dir,
    run_claude,
)
from studio.render import RENDER_DIR

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

# Rôle Claude → nom d'agent historique (dashboard, AgentRun, statuts Redis).
ROLE_AGENT_NAMES = {
    "scenariste": "scenario_agent",
    "critique-scenario": "scenario_critic_agent",  # boucle scénario, avant la voix (itération 1)
    "voix": "narrator_agent",
    "monteur": "editor_agent",
    "critique": "critic_agent",
    "miniaturiste": "thumbnail_agent",  # une fois, après la boucle
}
STUDIO_AGENT_ORDER = list(ROLE_AGENT_NAMES.values())
# Étapes non relancées par une itération (rôle non cité par la critique) : dupliquées en `reused`.
REUSABLE_AGENTS = ("scenario_agent", "scenario_critic_agent", "narrator_agent")
PLATFORMS = ("youtube", "tiktok", "instagram")
OUTPUT_ROOT = Path("./output/studio")
_MAX_LOGGED_CHARS = 4000
# Écriture de la trace d'un sous-agent (AgentRun.log) au plus toutes les N secondes.
LOG_FLUSH_INTERVAL_S = 1.5
# Reprise après un redémarrage du worker (cf. agent/core/studio_resume.py).
RESUME_FILE = "resume.json"
RESUME_PROMPT = (
    "La session a été interrompue par un redémarrage du serveur. Reprends la production là où elle en était "
    "(section « Reprise » de /make-video, `resume.json`) : ne refais pas ce qui est déjà produit et valide, "
    "relance l'étape interrompue en demandant au rôle de réutiliser les fichiers déjà présents."
)


def build_brief(ctx: PipelineContext) -> Brief:
    cfg = ctx.channel_config
    plan = ctx.content_plan or {}
    ai = cfg.ai_fallback
    ai_on = ai.enabled and ai.plan.value != "off"
    return Brief(
        theme=ctx.theme,
        niche=ctx.niche_prompt,
        angle=str(plan.get("angle") or plan.get("hook") or ""),
        language=cfg.content_language or "fr",
        target_duration_s=max(15, min(int(ctx.target_duration_seconds or cfg.short_duration_s), 180)),
        voice=cfg.tts_short.voice or cfg.tts_voice,
        tts_engine=cfg.tts_short.engine or cfg.tts_engine,
        max_iterations=max(1, min(ctx.max_critic_iterations or cfg.max_critic_iterations, 6)),
        min_score=cfg.min_critic_score,
        max_scenario_iterations=max(1, min(cfg.max_scenario_iterations, 6)),
        min_scenario_score=cfg.min_scenario_score,
        editorial_tone=cfg.editorial_tone,
        creative_brief=(ctx.channel.creative_brief or "").strip(),
        content_plan=plan or None,
        animations=cfg.studio_animations,
        visual_style=cfg.studio_visual_style,
        max_ai_images=ai.max_ai_images_per_video if ai_on else 0,
        ai_models=models_up_to(ai.plan.value) if ai_on else [],
    )


class _ProgressRecorder:
    """Reflète les événements du stream Claude en AgentRun (statut + trace `log` au fil de l'eau)."""

    def __init__(self, project_id: uuid.UUID, *, iteration: int = 1) -> None:
        self.project_id = project_id
        self.pid = str(project_id)
        self.iteration = iteration
        self.runs: dict[str, uuid.UUID] = {}
        self.logs: dict[str, list[str]] = {}  # tool_use_id du sous-agent → lignes de trace
        self._last_flush: dict[str, float] = {}
        self._pending: dict[str, asyncio.Task[None]] = {}
        self._writing: set[str] = set()  # écritures différées en cours vers la base (à ne pas annuler)
        # Étapes finies en erreur sur un texte de limite d'usage : « interrupted » seulement si la session est
        # ensuite mise en pause (`mark_limit_interrupted`), sinon elles restent des échecs.
        self.limit_failures: list[uuid.UUID] = []
        self.result: dict[str, Any] | None = None
        # Tâches de fond tuées par Claude Code (`task_id → libellé`) : la session s'arrête en plein travail.
        self.killed_tasks: dict[str, str] = {}

    async def __call__(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "agent_start":
            await self._start(data)
        elif kind == "agent_end":
            await self._end(data)
        elif kind == "agent_stream":
            self._stream(data)
        elif kind == "task_killed":
            self.killed_tasks[data["id"]] = data.get("label") or self.killed_tasks.get(data["id"], "")
        elif kind == "result":
            self.result = data

    async def _start(self, data: dict[str, Any]) -> None:
        name = ROLE_AGENT_NAMES.get(data["role"])
        if not name:
            return
        # Le miniaturiste tourne après la boucle : rattaché à la dernière itération critiquée.
        iteration = max(1, self.iteration - 1) if data["role"] == "miniaturiste" else self.iteration
        log = [f"--- Démarrage : {data.get('description') or data['role']} ---"]
        async with AsyncSessionFactory() as session:
            if data["role"] == "critique" and iteration > 1:
                await self._record_reused(session, iteration)
            run = AgentRun(
                project_id=self.project_id,
                agent_name=name,
                status="running",
                iteration=iteration,
                input_json={
                    "description": data.get("description", ""),
                    "prompt": str(data.get("prompt", ""))[:_MAX_LOGGED_CHARS],
                },
                log=log,
                started_at=datetime.now(UTC),
                llm_model="claude-code",
            )
            session.add(run)
            await session.commit()
            self.runs[data["id"]] = run.id
            self.logs[data["id"]] = log
            self._last_flush[data["id"]] = time.monotonic()

    async def _record_reused(self, session: AsyncSession, iteration: int) -> None:
        """Duplique en `reused` (coût nul) les étapes que l'itération n'a pas relancées."""
        runs = (
            await session.execute(
                select(AgentRun)
                .where(
                    AgentRun.project_id == self.project_id,
                    AgentRun.agent_name.in_(REUSABLE_AGENTS),
                    AgentRun.iteration <= iteration,
                )
                .order_by(AgentRun.iteration.asc(), AgentRun.started_at.asc())
            )
        ).scalars().all()
        latest: dict[str, AgentRun] = {}
        for run in runs:
            if run.status in ("success", "reused") or run.iteration == iteration:
                latest[run.agent_name or ""] = run
        now = datetime.now(UTC)
        for name, source in latest.items():
            if source.iteration == iteration:
                continue
            origin = int((source.output_json or {}).get("reused_from") or source.iteration)
            session.add(AgentRun(
                project_id=self.project_id,
                agent_name=name,
                status="reused",
                iteration=iteration,
                input_json=source.input_json,
                output_json={**(source.output_json or {}), "reused_from": origin},
                log=[f"--- Réutilisé de l'itération {origin} (non cité par la critique) ---"],
                started_at=now,
                ended_at=now,
                llm_model=source.llm_model,
            ))

    def _stream(self, data: dict[str, Any]) -> None:
        tool_id = data["id"]
        log = self.logs.get(tool_id)
        if log is None:
            return
        for line in data["lines"]:
            coalesce(log, line)
        if tool_id not in self._pending:
            delay = max(0.0, self._last_flush.get(tool_id, 0.0) + LOG_FLUSH_INTERVAL_S - time.monotonic())
            self._pending[tool_id] = asyncio.create_task(self._flush_later(tool_id, delay))

    async def _flush_later(self, tool_id: str, delay: float) -> None:
        """Écrit la trace après `delay` : un outil long (rendu) reste visible « en cours » sans attendre la suite."""
        try:
            await asyncio.sleep(delay)
            run_id = self.runs.get(tool_id)
            if run_id is None:
                return
            self._last_flush[tool_id] = time.monotonic()
            log = self.logs[tool_id] = trim(self.logs[tool_id])
            self._writing.add(tool_id)
            try:
                async with AsyncSessionFactory() as session:
                    await session.execute(update(AgentRun).where(AgentRun.id == run_id).values(log=list(log)))
                    await session.commit()
            finally:
                self._writing.discard(tool_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Trace du sous-agent %s non enregistrée", tool_id)
        finally:
            if self._pending.get(tool_id) is asyncio.current_task():
                del self._pending[tool_id]

    async def _final_log(self, tool_id: str, *lines: str) -> list[str]:
        """Annule l'écriture différée et renvoie la trace complétée, à écrire avec le statut final.

        Une écriture déjà en cours n'est pas annulée mais attendue : son UPDATE ne doit pas être validé
        après l'écriture finale (il effacerait « --- Fin --- »)."""
        task = self._pending.pop(tool_id, None)
        if task:
            if tool_id not in self._writing:
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._last_flush.pop(tool_id, None)
        log = self.logs.pop(tool_id, [])
        log.extend(lines)
        return trim(log)

    async def _end(self, data: dict[str, Any]) -> None:
        name = ROLE_AGENT_NAMES.get(data["role"])
        run_id = self.runs.pop(data["id"], None)
        if not name or run_id is None:
            return
        output = str(data.get("output", ""))[:_MAX_LOGGED_CHARS]
        status = "failed" if data["is_error"] else "success"
        if data["is_error"] and studio_resume.is_usage_limit_text(output):
            self.limit_failures.append(run_id)
        end_lines = [encode({"type": "error", "text": output[:500]})] if data["is_error"] else []
        end_lines.append(f"--- Fin : {'erreur' if data['is_error'] else 'succès'} ---")
        log = await self._final_log(data["id"], *end_lines)
        async with AsyncSessionFactory() as session:
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == run_id)
                .values(
                    status=status,
                    output_json={"summary": output},
                    error=output if data["is_error"] else None,
                    log=log,
                    ended_at=datetime.now(UTC),
                )
            )
            await session.commit()
        if data["role"] == "critique" and not data["is_error"]:
            self.iteration += 1

    async def mark_limit_interrupted(self) -> None:
        """Session mise en pause : les étapes arrêtées par la limite seront relancées à la reprise."""
        if not self.limit_failures:
            return
        async with AsyncSessionFactory() as session:
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id.in_(self.limit_failures))
                .values(status="interrupted", error=studio_resume.LIMIT_MESSAGE)
            )
            await session.commit()
        self.limit_failures.clear()

    async def close_dangling(self, status: str, reason: str) -> None:
        """Clôt les AgentRun restés ouverts (session interrompue)."""
        if not self.runs:
            return
        async with AsyncSessionFactory() as session:
            for tool_id, run_id in self.runs.items():
                log = await self._final_log(tool_id, f"--- Interrompu : {reason} ---")
                await session.execute(
                    update(AgentRun)
                    .where(AgentRun.id == run_id)
                    .values(status=status, error=reason, log=log, ended_at=datetime.now(UTC))
                )
            await session.commit()
        self.runs.clear()


class ClaudeStudioRunner:
    def __init__(self, ctx: PipelineContext) -> None:
        self.ctx = ctx
        self.run_dir = default_runs_dir() / str(ctx.project_id)
        self.output_dir = OUTPUT_ROOT / str(ctx.project_id)

    async def run(self) -> Video:
        from agent.core.api_keys import resolve_user_keys
        from agent.core.pipeline_reset import clear_creation_artifacts

        # Clés du propriétaire de la chaîne, vérifiées avant d'effacer la création précédente.
        keys = await resolve_user_keys(self.ctx.channel.user_id)
        if not (keys.anthropic or keys.claude_subscription):
            raise ClaudeRunError(
                "Aucune clé API Anthropic : ajoutez-la dans Compte → Clés API pour créer des vidéos"
            )
        config_dir = default_runs_dir() / ".claude-config" / str(self.ctx.channel.user_id)

        decision = await self._resume_decision() if self.ctx.resume else None
        if decision and decision.action == "give_up":
            await self._fail_open_runs(decision.reason)
            await self._discard_session(config_dir)
            raise ClaudeRunError(decision.reason)
        resuming = decision is not None and decision.action == "resume"
        # Abonnement Claude (mode CLI) : une limite d'usage met la création en pause jusqu'au reset.
        subscription = bool(keys.claude_subscription)
        if subscription and (limited_until := await studio_resume.get_user_limit(self.ctx.channel.user_id)):
            # Limite déjà connue pour ce compte : on attend le reset sans appeler Claude. Avant tout lancement,
            # seul le compteur de pauses est gardé (pas la session d'une création précédente).
            state = decision.state if resuming and decision else {
                "limit_pauses": (await self._session_state() or {}).get("limit_pauses", 0)
            }
            await self._pause(limited_until, state, config_dir)

        if resuming:
            assert decision is not None
            session_id = str(decision.state["session_id"])
            write_json(self.run_dir / RESUME_FILE, {
                "attempt": decision.state.get("resumes", 0),
                "limit_pauses": decision.state.get("limit_pauses", 0),
                "reason": decision.reason,
                "at": datetime.now(UTC).isoformat(),
            })
            await self._save_session_state(decision.state, error_message=f"Reprise automatique ({decision.reason})")
            logger.info("Claude Studio — projet %s : %s de la session %s", self.ctx.project_id, decision.reason, session_id)
        else:
            # Démarrage qui suit une pause d'avant lancement : le compteur de pauses continue (plafond borné).
            prior = (await self._session_state() or {}) if self.ctx.resume else {}
            carried = {"limit_pauses": prior["limit_pauses"]} if prior.get("limit_pauses") else {}
            brief = build_brief(self.ctx)
            # Relance complète : on repart d'un état propre (DB et run dir).
            async with AsyncSessionFactory() as session:
                await clear_creation_artifacts(self.ctx.project_id, session)
                await session.commit()
            for directory in (self.run_dir, self.output_dir):
                if directory.exists():
                    shutil.rmtree(directory)
            self._forget_session(config_dir)
            prepare_run_dir(self.run_dir, brief)
            session_id = str(uuid.uuid4())
            # Enregistré avant le lancement : un worker interrompu pourra reprendre cette session.
            await self._save_session_state({"session_id": session_id, **carried})
        session_state = decision.state if resuming and decision else {"session_id": session_id, **carried}
        logger.info("Claude Studio — projet %s, run dir %s", self.ctx.project_id, self.run_dir)

        recorder = _ProgressRecorder(self.ctx.project_id, iteration=self._next_iteration() if resuming else 1)
        launch = {"on_event": recorder, "keys": keys, "config_dir": config_dir}
        try:
            try:
                session_result = await run_claude(
                    self.run_dir,
                    prompt=RESUME_PROMPT if resuming else "/make-video",
                    session_id=session_id,
                    resume=resuming,
                    **launch,
                )
            except ClaudeRunError as exc:
                limited = subscription and studio_resume.usage_limit_reset(exc) is not None
                if limited or not (resuming and exc.no_turn_played):
                    raise
                # Session introuvable : nouvelle session qui reconstitue l'état depuis le run dir (resume.json).
                logger.warning("Projet %s : reprise de session impossible (%s), nouvelle session", self.ctx.project_id, exc)
                session_id = str(uuid.uuid4())
                session_state = {**session_state, "session_id": session_id}
                await self._save_session_state(session_state)
                session_result = await run_claude(self.run_dir, session_id=session_id, **launch)
        except BaseException as exc:
            if not isinstance(exc, Exception) and is_worker_shutdown():
                # Reprise au redémarrage : on garde la session et le run dir.
                await recorder.close_dangling("interrupted", studio_resume.INTERRUPTED_MESSAGE)
                raise
            limit_until = studio_resume.usage_limit_reset(exc) if isinstance(exc, ClaudeRunError) else None
            if limit_until and subscription:
                # Limite d'usage : session et run dir gardés, reprise au reset (ou abandon au plafond de pauses).
                await self._pause(limit_until, session_state, config_dir, recorder=recorder)  # NoReturn
            if limit_until:
                # Clé API : échec normal, mais nommé (le résultat Claude est vide sur une limite).
                exc = ClaudeRunError(f"{studio_resume.LIMIT_MESSAGE} (clé API : pas de pause automatique) — {exc}")
            await recorder.close_dangling("stopped" if not isinstance(exc, Exception) else "failed", str(exc)[:500])
            await self._discard_session(config_dir)  # plus de session à reprendre : état effacé comme en succès
            raise exc
        if not (self.run_dir / "result.json").exists() and background_tasks_stopped(self.run_dir):
            # Claude Code a tué ses tâches de fond au plafond d'attente puis terminé la session « avec succès »
            # sans écrire result.json. Session et run dir sont intacts : la création reprend où elle en était
            # (état de session déjà enregistré avant le lancement) au lieu d'être perdue.
            await recorder.close_dangling("interrupted", studio_resume.KILLED_TASK_MESSAGE)
            raise studio_resume.StudioInterrupted(sorted(recorder.killed_tasks.values()))
        await recorder.close_dangling("failed", "sous-agent non terminé")
        self._forget_session(config_dir)

        try:
            result = load_contract(self.run_dir / "result.json", StudioResult)
        except ContractError as exc:
            raise ClaudeRunError(f"Claude Studio n'a pas produit de résultat exploitable : {exc}") from exc
        if result.status == "failed" or not result.final_video:
            raise ClaudeRunError(f"Claude Studio a échoué : {result.notes or 'aucune vidéo finale'}")

        video = await self._persist(result, session_result)
        await self._save_session_state(None, error_message="")
        return video

    # ── reprise ──────────────────────────────────────────────────────────

    async def _discard_session(self, config_dir: Path) -> None:
        """Plus rien à reprendre : transcription Claude oubliée et état de session effacé."""
        self._forget_session(config_dir)
        await self._save_session_state(None)

    async def _fail_open_runs(self, reason: str) -> None:
        """Création abandonnée : aucune étape ne doit rester `running` ou `interrupted` (« reprise automatique »)."""
        async with AsyncSessionFactory() as session:
            await session.execute(
                update(AgentRun)
                .where(AgentRun.project_id == self.ctx.project_id, AgentRun.status.in_(("running", "interrupted")))
                .values(status="failed", error=reason, ended_at=datetime.now(UTC))
            )
            await session.commit()

    async def _pause(
        self,
        until: datetime,
        state: dict[str, Any] | None,
        config_dir: Path,
        *,
        recorder: _ProgressRecorder | None = None,
    ) -> NoReturn:
        """Pause jusqu'à `until` (limite d'usage) ; abandon au-delà de `STUDIO_MAX_LIMIT_PAUSES`.

        `recorder` = limite tombée en pleine création : ses étapes ouvertes finissent `interrupted` (reprise
        automatique) si la pause est accordée, `failed` si le plafond est atteint — le projet passe alors `failed`
        et ne doit pas afficher d'étape en attente de reprise.
        """
        allowed, state = studio_resume.record_pause(state, until)
        # Étapes d'abord (base), Redis ensuite : une panne Redis ne doit pas laisser d'étape `running`.
        if not allowed:
            reason = f"Limite d'usage Claude atteinte {state['limit_pauses']} fois, création abandonnée"
            if recorder is not None:
                await recorder.close_dangling("failed", reason)  # garde la trace « Interrompu » dans le log
            await self._fail_open_runs(reason)  # + étapes `interrupted` d'une pause précédente
        elif recorder is not None:
            await recorder.close_dangling("interrupted", studio_resume.LIMIT_MESSAGE)
            await recorder.mark_limit_interrupted()
        # Le compte est limité quoi qu'il arrive : les autres créations du compte attendent le reset.
        await studio_resume.set_user_limit(self.ctx.channel.user_id, until)
        if not allowed:
            await self._discard_session(config_dir)
            raise ClaudeRunError(reason)
        await self._save_session_state(state)
        logger.info("Projet %s : limite d'usage Claude, pause jusqu'à %s", self.ctx.project_id, until.isoformat())
        raise studio_resume.StudioPaused(until)

    async def _session_state(self) -> dict[str, Any] | None:
        async with AsyncSessionFactory() as session:
            project = await session.get(Project, self.ctx.project_id)
            state = (project.config or {}).get(studio_resume.CONFIG_KEY) if project else None
        return state if isinstance(state, dict) else None

    async def _resume_decision(self) -> studio_resume.ResumeDecision:
        async with AsyncSessionFactory() as session:
            progress = await session.scalar(
                select(func.count()).select_from(AgentRun).where(
                    AgentRun.project_id == self.ctx.project_id, AgentRun.status == "success"
                )
            )
        return studio_resume.decide(
            await self._session_state(),
            progress=int(progress or 0),
            run_dir_ok=studio_resume.run_dir_resumable(self.run_dir),
        )

    async def _save_session_state(self, state: dict[str, Any] | None, *, error_message: str | None = None) -> None:
        """État de reprise dans Project.config (None = terminé) ; `error_message=""` l'efface."""
        async with AsyncSessionFactory() as session:
            project = await session.get(Project, self.ctx.project_id)
            if project is None:
                return
            config = dict(project.config or {})
            if state is None:
                config.pop(studio_resume.CONFIG_KEY, None)
            else:
                config[studio_resume.CONFIG_KEY] = state
            values: dict[str, Any] = {"config": config}
            if error_message is not None:
                values["error_message"] = error_message or None
            await session.execute(update(Project).where(Project.id == self.ctx.project_id).values(**values))
            await session.commit()

    def _forget_session(self, config_dir: Path) -> None:
        """Supprime la transcription Claude Code de ce run et le marqueur de reprise."""
        for path in (config_dir / "projects").glob(f"*{self.ctx.project_id}*"):
            shutil.rmtree(path, ignore_errors=True)
        (self.run_dir / RESUME_FILE).unlink(missing_ok=True)

    def _next_iteration(self) -> int:
        """Itération en cours : la suivante de la dernière critique valide."""
        return max((c.iteration for c in self._load_critiques()), default=0) + 1

    # ── persistance ──────────────────────────────────────────────────────

    async def _persist(self, result: StudioResult, session_result: dict[str, Any]) -> Video:
        from studio.media import probe_media

        run_dir = self.run_dir
        scenario = load_contract(run_dir / "scenario.json", StudioScenario)
        final_src = resolve_in_run_dir(run_dir, result.final_video)
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
                        # Repli du dashboard une fois le run dir purgé : barres par critère + alertes.
                        "scores": critique.scores,
                        "analysis": critique.analysis,
                    },
                    requested_changes=[c.model_dump() for c in critique.changes],
                ))
            await session.commit()
            await session.refresh(master)

        await self._export_platforms(master_path, duration, result.iterations)
        await self._update_project_config(scenario, credits, result, session_result, critiques)
        # Caches de travail (médias, segments de rendu, lignes de voix) : inutiles une fois la vidéo persistée.
        for cache in (run_dir / "media" / ".cache", run_dir / RENDER_DIR, run_dir / VOICE_CACHE_DIR):
            shutil.rmtree(cache, ignore_errors=True)
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

    def _scenario_critiques(self) -> list[dict[str, Any]]:
        """Passes de la boucle scénario (stockées dans Project.config, pas de table dédiée)."""
        out: list[dict[str, Any]] = []
        for path in self.run_dir.glob("scenario_critique_*.json"):
            try:
                c = load_contract(path, ScenarioCritique)
            except ContractError as exc:
                logger.warning("Analyse scénario ignorée (%s) : %s", path.name, exc)
                continue
            out.append({
                "iteration": c.iteration,
                "score": c.score,
                "decision": c.decision,
                "summary": c.summary,
                "scores": c.scores,
                "changes": c.changes,
                "unverified_claims": c.unverified_claims,
            })
        return sorted(out, key=lambda c: c["iteration"])

    def _publish_metadata(self, scenario: StudioScenario) -> PublishMetadata:
        """Fiche de publication : `publish.json` (miniaturiste, une fois sur la vidéo finale) ; anciens run dirs :
        `scenario.publish`, sinon le titre du scénario."""
        path = self.run_dir / "publish.json"
        if path.exists():
            try:
                return load_contract(path, PublishMetadata)
            except ContractError as exc:
                logger.warning("publish.json invalide, fiche de publication dégradée : %s", exc)
        elif scenario.publish is None:
            logger.warning("publish.json absent : titre de travail publié, sans description ni légendes")
        return scenario.publish or PublishMetadata(title=scenario.title[:100])

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
        publish = self._publish_metadata(scenario)
        hashtags = [h if h.startswith("#") else f"#{h}" for h in publish.hashtags]
        description = publish.description.strip()
        credit_lines = [c.get("attribution") for c in credits if c.get("attribution")]
        if hashtags:
            description += "\n\n" + " ".join(hashtags)
        if credit_lines:
            description += "\n\nCrédits :\n" + "\n".join(f"- {line}" for line in credit_lines)
        metadata = {
            "title": publish.title,
            "description": description,
            "tags": [h.lstrip("#") for h in hashtags],
            # Légendes par plateforme (sans hashtags : ajoutés à la publication par build_caption).
            "tiktok_caption": publish.tiktok_caption.strip(),
            "instagram_caption": publish.instagram_caption.strip(),
            "source": "claude_studio",
        }
        studio_info = {
            "run_dir": str(self.run_dir),
            "status": result.status,
            "iterations": result.iterations,
            "final_video": result.final_video,
            "scores": [c.score for c in critiques],
            "scenario_critiques": self._scenario_critiques(),
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
                .values(config=config, title=publish.title)
            )
            await session.commit()
