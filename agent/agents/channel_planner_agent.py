from __future__ import annotations

import json
import logging
import re
from typing import Any

from agent.core.base_agent import BaseAgent
from agent.core.channel_brand import (
    ChannelBrandKit,
    InstagramBrand,
    ThemeVariant,
    TikTokBrand,
    YouTubeBrand,
)
from agent.core.config import load_agent_config
from agent.core.market_research_models import (
    CompetitorProfile,
    MarketAnalysisReport,
    NicheOpportunity,
    PlatformInsight,
    RecommendedTheme,
)
from agent.skills.market_research.youtube_discovery import YouTubeAuthError, discover_youtube_landscape

logger = logging.getLogger(__name__)

SUGGEST_SYSTEM = """Tu es un stratège de chaînes YouTube/TikTok/Instagram spécialisé en niches virales.
Tu proposes des angles éditoriaux DISTINCTS pour une même idée de contenu.
Tu retournes UNIQUEMENT du JSON valide."""

SUGGEST_PROMPT = """L'utilisateur veut créer une ou plusieurs chaînes vidéo autour de cette idée :

"{user_prompt}"
{market_block}

Propose entre 3 et 5 variantes de niche DIFFÉRENTES (ex. bébés animaux seuls / animaux mignons en général / duos parent-bébé).
Chaque variante doit maximiser la différenciation face à la concurrence identifiée.

Retourne UNIQUEMENT ce JSON :
{{
  "variants": [
    {{
      "content_angle": "Description courte de l'angle (1 phrase)",
      "slug": "identifiant-url-court",
      "name": "Nom affiché de la chaîne",
      "theme_category": "nature|animaux|science|art|histoire|default",
      "niche_prompt": "Instructions éditoriales pour le pipeline vidéo (2-3 phrases)",
      "suggested_tags": ["#tag1", "#tag2"]
    }}
  ]
}}"""

MARKET_SYSTEM = """Tu es un analyste marché pour créateurs vidéo éducatives (YouTube, TikTok, Instagram) en français.
Tu combines des données YouTube réelles (fournies) avec ton expertise des dynamiques TikTok/Reels.
Tu évalues la concurrence, la saturation, et la faisabilité de se démarquer.
Tu retournes UNIQUEMENT du JSON valide conforme au schéma demandé.
Sois factuel pour YouTube (données API) ; pour TikTok/Instagram indique data_source model_estimate."""

MARKET_PROMPT = """Analyse de marché demandée par l'utilisateur.

## Idée / intention
{user_prompt}

## Plateformes à couvrir
{platforms_json}

## Région et langue cible
Région : {region} | Langue : {language}

## Données YouTube collectées (API live — à prioriser)
{youtube_data_json}

## Consignes
1. Synthétise le marché : qui domine, formats gagnants, saturation.
2. Analyse la concurrence : forces/faiblesses des chaînes listées + archétypes implicites TikTok/IG.
3. Évalue si l'utilisateur a une **chance réelle de se démarquer** (differentiation_verdict).
4. Propose 3 à 5 niches/thèmes avec scores de différenciation et risques.
5. Liste ce qu'il faut éviter (angles saturés, erreurs courantes).

Retourne UNIQUEMENT ce JSON :
{{
  "market_summary": "Synthèse 150-250 mots",
  "saturation_verdict": "favorable | nuanced | crowded",
  "differentiation_verdict": "Verdict clair : pourquoi oui/non se démarquer",
  "platforms_analyzed": ["youtube", "tiktok", "instagram"],
  "platform_insights": [
    {{
      "platform": "youtube",
      "trend_summary": "...",
      "winning_formats": ["..."],
      "audience_signals": ["..."],
      "hashtag_or_keyword_hints": ["..."],
      "data_source": "live_api"
    }},
    {{
      "platform": "tiktok",
      "trend_summary": "...",
      "winning_formats": ["..."],
      "audience_signals": ["..."],
      "hashtag_or_keyword_hints": ["..."],
      "data_source": "model_estimate"
    }}
  ],
  "top_competitors": [
    {{
      "platform": "youtube",
      "name": "Nom chaîne",
      "handle_or_url": "@handle ou URL",
      "subscriber_count": 100000,
      "video_count": 200,
      "positioning": "Positionnement en 1 phrase",
      "strengths": ["..."],
      "weaknesses": ["..."],
      "content_formats": ["long", "shorts"]
    }}
  ],
  "niche_opportunities": [
    {{
      "niche_name": "...",
      "potential_score": 75,
      "competition_level": "low|medium|high",
      "rationale": "...",
      "differentiation_angle": "Angle pour se distinguer"
    }}
  ],
  "recommended_themes": [
    {{
      "content_angle": "...",
      "slug": "slug-court",
      "name": "Nom chaîne",
      "theme_category": "histoire|science|nature|animaux|art|default",
      "niche_prompt": "Instructions pipeline 2-3 phrases",
      "suggested_tags": ["#tag"],
      "differentiation_score": 80,
      "competition_level": "low|medium|high",
      "why_you_can_win": "Pourquoi cet angle est défendable",
      "risks": ["risque 1"]
    }}
  ],
  "avoid": ["angle saturé à éviter"],
  "next_steps": ["action concrète 1", "action 2"]
}}"""

BRAND_SYSTEM = """Tu es un expert branding pour créateurs YouTube, TikTok et Instagram en français.
Tu génères des kits de marque cohérents et optimisés SEO.
JSON valide uniquement."""

BRAND_PROMPT = """Génère un kit de marque complet pour cette variante de chaîne :

Angle : {content_angle}
Nom : {name}
Catégorie : {theme_category}
Niche pipeline : {niche_prompt}
Slug : {slug}
Tags : {tags}
{market_hint}

Retourne UNIQUEMENT ce JSON :
{{
  "slug": "{slug}",
  "name": "{name}",
  "theme_category": "{theme_category}",
  "niche_prompt": "{niche_prompt}",
  "content_angle": "{content_angle}",
  "youtube": {{
    "title": "Titre chaîne YouTube (max 100 car.)",
    "description": "Description chaîne (max 1000 car., SEO, appels à l'abonnement)",
    "keywords": ["mot-clé1", "mot-clé2"],
    "handle_suggestion": "@HandleSuggere"
  }},
  "tiktok": {{
    "display_name": "Nom TikTok",
    "bio": "Bio TikTok (max 80 car.)",
    "default_caption_style": "Style de légendes courts (ex. question + emoji)"
  }},
  "instagram": {{
    "page_name": "Nom page Instagram",
    "bio": "Bio Instagram (max 150 car.)"
  }},
  "default_tags": ["#tag1", "#tag2"],
  "media_source_priority": ["unsplash", "pexels", "wikimedia"],
  "sample_video_titles": ["Titre vidéo 1", "Titre vidéo 2", "Titre vidéo 3"]
}}"""


class ChannelPlannerAgent(BaseAgent):
    """Suggère des niches, analyse le marché et génère le kit de marque pour une nouvelle chaîne."""

    name = "channel_planner_agent"

    async def run(self, input_data: str) -> list[ThemeVariant]:
        return await self.suggest_theme_variants(input_data)

    async def analyze_market(
        self,
        user_prompt: str,
        *,
        platforms: list[str] | None = None,
        region: str = "FR",
        language: str = "fr",
        youtube_refresh_token: str | None = None,
    ) -> MarketAnalysisReport:
        """Analyse marché multi-plateformes avec données YouTube live + synthèse IA."""
        cfg = load_agent_config().get("onboarding", {}).get("market_research", {})
        platforms = platforms or list(cfg.get("platforms", ["youtube", "tiktok", "instagram"]))
        region = region or str(cfg.get("region", "FR"))
        language = language or str(cfg.get("language", "fr"))

        youtube_data: dict[str, Any] = {"note": "YouTube non demandé ou indisponible"}
        if "youtube" in platforms:
            try:
                youtube_data = await discover_youtube_landscape(
                    user_prompt,
                    refresh_token=youtube_refresh_token,
                    max_channels=int(cfg.get("max_youtube_channels", 10)),
                    max_videos=int(cfg.get("max_youtube_videos", 15)),
                    region_code=region,
                    relevance_language=language,
                )
            except YouTubeAuthError:
                raise
            except Exception as e:
                logger.warning("Collecte YouTube marché échouée : %s", e)
                youtube_data = {"error": str(e), "channels": [], "top_videos": []}

        prompt = MARKET_PROMPT.format(
            user_prompt=user_prompt.replace('"', "'"),
            platforms_json=json.dumps(platforms, ensure_ascii=False),
            region=region,
            language=language,
            youtube_data_json=json.dumps(youtube_data, ensure_ascii=False, indent=2),
        )
        raw = await self._call_claude(
            prompt,
            system=MARKET_SYSTEM,
            model=None,
            max_tokens=int(cfg.get("max_tokens", 8192)),
            cacheable_context=f"Analyse marché créateurs FR — région {region}",
        )
        data = _parse_json(raw)
        return _build_market_report(user_prompt, platforms, data)

    async def suggest_theme_variants(
        self,
        user_prompt: str,
        *,
        market_context: str | None = None,
    ) -> list[ThemeVariant]:
        market_block = ""
        if market_context and market_context.strip():
            market_block = (
                f"\n\nContexte analyse de marché (à respecter pour la différenciation) :\n"
                f"{market_context.strip()[:3000]}\n"
            )
        prompt = SUGGEST_PROMPT.format(
            user_prompt=user_prompt.replace('"', "'"),
            market_block=market_block,
        )
        raw = await self._call_claude(prompt, system=SUGGEST_SYSTEM, max_tokens=4096)
        data = _parse_json(raw)
        variants = []
        for item in data.get("variants", []):
            slug = _slugify(str(item.get("slug", "channel")))
            variants.append(
                ThemeVariant(
                    content_angle=str(item.get("content_angle", "")),
                    slug=slug,
                    name=str(item.get("name", slug)),
                    theme_category=str(item.get("theme_category", "default")),
                    niche_prompt=str(item.get("niche_prompt", user_prompt)),
                    suggested_tags=[str(t) for t in item.get("suggested_tags", [])],
                )
            )
        if not variants:
            raise ValueError("Aucune variante générée par l'IA")
        return variants

    def themes_from_market_report(self, report: MarketAnalysisReport) -> list[ThemeVariant]:
        """Convertit les thèmes recommandés de l'analyse marché en variantes onboarding."""
        return [
            ThemeVariant(
                content_angle=t.content_angle,
                slug=t.slug,
                name=t.name,
                theme_category=t.theme_category,
                niche_prompt=t.niche_prompt,
                suggested_tags=t.suggested_tags,
            )
            for t in report.recommended_themes
        ]

    async def generate_brand_kit(
        self,
        variant: ThemeVariant,
        *,
        market_hint: str | None = None,
    ) -> ChannelBrandKit:
        hint_block = ""
        if market_hint and market_hint.strip():
            hint_block = f"\nContexte marché (différenciation) : {market_hint.strip()[:1500]}"
        prompt = BRAND_PROMPT.format(
            content_angle=variant.content_angle,
            name=variant.name,
            theme_category=variant.theme_category,
            niche_prompt=variant.niche_prompt,
            slug=variant.slug,
            tags=", ".join(variant.suggested_tags),
            market_hint=hint_block,
        )
        raw = await self._call_claude(prompt, system=BRAND_SYSTEM, max_tokens=4096)
        data = _parse_json(raw)
        return ChannelBrandKit(
            slug=str(data.get("slug", variant.slug)),
            name=str(data.get("name", variant.name)),
            theme_category=str(data.get("theme_category", variant.theme_category)),
            niche_prompt=str(data.get("niche_prompt", variant.niche_prompt)),
            content_angle=str(data.get("content_angle", variant.content_angle)),
            youtube=YouTubeBrand(**data.get("youtube", {})),
            tiktok=TikTokBrand(**data.get("tiktok", {})),
            instagram=InstagramBrand(**data.get("instagram", {})),
            default_tags=[str(t) for t in data.get("default_tags", variant.suggested_tags)],
            media_source_priority=data.get("media_source_priority"),
            sample_video_titles=[str(t) for t in data.get("sample_video_titles", [])],
        )


def _build_market_report(
    user_prompt: str,
    platforms: list[str],
    data: dict[str, Any],
) -> MarketAnalysisReport:
    competitors = [
        CompetitorProfile(
            platform=str(c.get("platform", "youtube")),
            name=str(c.get("name", "")),
            handle_or_url=str(c.get("handle_or_url", "")),
            subscriber_count=c.get("subscriber_count"),
            video_count=c.get("video_count"),
            positioning=str(c.get("positioning", "")),
            strengths=[str(s) for s in c.get("strengths", [])],
            weaknesses=[str(w) for w in c.get("weaknesses", [])],
            content_formats=[str(f) for f in c.get("content_formats", [])],
        )
        for c in data.get("top_competitors", [])
        if isinstance(c, dict)
    ]

    platform_insights = [
        PlatformInsight(
            platform=str(p.get("platform", "")),
            trend_summary=str(p.get("trend_summary", "")),
            winning_formats=[str(f) for f in p.get("winning_formats", [])],
            audience_signals=[str(a) for a in p.get("audience_signals", [])],
            hashtag_or_keyword_hints=[str(h) for h in p.get("hashtag_or_keyword_hints", [])],
            data_source=str(p.get("data_source", "model_estimate")),
        )
        for p in data.get("platform_insights", [])
        if isinstance(p, dict)
    ]

    opportunities = [
        NicheOpportunity(
            niche_name=str(n.get("niche_name", "")),
            potential_score=int(n.get("potential_score", 50)),
            competition_level=str(n.get("competition_level", "medium")),
            rationale=str(n.get("rationale", "")),
            differentiation_angle=str(n.get("differentiation_angle", "")),
        )
        for n in data.get("niche_opportunities", [])
        if isinstance(n, dict)
    ]

    themes = []
    for t in data.get("recommended_themes", []):
        if not isinstance(t, dict):
            continue
        themes.append(
            RecommendedTheme(
                content_angle=str(t.get("content_angle", "")),
                slug=_slugify(str(t.get("slug", "channel"))),
                name=str(t.get("name", "")),
                theme_category=str(t.get("theme_category", "default")),
                niche_prompt=str(t.get("niche_prompt", "")),
                suggested_tags=[str(tag) for tag in t.get("suggested_tags", [])],
                differentiation_score=int(t.get("differentiation_score", 50)),
                competition_level=str(t.get("competition_level", "medium")),
                why_you_can_win=str(t.get("why_you_can_win", "")),
                risks=[str(r) for r in t.get("risks", [])],
            )
        )

    return MarketAnalysisReport(
        user_prompt=user_prompt,
        market_summary=str(data.get("market_summary", "")),
        saturation_verdict=str(data.get("saturation_verdict", "nuanced")),
        differentiation_verdict=str(data.get("differentiation_verdict", "")),
        platforms_analyzed=list(data.get("platforms_analyzed", platforms)),
        platform_insights=platform_insights,
        top_competitors=competitors,
        niche_opportunities=opportunities,
        recommended_themes=themes,
        avoid=[str(a) for a in data.get("avoid", [])],
        next_steps=[str(s) for s in data.get("next_steps", [])],
    )


def _slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:48] or "channel"


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    # Extract content from the first ```[json]...``` block
    m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", text)
    if m:
        candidate = m.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    # Fallback: find the outermost balanced { ... }
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
    return json.loads(text)
