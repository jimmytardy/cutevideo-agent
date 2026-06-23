from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import delete

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, AudioFile, Scenario
from agent.core.scenario_integrity import scenario_expects_narration

logger = logging.getLogger(__name__)


def segment_needs_voice(segment: dict) -> bool:
    if segment.get("needs_voice") is False:
        return False
    text = (segment.get("narration_text") or "").strip()
    if not text:
        return False
    return bool(segment.get("needs_voice", True))


def segment_needs_music(segment: dict) -> bool:
    """True si le segment demande une musique de fond."""
    if "needs_music" in segment:
        return bool(segment["needs_music"])
    return bool(segment.get("needs_voice", True))


class NarratorAgent(BaseAgent):
    """Agent 3 — Narrateur voix : synthèse TTS pour les segments qui en ont besoin."""

    name = "narrator_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> list[AudioFile]:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id, {"scenario_id": str(scenario.id)}, iteration=ctx.iteration
        )
        try:
            audio_files = await self._generate_all_audio(ctx, scenario)
            await self.end_run(run, {"audio_count": len(audio_files)})
            return audio_files
        except asyncio.CancelledError:
            await self.stop_run(run)
            raise
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def run_derivation(
        self, ctx: "PipelineContext", plan: "DerivedShortPlan"
    ) -> list[AudioFile]:
        from agent.core.short_derivation import DerivedShortPlan
        from agent.skills.shorts.derivation import run_narration_for_short_derivation

        run = await self.start_run(
            ctx.project_id,
            {"derivation_index": plan.index, "mode": "short_derivation"},
        )
        try:
            audio_files = await run_narration_for_short_derivation(self, ctx, plan)
            await self.end_run(run, {"audio_count": len(audio_files)})
            return audio_files
        except asyncio.CancelledError:
            await self.stop_run(run)
            raise
        except Exception as e:
            await self.fail_run(run, e)
            raise

    @staticmethod
    def _audio_iteration(ctx: "PipelineContext") -> int:
        from agent.core.short_derivation import derivation_iteration

        if ctx.derivation_short_index is not None:
            return derivation_iteration(ctx.derivation_short_index)
        return ctx.iteration

    async def _clear_existing_audio(
        self, project_id: uuid.UUID, *, iteration: int
    ) -> None:
        async with AsyncSessionFactory() as session:
            await session.execute(
                delete(AudioFile).where(
                    AudioFile.project_id == project_id,
                    AudioFile.iteration == iteration,
                )
            )
            await session.commit()

    async def _generate_all_audio(
        self, ctx: "PipelineContext", scenario: Scenario
    ) -> list[AudioFile]:
        segments = scenario.segments or []
        voice_segments = [s for s in segments if segment_needs_voice(s)]

        await self._clear_existing_audio(
            ctx.project_id, iteration=self._audio_iteration(ctx)
        )

        output_dir = Path(f"./tmp/{ctx.project_id}/audio")
        output_dir.mkdir(parents=True, exist_ok=True)

        from agent.core.concurrency import bounded_gather

        tasks = [self._generate_segment_audio(ctx, segment, output_dir) for segment in voice_segments]
        results = await bounded_gather(*tasks, return_exceptions=True)

        audio_files: list[AudioFile] = []
        errors: list[Exception] = []
        for result in results:
            if isinstance(result, AudioFile):
                audio_files.append(result)
            elif isinstance(result, Exception):
                logger.warning("Erreur génération audio : %s", result)
                errors.append(result)

        skipped = len(segments) - len(voice_segments)
        if skipped:
            logger.info("Narration : %d segment(s) sans voix (choix éditorial)", skipped)

        if voice_segments and not audio_files:
            detail = str(errors[0]) if errors else "aucune cause enregistrée"
            raise RuntimeError(
                f"Narration requise pour {len(voice_segments)} segment(s) "
                f"mais 0 fichier audio généré — {detail}"
            )

        if not audio_files and scenario_expects_narration(segments):
            raise RuntimeError(
                "Scénario attend de la narration (narration_text ou phrase_anchor) "
                "mais 0 fichier audio généré — vérifier diagram_specialist / scénario actif"
            )

        audio_files.sort(key=lambda a: a.segment_order or 0)
        logger.info("Narration : %d fichiers audio générés", len(audio_files))
        return audio_files

    async def _generate_segment_audio(
        self, ctx: "PipelineContext", segment: dict, output_dir: Path
    ) -> AudioFile:
        from agent.core.api_keys import fetch_api_key
        from agent.skills.audio.tts import generate_tts

        order = segment.get("order", 0)
        text = segment.get("narration_text", "")
        cfg = ctx.channel_config
        if cfg.tts_oralize and text.strip():
            from agent.skills.audio.oralize import oralize_text

            text = oralize_text(text)
        output_path = output_dir / f"segment_{order:02d}.wav"
        delivery_style = segment.get("delivery_style") or {}
        mood = str(segment.get("mood") or "")
        # P6 — Sur un retour critique « voix trop plate », varie réellement la direction
        # voix (pace/emotion/azure_style) par segment plutôt que de re-synthétiser à l'identique.
        if ctx.critic_start_from == "narrator_agent":
            from agent.skills.audio.voice_direction import direct_voice_for_revision

            delivery_style = direct_voice_for_revision(
                delivery_style,
                segment_index=int(order),
                iteration=ctx.iteration,
                mood=mood,
            )
            logger.info(
                "Direction voix (P6) segment %s → %s/%s/%s",
                order,
                delivery_style.get("pace"),
                delivery_style.get("emotion"),
                delivery_style.get("azure_style"),
            )
        from agent.core.channel_config import tts_profile_for_channel
        from agent.skills.audio.tts import resolve_tts_settings

        gemini_ctx = await fetch_api_key(
            ctx.user_id, "gemini", purpose="gemini_tts", tier="free"
        )
        azure_ctx = await fetch_api_key(
            ctx.user_id, "azure_speech", purpose="tts_azure", tier="paid"
        )
        azure_region = (azure_ctx.metadata or {}).get("region")

        is_short = ctx.is_short_project or ctx.derivation_short_index is not None
        tts_profile = tts_profile_for_channel(cfg, is_short=is_short)

        tts_settings = resolve_tts_settings(
            default_engine=tts_profile.engine,
            default_voice=tts_profile.voice,
            gemini_apply_to=cfg.gemini_tts.apply_to,
            gemini_voice=cfg.gemini_tts.voice,
            gemini_model=cfg.gemini_tts.model,
            gemini_language_code=cfg.gemini_tts.language_code,
            is_short=is_short,
            gemini_api_key=gemini_ctx.key,
            azure_speech_key=azure_ctx.key,
            azure_speech_region=azure_region,
        )

        duration_s, effective_engine = await generate_tts(
            text=text,
            output_path=output_path,
            voice=tts_settings.voice,
            engine=tts_settings.engine,
            delivery_style=delivery_style,
            mood=mood,
            editorial_tone=cfg.editorial_tone,
            tts_style=cfg.tts_style,
            tts_rate=cfg.tts_rate,
            tts_pitch=cfg.tts_pitch,
            insert_pauses=cfg.tts_insert_pauses,
            comma_pauses=cfg.tts_comma_pauses,
            mastering=cfg.audio_mastering.model_dump(),
            gemini_model=tts_settings.gemini_model,
            gemini_language_code=tts_settings.gemini_language_code,
            gemini_api_key=tts_settings.gemini_api_key,
            azure_speech_key=tts_settings.azure_speech_key,
            azure_speech_region=tts_settings.azure_speech_region,
        )

        word_timestamps: list[dict] | None = None
        if cfg.visual_beats.enabled and text.strip():
            from agent.core.config import load_agent_config
            from agent.skills.audio.whisper_utils import transcribe_to_words

            whisper_cfg = load_agent_config().get("whisper", {})
            words = await transcribe_to_words(
                [output_path],
                model_name=str(whisper_cfg.get("model", "large-v3")),
                language=str(whisper_cfg.get("language", "fr")),
            )
            word_timestamps = [
                {"word": w.word, "start": w.start, "end": w.end} for w in words
            ]

        async with AsyncSessionFactory() as session:
            audio_file = AudioFile(
                project_id=ctx.project_id,
                iteration=self._audio_iteration(ctx),
                segment_order=order,
                local_path=str(output_path),
                duration_s=duration_s,
                tts_engine=effective_engine,
                voice=tts_settings.voice,
                transcript=text,
                word_timestamps=word_timestamps,
            )
            session.add(audio_file)
            await session.commit()
            await session.refresh(audio_file)

        return audio_file
