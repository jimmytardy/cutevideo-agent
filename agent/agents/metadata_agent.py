from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Project, Scenario

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

METADATA_SYSTEM = """Tu es expert SEO YouTube. Tu écris des titres à fort taux de clic et des
descriptions optimisées pour le référencement, fidèles au contenu. Tu réponds UNIQUEMENT en JSON valide."""

METADATA_PROMPT_SHORT = """Rédige les métadonnées de publication de ce SHORT vertical (9:16).

CHAÎNE : {channel_name} ({theme_category})
SUJET : {theme}
LANGUE : {language}
FORMAT ÉDITORIAL : {editorial_format}
ANGLE ÉDITORIAL : {authorship_thesis}
FORMAT : YouTube Short / TikTok / Reels
{research_block}
STRUCTURE (segments) :
{scenario_summary}

Retourne UNIQUEMENT :
{{
  "title": "Titre accrocheur pour short, max 70 caractères",
  "description": "Description courte 1-2 phrases avec #Shorts si pertinent",
  "tags": ["shorts", "tag2", "..."]
}}"""

METADATA_PROMPT = """Rédige les métadonnées de publication de cette vidéo.

CHAÎNE : {channel_name} ({theme_category})
SUJET : {theme}
LANGUE : {language}
FORMAT ÉDITORIAL : {editorial_format}
ANGLE ÉDITORIAL : {authorship_thesis}
{research_block}
STRUCTURE (segments) :
{scenario_summary}

Retourne UNIQUEMENT :
{{
  "title": "Titre YouTube accrocheur, max 70 caractères, sans clickbait mensonger",
  "description": "Description SEO 2-4 phrases (max 480 caractères) résumant la vidéo et donnant envie, mots-clés naturels",
  "tags": ["tag1", "tag2", "..."]
}}

Règles :
- title : promesse claire + curiosité ; intègre l'entité/sujet principal ; en {language}
- description : pas de timestamps (ajoutés automatiquement) ; phrases complètes ; mots-clés du sujet
- tags : 8 à 15 mots-clés pertinents (sans #), du plus spécifique au plus général, en {language}"""


def build_chapters(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chapitres YouTube (timestamp cumulé + titre de segment) à partir des durées."""
    chapters: list[dict[str, Any]] = []
    cursor = 0.0
    for seg in segments:
        title = str(seg.get("title") or "").strip()
        if title:
            chapters.append({"start_s": int(cursor), "title": title})
        cursor += float(seg.get("duration_s") or 0)
    return chapters


def format_chapters_block(chapters: list[dict[str, Any]]) -> str:
    if len(chapters) < 3:
        return ""
    lines = ["Chapitres :"]
    for ch in chapters:
        total = int(ch["start_s"])
        mm, ss = divmod(total, 60)
        hh, mm = divmod(mm, 60)
        ts = f"{hh:d}:{mm:02d}:{ss:02d}" if hh else f"{mm:d}:{ss:02d}"
        lines.append(f"{ts} {ch['title']}")
    return "\n".join(lines)


class MetadataAgent(BaseAgent):
    """Produit titre/description SEO + tags + chapitres après validation du scénario.

    Décharge le ScenarioAgent de la responsabilité métadonnées (prompt plus focalisé)
    et améliore le CTR / référencement.
    """

    name = "metadata_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> dict[str, Any]:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id,
            {"scenario_id": str(scenario.id)},
            iteration=ctx.iteration,
        )
        try:
            metadata = await self._build(ctx, scenario)
            await self._persist(ctx.project_id, metadata)
            await self.end_run(run, {"title": metadata.get("title", "")})
            logger.info("Métadonnées : %s", metadata.get("title", ""))
            return metadata
        except Exception as exc:
            await self.fail_run(run, exc)
            raise

    async def _build(self, ctx: "PipelineContext", scenario: Scenario) -> dict[str, Any]:
        from agent.agents.scenario_agent import _format_research_block

        segments = list(scenario.segments or [])
        chapters = build_chapters(segments)
        scenario_summary = "\n".join(
            f"- {s.get('title', '')} ({int(s.get('duration_s') or 0)}s)" for s in segments[:12]
        )
        editorial_format = ""
        authorship_thesis = ""
        async with AsyncSessionFactory() as session:
            project = await session.get(Project, ctx.project_id)
            if project and isinstance(project.config, dict):
                plan = project.config.get("content_plan") or {}
                editorial_format = str(plan.get("narrative_format") or plan.get("editorial_format_id") or "")
                angle = project.config.get("authorship_angle") or {}
                if isinstance(angle, dict):
                    authorship_thesis = str(angle.get("thesis") or "")
        prompt_template = METADATA_PROMPT_SHORT if ctx.is_short_project else METADATA_PROMPT
        prompt = prompt_template.format(
            channel_name=ctx.channel.name,
            theme_category=ctx.theme_category,
            theme=ctx.theme,
            language=ctx.channel_config.content_language,
            editorial_format=editorial_format or ctx.theme_category,
            authorship_thesis=authorship_thesis or ctx.theme,
            research_block=_format_research_block(ctx.research_brief),
            scenario_summary=scenario_summary,
        )
        title = (segments[0].get("title") if segments else None) or ctx.theme
        description = ctx.theme
        tags = list(ctx.channel_config.default_tags or [])
        if ctx.is_short_project and "shorts" not in [t.lower() for t in tags]:
            tags = ["shorts", *tags]
        try:
            raw = await self._call_claude(prompt, system=METADATA_SYSTEM, max_tokens=2048)
            data = self._parse_json(raw)
            title = str(data.get("title") or title)[:100]
            description = str(data.get("description") or description)[:480]
            llm_tags = [str(t).lstrip("#").strip() for t in (data.get("tags") or []) if str(t).strip()]
            if llm_tags:
                tags = llm_tags
        except Exception as exc:
            logger.warning("Metadata LLM indisponible — valeurs de repli : %s", exc)

        chapters_block = format_chapters_block(chapters)
        full_description = f"{description}\n\n{chapters_block}".strip() if chapters_block else description

        return {
            "title": title,
            "description": full_description,
            "tags": tags,
            "chapters": chapters,
        }

    @staticmethod
    async def _persist(project_id: object, metadata: dict[str, Any]) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                raise RuntimeError(f"Projet {project_id} introuvable")
            config = dict(project.config or {})
            config["youtube_metadata"] = metadata
            await session.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(config=config, title=metadata.get("title") or project.title)
            )
            await session.commit()

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
