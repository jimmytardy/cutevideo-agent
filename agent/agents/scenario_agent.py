from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Scenario
from agent.core.learning_context import LEARNING_CONTEXT_BLOCK

logger = logging.getLogger(__name__)

AVAILABLE_SOURCES = """Sources médias disponibles (utilise leurs noms exacts dans source_hint) :
- gallica        : archives BnF, France historique (avant 1950)
- europeana      : patrimoine européen, musées, archives
- wikimedia      : encyclopédique, toutes époques, monde entier
- internet_archive : films, docs, médias anciens domaine public
- pexels         : photos/vidéos stock modernes, lifestyle, nature
- pixabay        : idem pexels, plus de variété
- unsplash       : photos artistiques, ambiances, architecture
- nasa           : espace, astronomie, science
- ai             : génération IA si aucune source réelle ne convient"""

SYSTEM_PROMPT_LONG = """Tu es un scénariste expert en vidéos documentaires YouTube éducatives.
Tu maîtrises les techniques narratives des meilleures chaînes françaises.
Tu produis toujours des JSON valides, sans texte avant ni après."""

SYSTEM_PROMPT_SHORT = """Tu es un scénariste expert en formats courts verticaux (YouTube Shorts, TikTok).
Tu maîtrises l'humour, le rythme rapide et les hooks visuels.
Tu produis toujours des JSON valides, sans texte avant ni après.

RÈGLE VOIX : la narration vocale n'est PAS obligatoire. Pour chaque segment, décide si une voix
apporte de la valeur (`needs_voice: true`) ou si le visuel + texte à l'écran suffisent (`needs_voice: false`).
Réserve la voix aux moments où elle clarifie, accroche ou renforce l'émotion — pas systématiquement."""

USER_PROMPT_LONG = """Crée un scénario détaillé pour une vidéo de {duration_min} minutes.

CHAÎNE : {channel_name} (catégorie : {theme_category})
THÈME CHAÎNE : {theme_prompt}
CONTEXTE ÉDITORIAL : {niche_prompt}
TON ÉDITORIAL : {editorial_tone}
SUJET DE LA VIDÉO : "{theme}"

{content_plan_block}

{learning_block}

Retourne UNIQUEMENT un JSON valide avec cette structure :
{{
  "title": "Titre accrocheur YouTube (max 70 caractères)",
  "description": "Description YouTube SEO (max 500 caractères)",
  "segments": [
    {{
      "order": 1,
      "title": "Titre du segment",
      "duration_s": 150,
      "needs_voice": true,
      "narration_text": "Texte complet de narration (minimum 300 mots si needs_voice true, sinon vide)",
      "on_screen_text": "",
      "search_keywords": ["mot-clé 1 fr", "keyword 1 en", "mot-clé 2 fr", "keyword 2 en"],
      "source_hint": ["gallica", "wikimedia"],
      "historical_period": "Antiquité | Moyen-Âge | Moderne | Contemporain | N/A",
      "hook_type": "question | fait_surprenant | anecdote | chiffre | null",
      "delivery_style": {{
        "pace": "normal",
        "emotion": "serious",
        "azure_style": "narration-professional",
        "emphasis_words": []
      }}
    }}
  ],
  "total_duration_s": 1800
}}

Principes OBLIGATOIRES :
- Hook fort dans les 30 premières secondes
- Chaque segment : MINIMUM 4 mots-clés (2 FR + 2 EN)
- Narration naturelle si needs_voice true
- Total : environ {duration_min} minutes

{sources_block}
Pour source_hint : choisis 2-3 sources dans l'ordre de pertinence pour chaque segment selon son sujet et sa période."""

USER_PROMPT_SHORT = """Crée un scénario pour un SHORT vertical de {duration_s} secondes.

CHAÎNE : {channel_name} (catégorie : {theme_category})
THÈME CHAÎNE : {theme_prompt}
CONTEXTE : {niche_prompt}
TON : {editorial_tone}
SUJET : "{theme}"

{content_plan_block}

{learning_block}

Retourne UNIQUEMENT ce JSON :
{{
  "title": "Titre accrocheur (max 60 car.)",
  "description": "Description courte",
  "segments": [
    {{
      "order": 1,
      "title": "Hook",
      "duration_s": {segment_duration},
      "needs_voice": true,
      "narration_text": "Texte voix SI needs_voice true, sinon \"\"",
      "on_screen_text": "Texte à l'écran si pas de voix ou en complément",
      "search_keywords": ["kw fr", "kw en", "kw2 fr", "kw2 en"],
      "source_hint": ["pexels", "pixabay"],
      "historical_period": "N/A",
      "hook_type": "fait_surprenant",
      "delivery_style": {{
        "pace": "fast",
        "emotion": "playful",
        "azure_style": "cheerful",
        "emphasis_words": []
      }}
    }}
  ],
  "total_duration_s": {duration_s}
}}

RÈGLES SHORT :
- 1 à 3 segments de 15-30 s chacun
- needs_voice : true UNIQUEMENT si la voix améliore le contenu (pas par défaut)
- Formats sans voix OK : visuels + on_screen_text, meme-style, musique
- Rythme rapide, punchlines si ton humoristique
- Total ~{duration_s} s

{sources_block}
Pour source_hint : 2-3 sources dans l'ordre de pertinence pour le sujet du segment."""


def _format_content_plan_block(plan: dict[str, Any] | None) -> str:
    if not plan:
        return ""
    lines = [
        "MANDAT ÉDITORIAL (content_planner) :",
        f"- Titre provisoire : {plan.get('provisional_title', '')}",
        f"- Angle : {plan.get('angle', '')}",
        f"- Format narratif : {plan.get('narrative_format', '')}",
    ]
    return "\n".join(lines)


@dataclass
class ScenarioInput:
    project_id: uuid.UUID
    theme: str
    target_duration_seconds: int
    channel_name: str
    theme_category: str
    theme_prompt: str
    niche_prompt: str
    editorial_tone: str
    production_mode: str
    learning_context_prompt: str
    content_plan_block: str = ""


class ScenarioAgent(BaseAgent):
    """Agent 1 — Scénariste : crée la structure narrative complète."""

    name = "scenario_agent"

    async def run(self, ctx: "PipelineContext") -> Scenario:  # type: ignore[override]
        theme_prompt = ctx.channel.theme_prompt or ctx.niche_prompt or ""
        input_data = ScenarioInput(
            project_id=ctx.project_id,
            theme=ctx.theme,
            target_duration_seconds=ctx.target_duration_seconds,
            channel_name=ctx.channel.name,
            theme_category=ctx.theme_category,
            theme_prompt=theme_prompt,
            niche_prompt=ctx.niche_prompt,
            editorial_tone=ctx.channel_config.editorial_tone,
            production_mode=ctx.channel_config.production_mode,
            learning_context_prompt=ctx.learning_context_prompt,
            content_plan_block=_format_content_plan_block(ctx.content_plan),
        )
        run = await self.start_run(ctx.project_id, input_data)
        try:
            scenario = await self._generate_scenario(input_data)
            await self.end_run(run, {"scenario_id": str(scenario.id)})
            return scenario
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _generate_scenario(self, input_data: ScenarioInput) -> Scenario:
        is_short = input_data.production_mode == "shorts_only" or input_data.target_duration_seconds <= 120
        learning_block = LEARNING_CONTEXT_BLOCK.format(
            learning_context_prompt=input_data.learning_context_prompt,
        )

        if is_short:
            segment_duration = min(30, max(15, input_data.target_duration_seconds // 2))
            prompt = USER_PROMPT_SHORT.format(
                duration_s=input_data.target_duration_seconds,
                segment_duration=segment_duration,
                channel_name=input_data.channel_name,
                theme_category=input_data.theme_category,
                theme_prompt=input_data.theme_prompt or input_data.niche_prompt,
                niche_prompt=input_data.niche_prompt or "Contenu court vertical",
                editorial_tone=input_data.editorial_tone,
                theme=input_data.theme,
                content_plan_block=input_data.content_plan_block,
                learning_block=learning_block,
                sources_block=AVAILABLE_SOURCES,
            )
            system = SYSTEM_PROMPT_SHORT
            if "humor" in input_data.editorial_tone.lower() or "humour" in input_data.editorial_tone.lower():
                system += "\nPriorise l'humour, le second degré et les formats sans voix quand le visuel suffit."
        else:
            duration_min = max(1, input_data.target_duration_seconds // 60)
            prompt = USER_PROMPT_LONG.format(
                duration_min=duration_min,
                channel_name=input_data.channel_name,
                theme_category=input_data.theme_category,
                theme_prompt=input_data.theme_prompt or input_data.niche_prompt,
                niche_prompt=input_data.niche_prompt or "Vidéo éducative française",
                editorial_tone=input_data.editorial_tone,
                theme=input_data.theme,
                content_plan_block=input_data.content_plan_block,
                learning_block=learning_block,
                sources_block=AVAILABLE_SOURCES,
            )
            system = SYSTEM_PROMPT_LONG

        raw = await self._call_claude(prompt, system=system, max_tokens=8192)
        data = self._parse_json(raw)

        async with AsyncSessionFactory() as session:
            scenario = Scenario(
                project_id=input_data.project_id,
                segments=data.get("segments", []),
                total_duration_s=data.get("total_duration_s", input_data.target_duration_seconds),
                iteration=1,
            )
            session.add(scenario)

            from agent.core.database import Project
            from sqlalchemy import update

            await session.execute(
                update(Project)
                .where(Project.id == input_data.project_id)
                .values(title=data.get("title"))
            )
            await session.commit()
            await session.refresh(scenario)

        logger.info("Scénario créé : %d segments", len(scenario.segments or []))
        return scenario

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
