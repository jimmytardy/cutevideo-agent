from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.channel_config import resolve_channel_config
from agent.core.config import load_agent_config
from agent.core.content_plan_models import DailyContentPlan, ThemeAnalysis, VideoTopicPlan
from agent.core.database import AsyncSessionFactory, Channel, Project
from agent.core.learning_context import load_channel_context
from agent.core.llm_config import compact_learning_context, is_planner_llm_day
from agent.skills.content_planning.heuristic_planner import build_heuristic_plan, find_similar_in_history
from agent.scheduler.content_planning import (
    build_editorial_identity,
    count_planner_projects_for_publish_date,
    load_topic_history,
    production_quotas,
)
from agent.scheduler.editorial_calendar import production_day, publication_target_day

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """Tu es un directeur éditorial IA pour chaînes vidéo éducatives YouTube/TikTok/Instagram.
Tu choisis les SUJETS et formats (long vs court) — tu ne rédiges pas le script, ne montes pas, ne publies pas.
Tu retournes UNIQUEMENT du JSON valide conforme au schéma demandé."""

PLANNER_PROMPT = """Date de production (aujourd'hui) : {production_date}
Date de publication cible (lendemain) : {target_publish_date}
Chaîne : {channel_name} (slug {channel_slug})
Catégorie thématique : {theme_category}

## Identité éditoriale (à respecter strictement)
Thème / promesse chaîne : {theme_prompt}
Niche pipeline : {niche_prompt}
Angle différenciateur : {content_angle}
Public cible : {target_audience}
Ton : {tone}
Différenciation : {differentiator}

## Production du jour (vidéos à fabriquer aujourd'hui pour publication demain)
Vidéos longues à produire : {long_count}
Shorts à produire (découpés des longs du jour) : {short_count}
Les publications plateforme sont programmées pour le {target_publish_date} uniquement.
Durée cible longue (s) : {default_long_duration_s}
Durée cible short (s) : {default_short_duration_s}

## Fraîcheur
Ne pas répéter un sujet traité depuis moins de {freshness_days} jours.
Sujets intemporels de secours pour ce thème : {evergreen_topics_json}

## Historique des sujets déjà produits
{history_json}

## Contexte performance (analytics + commentaires)
{learning_context}

## Consignes de réflexion (intègre dans theme_analysis et selection_rationale)
1. Extraire sous-thèmes, formats narratifs pertinents, figures/objets centraux, critères de "bon sujet" pour CE thème.
2. Équilibrer la diversité des sous-thèmes sur la période récente.
3. Pondérer SEO, actualité/anniversaires liés au thème, ratio notoriété/originalité.
4. Long = profondeur ; short = hook autonome (45–90 s) — indiquer parent_long_index (0-based) pour shorts dérivés d'un long du jour.
5. Si actualité forte sur le thème : au plus 1 sujet réactif (reactive_news_hook).

Retourne UNIQUEMENT ce JSON :
{{
  "theme_analysis": {{
    "sub_themes": ["..."],
    "narrative_formats": ["..."],
    "central_figures": ["..."],
    "good_subject_criteria": ["..."]
  }},
  "selection_rationale": "Pourquoi ces choix aujourd'hui (max 300 mots)",
  "evergreen_fallback_used": false,
  "long_videos": [
    {{
      "priority": 1,
      "format": "long",
      "provisional_title": "...",
      "angle": "2 lignes max",
      "narrative_format": "récit|portrait|...",
      "estimated_duration_s": {default_long_duration_s},
      "sub_theme": "...",
      "main_entities": ["personne", "lieu", "..."],
      "seo_keywords": ["..."],
      "subject": "Sujet précis pour le scénariste (phrase complète)",
      "parent_long_index": null,
      "reactive_news_hook": null
    }}
  ],
  "short_videos": [
    {{
      "priority": 1,
      "format": "short_derived",
      "provisional_title": "...",
      "angle": "...",
      "narrative_format": "...",
      "estimated_duration_s": {default_short_duration_s},
      "sub_theme": "...",
      "main_entities": [],
      "seo_keywords": [],
      "subject": "Angle du short",
      "parent_long_index": 0,
      "reactive_news_hook": null
    }}
  ]
}}

Règles strictes :
- Exactement {long_count} entrées dans long_videos
- Exactement {short_count} entrées dans short_videos
- Chaque short_derived doit référencer un parent_long_index valide (< {long_count}) si long_count > 0
- En mode shorts_only (long_count=0) : shorts autonomes, parent_long_index=null, format short_standalone
- Voix/narration : recommandée sur shorts éducatifs (needs_voice true) ; optionnelle pour formats purement visuels
- Musique (needs_music) : optionnelle — false si voix seule ou son ambiant suffisent
- Aucune répétition sémantique avec l'historique
- subject = formulation claire pour alimenter le scénariste (pas le titre YouTube seul)"""


class ContentPlannerAgent(BaseAgent):
    """Agent planificateur — choisit les sujets longs/courts du jour à partir des quotas distribution."""

    name = "content_planner_agent"

    async def run(self, input_data: None = None) -> dict[str, Any]:  # type: ignore[override]
        return await self.run_scheduled()

    async def run_scheduled(self, *, plan_date: date | None = None) -> dict[str, Any]:
        prod_day = plan_date or production_day()
        target_day = publication_target_day()
        created_projects = 0
        skipped_channels = 0
        errors = 0

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Channel).where(Channel.is_active == True)  # noqa: E712
            )
            channels = list(result.scalars().all())

        for channel in channels:
            cfg = resolve_channel_config(channel)
            try:
                n = await self._plan_channel(channel, cfg, prod_day, target_day)
                if n == 0:
                    skipped_channels += 1
                else:
                    created_projects += n
            except Exception as e:
                errors += 1
                logger.error("Content planner échoué pour %s : %s", channel.slug, e)

        summary = {
            "production_date": prod_day.isoformat(),
            "target_publish_date": target_day.isoformat(),
            "projects_created": created_projects,
            "channels_skipped": skipped_channels,
            "errors": errors,
        }
        logger.info("Content planner terminé : %s", summary)
        return summary

    async def run_for_channel(
        self,
        channel_id: uuid.UUID,
        *,
        plan_date: date | None = None,
        force: bool = False,
    ) -> DailyContentPlan | None:
        prod_day = plan_date or production_day()
        target_day = publication_target_day()
        async with AsyncSessionFactory() as session:
            channel = await session.get(Channel, channel_id)
        if not channel:
            raise ValueError(f"Chaîne {channel_id} introuvable")
        cfg = resolve_channel_config(channel)
        if not force and await count_planner_projects_for_publish_date(channel.id, target_day) > 0:
            raise ValueError(
                f"Un plan existe déjà pour publication le {target_day.isoformat()}"
            )
        plan = await self._generate_plan(channel, cfg, prod_day, target_day)
        await self._persist_plan(channel, plan, target_day, prod_day)
        return plan

    async def _generate_plan(
        self,
        channel: Channel,
        cfg: Any,
        production_date: date,
        target_publish_date: date,
    ) -> DailyContentPlan:
        if is_planner_llm_day(production_date):
            return await self._generate_plan_llm(
                channel, cfg, production_date, target_publish_date
            )
        return await self._generate_plan_heuristic(
            channel, cfg, production_date, target_publish_date
        )

    async def _generate_plan_heuristic(
        self,
        channel: Channel,
        cfg: Any,
        production_date: date,
        target_publish_date: date,
    ) -> DailyContentPlan:
        global_cfg = load_agent_config().get("content_planning", {})
        channel_cp = (channel.config or {}).get("content_planning", {})
        default_long_s = int(
            channel_cp.get(
                "default_long_duration_seconds",
                global_cfg.get("default_long_duration_seconds", 1800),
            )
        )
        default_short_s = int(
            channel_cp.get("default_short_duration_s", global_cfg.get("default_short_duration_s", 60))
        )
        evergreen = channel_cp.get("evergreen_topics") or global_cfg.get(
            "evergreen_by_theme", {}
        ).get(channel.theme_category, global_cfg.get("evergreen_default", []))

        long_count, short_count = production_quotas(cfg)
        history = await load_topic_history(channel.id)
        return build_heuristic_plan(
            channel,
            production_date=production_date,
            target_publish_date=target_publish_date,
            long_count=long_count,
            short_count=short_count,
            default_long_s=default_long_s,
            default_short_s=default_short_s,
            history=history,
            evergreen=list(evergreen),
        )

    async def _plan_channel(
        self,
        channel: Channel,
        cfg: Any,
        production_date: date,
        target_publish_date: date,
    ) -> int:
        if await count_planner_projects_for_publish_date(channel.id, target_publish_date) > 0:
            logger.info(
                "Plan déjà créé pour publication %s (%s) — skip",
                target_publish_date.isoformat(),
                channel.slug,
            )
            return 0

        long_count, short_count = production_quotas(cfg)
        if long_count <= 0 and short_count <= 0:
            return 0

        plan = await self._generate_plan(channel, cfg, production_date, target_publish_date)
        return await self._persist_plan(channel, plan, target_publish_date, production_date)

    async def _generate_plan_llm(
        self,
        channel: Channel,
        cfg: Any,
        production_date: date,
        target_publish_date: date,
    ) -> DailyContentPlan:
        global_cfg = load_agent_config().get("content_planning", {})
        channel_cp = (channel.config or {}).get("content_planning", {})
        freshness_days = int(channel_cp.get("freshness_days", global_cfg.get("freshness_days", 30)))
        default_long_s = int(
            channel_cp.get("default_long_duration_seconds", global_cfg.get("default_long_duration_seconds", 1800))
        )
        default_short_s = int(
            channel_cp.get("default_short_duration_s", global_cfg.get("default_short_duration_s", 60))
        )
        evergreen = channel_cp.get("evergreen_topics") or global_cfg.get(
            "evergreen_by_theme", {}
        ).get(channel.theme_category, global_cfg.get("evergreen_default", []))

        long_count, short_count = production_quotas(cfg)
        identity = build_editorial_identity(channel)
        history = await load_topic_history(channel.id)
        learning = await load_channel_context(channel.id)

        prompt = PLANNER_PROMPT.format(
            production_date=production_date.isoformat(),
            target_publish_date=target_publish_date.isoformat(),
            channel_name=identity["channel_name"],
            channel_slug=channel.slug,
            theme_category=identity["theme_category"],
            theme_prompt=identity["theme_prompt"] or identity["niche_prompt"],
            niche_prompt=identity["niche_prompt"],
            content_angle=identity["content_angle"],
            target_audience=identity["target_audience"],
            tone=identity["tone"],
            differentiator=identity["differentiator"],
            long_count=long_count,
            short_count=short_count,
            default_long_duration_s=default_long_s,
            default_short_duration_s=default_short_s,
            freshness_days=freshness_days,
            evergreen_topics_json=json.dumps(evergreen, ensure_ascii=False),
            history_json=json.dumps(history, ensure_ascii=False, indent=2),
            learning_context="(voir bloc contexte chaîne ci-dessus)",
        )

        raw = await self._call_claude_for_channel(
            channel.id,
            prompt,
            system=PLANNER_SYSTEM,
            extra_cacheable=compact_learning_context(learning),
        )
        data = self._parse_json(raw)
        plan = self._build_plan(
            channel,
            data,
            production_date,
            target_publish_date,
            long_count,
            short_count,
            default_long_s,
            default_short_s,
        )
        return self._dedup_plan_against_history(plan, history)

    async def _persist_plan(
        self,
        channel: Channel,
        plan: DailyContentPlan,
        target_publish_date: date,
        production_date: date | None = None,
    ) -> int:
        prod_iso = (production_date or production_day()).isoformat()
        cfg = resolve_channel_config(channel)
        created = 0
        async with AsyncSessionFactory() as session:
            if cfg.production_mode != "shorts_only":
                for idx, long_topic in enumerate(plan.long_videos):
                    shorts_for_long = [
                        s.model_dump()
                        for s in plan.short_videos
                        if s.parent_long_index == idx
                    ]
                    project = Project(
                        channel_id=channel.id,
                        theme=long_topic.subject,
                        title=long_topic.provisional_title,
                        target_duration_seconds=long_topic.estimated_duration_s,
                        status="pending",
                        config={
                            "source": "content_planner_agent",
                            "production_date": prod_iso,
                            "target_publish_date": target_publish_date.isoformat(),
                            "planned_date": plan.plan_date,
                            "content_plan": long_topic.model_dump(),
                            "planned_shorts": shorts_for_long,
                            "format": "long",
                        },
                    )
                    session.add(project)
                    created += 1

            short_topics = list(plan.short_videos)
            if cfg.production_mode == "shorts_only" and not short_topics:
                logger.warning("Plan shorts_only sans short_videos pour %s", channel.slug)

            orphan_shorts = [
                s
                for s in short_topics
                if cfg.production_mode == "shorts_only"
                or s.parent_long_index is None
                or s.parent_long_index >= len(plan.long_videos)
            ]
            for short_topic in orphan_shorts:
                duration = short_topic.estimated_duration_s
                if cfg.production_mode == "shorts_only":
                    duration = cfg.short_duration_s
                project = Project(
                    channel_id=channel.id,
                    theme=short_topic.subject,
                    title=short_topic.provisional_title,
                    target_duration_seconds=duration,
                    status="pending",
                    config={
                        "source": "content_planner_agent",
                        "production_date": prod_iso,
                        "target_publish_date": target_publish_date.isoformat(),
                        "planned_date": plan.plan_date,
                        "content_plan": short_topic.model_dump(),
                        "planned_shorts": [],
                        "format_hint": "short_standalone",
                        "format": "short_standalone",
                    },
                )
                session.add(project)
                created += 1

            await session.commit()

        logger.info("%d projet(s) créés pour %s (%s)", created, channel.slug, plan.plan_date)
        return created

    @staticmethod
    def _build_plan(
        channel: Channel,
        data: dict[str, Any],
        production_date: date,
        target_publish_date: date,
        long_count: int,
        short_count: int,
        default_long_s: int,
        default_short_s: int,
    ) -> DailyContentPlan:
        ta = data.get("theme_analysis", {})
        theme_analysis = ThemeAnalysis(
            sub_themes=list(ta.get("sub_themes", [])),
            narrative_formats=list(ta.get("narrative_formats", [])),
            central_figures=list(ta.get("central_figures", [])),
            good_subject_criteria=list(ta.get("good_subject_criteria", [])),
        )

        def _parse_topics(raw_list: list[Any], fmt_default: str) -> list[VideoTopicPlan]:
            topics: list[VideoTopicPlan] = []
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                est = int(item.get("estimated_duration_s", 0))
                if fmt_default == "long" and est <= 0:
                    est = default_long_s
                if fmt_default.startswith("short") and est <= 0:
                    est = default_short_s
                topics.append(
                    VideoTopicPlan(
                        priority=int(item.get("priority", len(topics) + 1)),
                        format=str(item.get("format", fmt_default)),
                        provisional_title=str(item.get("provisional_title", "Sans titre")),
                        angle=str(item.get("angle", "")),
                        narrative_format=str(item.get("narrative_format", "récit")),
                        estimated_duration_s=est,
                        sub_theme=str(item.get("sub_theme", "")),
                        main_entities=[str(e) for e in item.get("main_entities", [])],
                        seo_keywords=[str(k) for k in item.get("seo_keywords", [])],
                        subject=str(item.get("subject", item.get("provisional_title", ""))),
                        parent_long_index=item.get("parent_long_index"),
                        reactive_news_hook=item.get("reactive_news_hook"),
                    )
                )
            return topics

        long_videos = _parse_topics(data.get("long_videos", []), "long")[:long_count]
        short_videos = _parse_topics(data.get("short_videos", []), "short_derived")[:short_count]

        while len(long_videos) < long_count:
            long_videos.append(
                VideoTopicPlan(
                    priority=len(long_videos) + 1,
                    format="long",
                    provisional_title="Sujet de secours",
                    angle="Exploration complémentaire du thème",
                    narrative_format="récit",
                    estimated_duration_s=default_long_s,
                    sub_theme=channel.theme_category,
                    subject=f"Approfondissement {channel.theme_category}",
                )
            )

        return DailyContentPlan(
            plan_date=target_publish_date.isoformat(),
            production_date=production_date.isoformat(),
            target_publish_date=target_publish_date.isoformat(),
            channel_slug=channel.slug,
            theme_category=channel.theme_category,
            long_count=long_count,
            short_count=short_count,
            theme_analysis=theme_analysis,
            long_videos=long_videos,
            short_videos=short_videos,
            selection_rationale=str(data.get("selection_rationale", "")),
            evergreen_fallback_used=bool(data.get("evergreen_fallback_used", False)),
        )

    @staticmethod
    def _dedup_plan_against_history(
        plan: DailyContentPlan, history: list[dict[str, Any]]
    ) -> DailyContentPlan:
        """Filtre les topics LLM trop similaires à l'historique (vérification post-génération)."""
        live_history = list(history)

        filtered_longs: list[VideoTopicPlan] = []
        for topic in plan.long_videos:
            if find_similar_in_history(topic.subject, live_history):
                logger.warning("Topic LLM filtré post-génération (doublon) : %r", topic.subject)
            else:
                filtered_longs.append(topic)
                live_history.append({"subject": topic.subject, "title": topic.provisional_title})

        filtered_shorts: list[VideoTopicPlan] = []
        for topic in plan.short_videos:
            if find_similar_in_history(topic.subject, live_history):
                logger.warning("Short LLM filtré post-génération (doublon) : %r", topic.subject)
            else:
                filtered_shorts.append(topic)
                live_history.append({"subject": topic.subject, "title": topic.provisional_title})

        return plan.model_copy(update={"long_videos": filtered_longs, "short_videos": filtered_shorts})

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
