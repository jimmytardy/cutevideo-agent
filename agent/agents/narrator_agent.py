from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, AudioFile, Scenario

logger = logging.getLogger(__name__)


def segment_needs_voice(segment: dict) -> bool:
    if segment.get("needs_voice") is False:
        return False
    text = (segment.get("narration_text") or "").strip()
    if not text:
        return False
    return bool(segment.get("needs_voice", True))


class NarratorAgent(BaseAgent):
    """Agent 3 — Narrateur voix : synthèse TTS pour les segments qui en ont besoin."""

    name = "narrator_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> list[AudioFile]:  # type: ignore[override]
        run = await self.start_run(ctx.project_id, {"scenario_id": str(scenario.id)})
        try:
            audio_files = await self._generate_all_audio(ctx, scenario)
            await self.end_run(run, {"audio_count": len(audio_files)})
            return audio_files
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _generate_all_audio(
        self, ctx: "PipelineContext", scenario: Scenario
    ) -> list[AudioFile]:
        segments = scenario.segments or []
        output_dir = Path(f"./tmp/{ctx.project_id}/audio")
        output_dir.mkdir(parents=True, exist_ok=True)

        voice_segments = [s for s in segments if segment_needs_voice(s)]
        tasks = [self._generate_segment_audio(ctx, segment, output_dir) for segment in voice_segments]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        audio_files: list[AudioFile] = []
        for result in results:
            if isinstance(result, AudioFile):
                audio_files.append(result)
            elif isinstance(result, Exception):
                logger.warning("Erreur génération audio : %s", result)

        skipped = len(segments) - len(voice_segments)
        if skipped:
            logger.info("Narration : %d segment(s) sans voix (choix éditorial)", skipped)

        audio_files.sort(key=lambda a: a.segment_order or 0)
        logger.info("Narration : %d fichiers audio générés", len(audio_files))
        return audio_files

    async def _generate_segment_audio(
        self, ctx: "PipelineContext", segment: dict, output_dir: Path
    ) -> AudioFile:
        from agent.skills.audio.tts import generate_tts

        order = segment.get("order", 0)
        text = segment.get("narration_text", "")
        output_path = output_dir / f"segment_{order:02d}.wav"
        delivery_style = segment.get("delivery_style") or {}
        cfg = ctx.channel_config

        duration_s = await generate_tts(
            text=text,
            output_path=output_path,
            voice=cfg.tts_voice,
            engine=cfg.tts_engine,
            delivery_style=delivery_style,
            editorial_tone=cfg.editorial_tone,
            tts_style=cfg.tts_style,
            tts_rate=cfg.tts_rate,
            tts_pitch=cfg.tts_pitch,
        )

        async with AsyncSessionFactory() as session:
            audio_file = AudioFile(
                project_id=ctx.project_id,
                segment_order=order,
                local_path=str(output_path),
                duration_s=duration_s,
                tts_engine=cfg.tts_engine,
                voice=cfg.tts_voice,
                transcript=text,
            )
            session.add(audio_file)
            await session.commit()
            await session.refresh(audio_file)

        return audio_file
