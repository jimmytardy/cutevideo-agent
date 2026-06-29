from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select, update

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Project, Scenario

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

ART_DIRECTOR_SYSTEM = """Tu es directeur artistique d'une chaîne vidéo.
Tu définis UNE direction visuelle cohérente, réutilisée à l'identique sur TOUS les plans d'une
vidéo, pour éviter l'effet « patchwork » entre images générées. Tu réponds UNIQUEMENT en JSON valide."""

ART_DIRECTOR_PROMPT = """Définis la direction artistique visuelle de cette vidéo.

CHAÎNE : {channel_name} ({theme_category})
TON ÉDITORIAL : {editorial_tone}
SUJET : {theme}
{creative_brief_block}
Retourne UNIQUEMENT :
{{"style_block": "..."}}

Le style_block :
- en ANGLAIS, une seule phrase compacte (max 220 caractères)
- décrit UNIQUEMENT le rendu transversal : palette de couleurs, ambiance lumineuse,
  type de rendu (photoréaliste / illustré / archive), grain/époque, niveau de contraste
- NE décrit AUCUN sujet précis (ni lieu, ni personne, ni objet) — le sujet est ajouté par plan
- cohérent avec le ton et la catégorie de la chaîne
- pas de mots-clés de texte/typographie (les schémas restent sans texte)

Exemple : "cohesive cinematic documentary look, warm earthy palette, soft natural lighting, gentle film grain, muted contrast"
"""

# Direction visuelle par défaut si le LLM échoue — garantit un style cohérent sans casser le pipeline.
_FALLBACK_STYLE_BY_CATEGORY: dict[str, str] = {
    "science": "cohesive clean scientific look, cool blue and teal palette, crisp high-contrast lighting, sharp modern clarity",
    "espace": "cohesive cosmic look, deep blue and black palette, dramatic rim lighting, ultra-crisp high contrast",
    "histoire": "cohesive archival documentary look, warm sepia and amber palette, soft directional lighting, fine film grain",
    "art": "cohesive fine-art look, rich warm palette, soft gallery lighting, painterly texture, gentle contrast",
    "nature": "cohesive nature documentary look, lush green and earthy palette, golden hour lighting, high dynamic range",
    "sport": "cohesive dynamic sports look, vivid saturated palette, bright stadium lighting, crisp motion-frozen detail",
    "true_crime": "cohesive noir documentary look, desaturated cold palette, low-key chiaroscuro lighting, tense moody contrast",
    "politique": "cohesive photojournalistic look, neutral balanced palette, natural daylight, realistic documentary contrast",
    "actualite": "cohesive photojournalistic look, neutral balanced palette, natural daylight, realistic documentary contrast",
    "tech": "cohesive modern tech look, clean minimal palette, soft studio lighting, sharp product clarity",
    "finance": "cohesive modern editorial look, cool neutral palette, soft studio lighting, crisp clean detail",
    "humour": "cohesive playful look, bright vivid palette, high-key lighting, bold cheerful contrast",
}
_FALLBACK_STYLE_DEFAULT = (
    "cohesive cinematic documentary look, natural balanced palette, soft natural lighting, "
    "gentle film grain, muted contrast"
)

MAX_STYLE_BLOCK_CHARS = 240


def fallback_style_block(theme_category: str) -> str:
    cat = (theme_category or "").lower()
    for key, style in _FALLBACK_STYLE_BY_CATEGORY.items():
        if key in cat:
            return style
    return _FALLBACK_STYLE_DEFAULT


class ArtDirectorAgent(BaseAgent):
    """Définit un *style block* visuel unique, injecté dans tous les prompts d'image.

    Réduit la dérive de style entre plans (cf. bonnes pratiques cohérence vidéo IA).
    """

    name = "art_director_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> str:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id,
            {"scenario_id": str(scenario.id)},
            iteration=ctx.iteration,
        )
        try:
            style_block = await self._direct(ctx)
            await self._persist(ctx.project_id, style_block)
            await self.end_run(run, {"style_block": style_block})
            logger.info("Direction artistique : %s", style_block)
            return style_block
        except Exception as exc:
            await self.fail_run(run, exc)
            raise

    async def _direct(self, ctx: "PipelineContext") -> str:
        brief = (ctx.channel_config.creative_brief or "").strip()
        creative_brief_block = f"BRIEF CRÉATIF :\n{brief}\n" if brief else ""
        palette_block = ""
        async with AsyncSessionFactory() as session:
            project = await session.get(Project, ctx.project_id)
            palette = (project.config or {}).get("visual_palette") if project else None
        if isinstance(palette, list) and palette:
            colors = ", ".join(str(c) for c in palette[:5])
            palette_block = f"PALETTE DOMINANTE IMPOSÉE : {colors}\n"
        prompt = ART_DIRECTOR_PROMPT.format(
            channel_name=ctx.channel.name,
            theme_category=ctx.theme_category,
            editorial_tone=ctx.channel_config.editorial_tone,
            theme=ctx.theme,
            creative_brief_block=creative_brief_block + palette_block,
        )
        try:
            raw = await self._call_claude(prompt, system=ART_DIRECTOR_SYSTEM, max_tokens=512)
            data = self._parse_json(raw)
            style = str(data.get("style_block") or "").strip()
        except Exception as exc:
            logger.warning("Art director LLM indisponible — style par défaut : %s", exc)
            style = ""
        if not style:
            style = fallback_style_block(ctx.theme_category)
        return style[:MAX_STYLE_BLOCK_CHARS]

    @staticmethod
    async def _persist(project_id: object, style_block: str) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                raise RuntimeError(f"Projet {project_id} introuvable")
            config = dict(project.config or {})
            config["visual_style_block"] = style_block
            palette = config.get("visual_palette")
            if isinstance(palette, list):
                config["visual_palette"] = palette
            await session.execute(
                update(Project).where(Project.id == project_id).values(config=config)
            )
            await session.commit()

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
