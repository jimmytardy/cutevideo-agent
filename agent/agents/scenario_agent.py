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
- nasa           : espace, astronomie, science (images + vidéos NASA, domaine public)
- ai             : génération IA si aucune source réelle ne convient"""

SYSTEM_PROMPT_LONG = """Tu es un scénariste expert en vidéos YouTube longues (éducation, divertissement, documentaire).
Tu maîtrises les techniques narratives des meilleures chaînes YouTube francophones.
Tu produis toujours des JSON valides, sans texte avant ni après."""

SYSTEM_PROMPT_SHORT = """Tu es un scénariste expert en formats courts verticaux (YouTube Shorts, TikTok, Instagram Reels).
Tu maîtrises les hooks viraux, le rythme rapide et la narration percutante pour le scroll.
Tu produis toujours des JSON valides, sans texte avant ni après.

RÈGLE VOIX : pour le contenu éducatif, `needs_voice: true` par défaut — la voix clarifie et accroche.
Réserve `needs_voice: false` aux formats visuels purs (meme, ASMR, musique seule) où le visuel + texte à l'écran suffisent.
RÈGLE MUSIQUE : `needs_music` n'est pas obligatoire — false si le son ambiant du clip ou la voix seule suffisent."""

USER_PROMPT_LONG = """Crée un scénario détaillé pour une vidéo de {duration_min} minutes.

CHAÎNE : {channel_name} (catégorie : {theme_category})
THÈME CHAÎNE : {theme_prompt}
CONTEXTE ÉDITORIAL : {niche_prompt}
TON ÉDITORIAL : {editorial_tone}
{creative_brief_block}SUJET DE LA VIDÉO : "{theme}"

{content_plan_block}

{research_block}

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
      "needs_music": true,
      "narration_text": "Texte complet de narration (minimum 300 mots si needs_voice true, sinon vide)",
      "on_screen_text": "",
      "search_keywords": ["mot-clé 1 fr", "keyword 1 en", "mot-clé 2 fr", "keyword 2 en"],
      "source_hint": ["pexels", "wikimedia"],
      "mood": "inspirant",
      "strip_source_audio": true,
      "hook_type": "question | fait_surprenant | anecdote | chiffre | null",
      "delivery_style": {{
        "pace": "normal",
        "emotion": "serious",
        "azure_style": "narration-professional",
        "emphasis_words": []
      }}{visual_beats_comma}
      {visual_beats_example}
    }}
  ],
  "total_duration_s": 1800
}}

Principes OBLIGATOIRES :
- Hook fort dans les 30 premières secondes
- Chaque segment : MINIMUM 4 mots-clés (2 FR + 2 EN)
- Chaque search_keywords doit être ancré au SUJET DE LA VIDÉO (« {theme} ») et au contenu du segment (titre + narration)
- Inclure des termes précis (nom propre, lieu, concept, espèce, événement…) — jamais de mots-clés purement génériques seuls (ex. « nature », « animal », « histoire » sans qualificatif lié au sujet)
- Narration naturelle si needs_voice true
- Total : environ {duration_min} minutes

CHAMP mood — choisis parmi : energique | calme | dramatique | mysterieux | inspirant | humoristique | tension | revelateur
CHAMP strip_source_audio — true si la vidéo/image source doit être muette (narration ou musique seule), false si le son ambiant du clip enrichit le contenu (ex: applaudissements, sons de nature, ambiance lieu). Si needs_voice est false, mets strip_source_audio à false par défaut (sauf si tu veux explicitement une vidéo muette + musique seule).
CHAMP needs_music — true si une musique de fond améliore le segment ; false si voix seule, son ambiant seul, ou silence volontaire.

VOIX ET DELIVERY_STYLE (OBLIGATOIRE si needs_voice true) :
- Chaque segment avec voix DOIT avoir un delivery_style DIFFÉRENT des autres segments (varier pace, emotion, azure_style)
- Hook (segment 1) : pace "fast", emotion dynamique, azure_style énergique (excited, cheerful)
- Conclusion : pace "slow", emotion posée (calm, empathetic)
- emphasis_words : 3 à 8 mots par segment voix (noms propres, chiffres, mots-clés du hook)
- azure_style valides : narration-professional, cheerful, empathetic, excited, calm, sad, terrified, whispering, newscast-formal
- Ne JAMAIS répéter le même delivery_style sur tous les segments

{research_rules_block}
{critic_feedback_block}
{sources_block}
{visual_beats_rules}
Pour source_hint : choisis 2-3 sources dans l'ordre de pertinence pour le sujet du segment."""

USER_PROMPT_SHORT = """Crée un scénario pour un SHORT vertical de {duration_s} secondes.

CHAÎNE : {channel_name} (catégorie : {theme_category})
THÈME CHAÎNE : {theme_prompt}
CONTEXTE : {niche_prompt}
TON : {editorial_tone}
{creative_brief_block}SUJET : "{theme}"

{content_plan_block}

{research_block}

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
      "needs_music": true,
      "narration_text": "Texte voix SI needs_voice true, sinon \"\"",
      "on_screen_text": "Texte à l'écran si pas de voix ou en complément",
      "search_keywords": ["kw fr", "kw en", "kw2 fr", "kw2 en"],
      "source_hint": ["pexels", "pixabay"],
      "mood": "energique",
      "strip_source_audio": true,
      "hook_type": "fait_surprenant",
      "delivery_style": {{
        "pace": "fast",
        "emotion": "playful",
        "azure_style": "cheerful",
        "emphasis_words": []
      }}{visual_beats_comma}
      {visual_beats_example}
    }}
  ],
  "total_duration_s": {duration_s}
}}

RÈGLES SHORT :
- 1 à 3 segments de 15-30 s chacun
- needs_voice : true par défaut pour contenu éducatif ; false uniquement si visuel + on_screen_text suffisent
- needs_music : true seulement si la musique de fond apporte de la valeur ; false pour voix seule ou son ambiant
- search_keywords ancrés au SUJET (« {theme} ») et au segment — termes précis obligatoires, pas de mots-clés génériques seuls
- Formats sans voix OK : visuels + on_screen_text, meme-style, musique
- Rythme rapide, punchlines si ton humoristique
- Total ~{duration_s} s

CHAMP mood — choisis parmi : energique | calme | dramatique | mysterieux | inspirant | humoristique | tension | revelateur
CHAMP strip_source_audio — false par défaut si needs_voice est false (conserver sons ambiants des clips) ; true uniquement si tu veux une vidéo muette avec musique/texte seuls.
CHAMP needs_music — false si pas de bed musical pertinent (voix seule, ASMR, son ambiant du clip).

VOIX ET DELIVERY_STYLE (si needs_voice true) :
- delivery_style variable par segment ; hook rapide (pace fast), emphasis_words 3-5 mots
- Ne pas répéter le même azure_style sur tous les segments

{research_rules_block}
{critic_feedback_block}
{sources_block}
{visual_beats_rules}
Pour source_hint : 2-3 sources dans l'ordre de pertinence pour le sujet du segment."""


def _build_visual_beats_prompt_context(
    editorial_tone: str,
    theme_category: str,
    *,
    min_beats_short: int = 3,
    max_beats: int = 8,
    content_language: str = "fr",
    min_diagram_duration_long: float = 6.0,
    min_diagram_duration_short: float = 4.0,
    is_short: bool = False,
) -> dict[str, str]:
    from agent.core.visual_beats_prompt import build_visual_beats_prompt_context

    return build_visual_beats_prompt_context(
        editorial_tone,
        theme_category,
        min_beats_short=min_beats_short,
        max_beats=max_beats,
        content_language=content_language,
        min_diagram_duration_long=min_diagram_duration_long,
        min_diagram_duration_short=min_diagram_duration_short,
        is_short=is_short,
    )


def _format_creative_brief_block(brief: str) -> str:
    if not brief or not brief.strip():
        return ""
    return f"BRIEF CRÉATIF DE LA CHAÎNE :\n{brief.strip()}\n\n"


def _format_critic_feedback_block(feedback: list[dict] | None) -> str:
    if not feedback:
        return ""
    lines = ["CORRECTIONS DEMANDÉES PAR LE CRITIQUE (à appliquer impérativement) :"]
    for change in feedback:
        agent = change.get("agent", "?")
        desc = change.get("change_description", "")
        lines.append(f"- [{agent}] {desc}")
    lines.append("")
    return "\n".join(lines)


def _format_content_plan_block(plan: dict[str, Any] | None) -> str:
    if not plan:
        return ""
    entities = ", ".join(plan.get("main_entities") or [])
    seo = ", ".join(plan.get("seo_keywords") or [])
    lines = [
        "MANDAT ÉDITORIAL (content_planner) :",
        f"- Sujet mandaté : {plan.get('subject', '')}",
        f"- Titre provisoire : {plan.get('provisional_title', '')}",
        f"- Sous-thème : {plan.get('sub_theme', '')}",
        f"- Angle : {plan.get('angle', '')}",
        f"- Format narratif : {plan.get('narrative_format', '')}",
        f"- Entités centrales : {entities or '(aucune)'}",
        f"- Mots-clés SEO : {seo or '(aucun)'}",
    ]
    hook = plan.get("reactive_news_hook")
    if hook:
        lines.append(f"- Accroche actualité : {hook}")
    return "\n".join(lines) + "\n"


def _format_research_block(research_brief: dict[str, Any] | None) -> str:
    if not research_brief:
        return ""
    facts = research_brief.get("key_facts") or []
    timeline = research_brief.get("timeline") or []
    misconceptions = research_brief.get("common_misconceptions") or []
    sources = research_brief.get("sources") or []
    lines = [
        "RECHERCHE FACTUELLE (sources vérifiées — à respecter strictement) :",
        f"- Entité sujet : {research_brief.get('subject_entity', '')}",
        f"- Confiance recherche : {research_brief.get('confidence', 0)}",
        "Faits clés :",
    ]
    for fact in facts[:12]:
        lines.append(f"  • {fact}")
    if timeline:
        lines.append("Chronologie :")
        for entry in timeline[:8]:
            if isinstance(entry, dict):
                lines.append(f"  • {entry.get('year', '?')} — {entry.get('event', '')}")
    if misconceptions:
        lines.append("Idées reçues à déconstruire :")
        for m in misconceptions[:5]:
            lines.append(f"  • {m}")
    if sources:
        lines.append("Sources :")
        for src in sources[:6]:
            if isinstance(src, dict):
                lines.append(f"  • {src.get('title', '')} ({src.get('url', '')})")
    return "\n".join(lines) + "\n"


def _format_research_rules_block(research_brief: dict[str, Any] | None) -> str:
    if not research_brief:
        return ""
    return (
        "RÈGLES FACTUELLES : n'invente AUCUN fait, date ou nom absent de la recherche. "
        "Cite dates et chiffres précis issus des faits clés.\n\n"
    )


def _has_research_brief(research_brief: dict[str, Any] | None) -> bool:
    return bool(research_brief and research_brief.get("key_facts"))


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
    content_language: str = "fr"
    min_diagram_duration_s: float = 6.0
    min_diagram_duration_short_s: float = 4.0
    content_plan_block: str = ""
    research_block: str = ""
    research_rules_block: str = ""
    critic_feedback_block: str = ""
    creative_brief_block: str = ""


class ScenarioAgent(BaseAgent):
    """Agent 1 — Scénariste : crée la structure narrative complète."""

    name = "scenario_agent"

    async def run(self, ctx: "PipelineContext") -> Scenario:  # type: ignore[override]
        theme_prompt = ctx.channel.theme_prompt or ctx.niche_prompt or ""
        critic_feedback_block = _format_critic_feedback_block(ctx.critic_feedback)
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
            content_language=ctx.channel_config.content_language,
            min_diagram_duration_s=ctx.channel_config.visual_beats.min_diagram_duration_s,
            min_diagram_duration_short_s=ctx.channel_config.visual_beats.min_diagram_duration_short_s,
            content_plan_block=_format_content_plan_block(ctx.content_plan),
            research_block=_format_research_block(ctx.research_brief),
            research_rules_block=_format_research_rules_block(ctx.research_brief),
            critic_feedback_block=critic_feedback_block,
            creative_brief_block=_format_creative_brief_block(ctx.channel_config.creative_brief),
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
            vb_ctx = _build_visual_beats_prompt_context(
                input_data.editorial_tone,
                input_data.theme_category,
                content_language=input_data.content_language,
                min_diagram_duration_long=input_data.min_diagram_duration_s,
                min_diagram_duration_short=input_data.min_diagram_duration_short_s,
                is_short=True,
            )
            prompt = USER_PROMPT_SHORT.format(
                duration_s=input_data.target_duration_seconds,
                segment_duration=segment_duration,
                channel_name=input_data.channel_name,
                theme_category=input_data.theme_category,
                theme_prompt=input_data.theme_prompt or input_data.niche_prompt,
                niche_prompt=input_data.niche_prompt or "Contenu court vertical",
                editorial_tone=input_data.editorial_tone,
                creative_brief_block=input_data.creative_brief_block,
                theme=input_data.theme,
                content_plan_block=input_data.content_plan_block,
                research_block=input_data.research_block,
                research_rules_block=input_data.research_rules_block,
                learning_block=learning_block,
                critic_feedback_block=input_data.critic_feedback_block,
                sources_block=AVAILABLE_SOURCES,
                **vb_ctx,
            )
            system = SYSTEM_PROMPT_SHORT
            if "humor" in input_data.editorial_tone.lower() or "humour" in input_data.editorial_tone.lower():
                system += "\nPriorise l'humour, le second degré et les formats sans voix quand le visuel suffit."
        else:
            duration_min = max(1, input_data.target_duration_seconds // 60)
            vb_ctx = _build_visual_beats_prompt_context(
                input_data.editorial_tone,
                input_data.theme_category,
                min_beats_short=5,
                content_language=input_data.content_language,
                min_diagram_duration_long=input_data.min_diagram_duration_s,
                min_diagram_duration_short=input_data.min_diagram_duration_short_s,
                is_short=False,
            )
            prompt = USER_PROMPT_LONG.format(
                duration_min=duration_min,
                channel_name=input_data.channel_name,
                theme_category=input_data.theme_category,
                theme_prompt=input_data.theme_prompt or input_data.niche_prompt,
                niche_prompt=input_data.niche_prompt or "Vidéo éducative française",
                editorial_tone=input_data.editorial_tone,
                creative_brief_block=input_data.creative_brief_block,
                theme=input_data.theme,
                content_plan_block=input_data.content_plan_block,
                research_block=input_data.research_block,
                research_rules_block=input_data.research_rules_block,
                learning_block=learning_block,
                critic_feedback_block=input_data.critic_feedback_block,
                sources_block=AVAILABLE_SOURCES,
                **vb_ctx,
            )
            system = SYSTEM_PROMPT_LONG

        raw = await self._call_claude(prompt, system=system, max_tokens=8192)
        data = self._parse_json(raw)

        from agent.skills.media.validation_brief import (
            apply_brief_to_scenario_data,
            build_validation_brief,
        )

        brief = await build_validation_brief(
            theme=input_data.theme,
            theme_category=input_data.theme_category,
            segments=data.get("segments", []),
            creative_brief=input_data.creative_brief_block.replace(
                "BRIEF CRÉATIF DE LA CHAÎNE :\n", ""
            ).strip(),
        )
        data = apply_brief_to_scenario_data(data, brief)

        from agent.core.channel_config import VisualBeatsConfig
        from agent.skills.media.segment_beats_media import ensure_visual_beats_on_segments

        vb_config = VisualBeatsConfig(
            min_diagram_duration_s=input_data.min_diagram_duration_s,
            min_diagram_duration_short_s=input_data.min_diagram_duration_short_s,
        )
        data["segments"] = ensure_visual_beats_on_segments(
            data.get("segments", []),
            is_short=is_short,
            min_beats=3 if is_short else 5,
            max_beats=8,
            editorial_tone=input_data.editorial_tone,
            theme_category=input_data.theme_category,
            vb_config=vb_config,
        )

        async with AsyncSessionFactory() as session:
            scenario = Scenario(
                project_id=input_data.project_id,
                segments=data.get("segments", []),
                total_duration_s=data.get("total_duration_s", input_data.target_duration_seconds),
                iteration=1,
            )
            session.add(scenario)

            from agent.core.database import Project
            from sqlalchemy import select, update

            project_result = await session.execute(
                select(Project).where(Project.id == input_data.project_id)
            )
            project = project_result.scalar_one_or_none()
            project_config = dict(project.config or {}) if project else {}
            project_config["media_validation_brief"] = brief.to_dict()

            await session.execute(
                update(Project)
                .where(Project.id == input_data.project_id)
                .values(title=data.get("title"), config=project_config)
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
