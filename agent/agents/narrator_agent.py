from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, AudioFile, Scenario

logger = logging.getLogger(__name__)


class NarratorAgent(BaseAgent):
    """Agent 3 — Narrateur voix : synthèse TTS pour chaque segment."""

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

        tasks = [
            self._generate_segment_audio(ctx, segment, output_dir)
            for segment in segments
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        audio_files: list[AudioFile] = []
        for result in results:
            if isinstance(result, AudioFile):
                audio_files.append(result)
            elif isinstance(result, Exception):
                logger.warning("Erreur génération audio : %s", result)

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

        voice = ctx.channel_config.tts_voice
        duration_s = await generate_tts(
            text=text,
            output_path=output_path,
            voice=voice,
        )

        async with AsyncSessionFactory() as session:
            audio_file = AudioFile(
                project_id=ctx.project_id,
                segment_order=order,
                local_path=str(output_path),
                duration_s=duration_s,
                tts_engine="edge-tts",
                voice=voice,
                transcript=text,
            )
            session.add(audio_file)
            await session.commit()
            await session.refresh(audio_file)

        logger.debug("Audio segment %d : %.1f s", order, duration_s)
        return audio_file
