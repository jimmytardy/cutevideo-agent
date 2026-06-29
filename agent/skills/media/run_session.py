from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.core.media_validation import MediaValidationBrief
from agent.skills.media.ai_image_result import MediaGap
from agent.skills.media_sources.ai.prompt_synthesizer import SearchAnchor


@dataclass
class MediaRunSession:
    """État mutable partagé pour un run MediaAgent (recherche, scoring, quotas IA)."""

    relevance_log: list[dict[str, Any]] = field(default_factory=list)
    media_gaps: list[MediaGap] = field(default_factory=list)
    kept_temp_s3_keys: list[str] = field(default_factory=list)
    segment_media_gaps: set[int] = field(default_factory=set)
    ai_images_used: int = 0
    runway_clips_used: int = 0
    perception_calls_used: int = 0
    search_anchor: SearchAnchor | None = None
    search_orientation: str = "landscape"
    validation_brief: MediaValidationBrief | None = None
    gemini_api_key: str = ""
    scoring_models: list[str] | None = None
    fal_api_key: str | None = None
    runway_api_key: str | None = None
    gcp_credentials: Any = None

    def bind_agent(self, agent: Any) -> None:
        """Lie les attributs legacy de l'agent aux mêmes objets mutables."""
        agent._relevance_log = self.relevance_log
        agent._media_gaps = self.media_gaps
        agent._kept_temp_s3_keys = self.kept_temp_s3_keys
        agent._segment_media_gaps = self.segment_media_gaps
        agent._ai_images_used = self.ai_images_used
        agent._runway_clips_used = self.runway_clips_used
        agent._perception_calls_used = self.perception_calls_used
        agent._search_anchor = self.search_anchor
        agent._search_orientation = self.search_orientation
        agent._validation_brief = self.validation_brief
        agent._gemini_api_key = self.gemini_api_key
        agent._scoring_models = self.scoring_models
        agent._fal_api_key = self.fal_api_key
        agent._runway_api_key = self.runway_api_key
        agent._gcp_credentials = self.gcp_credentials
        agent._session = self

    def sync_from_agent(self, agent: Any) -> None:
        """Recopie les compteurs mutables depuis l'agent (wrappers legacy)."""
        self.ai_images_used = int(getattr(agent, "_ai_images_used", 0))
        self.runway_clips_used = int(getattr(agent, "_runway_clips_used", 0))
        self.perception_calls_used = int(getattr(agent, "_perception_calls_used", 0))


async def init_provider_keys(
    agent: Any,
    ctx: Any,
    session: MediaRunSession,
) -> None:
    """Charge les clés API résolues pour l'utilisateur propriétaire de la chaîne."""
    from agent.core.agent_llm_constraints import normalize_agent_preference
    from agent.core.api_keys import fetch_api_key, parse_gcp_credentials
    from agent.core.database import AsyncSessionFactory, User
    from agent.core.llm_resolver import parse_agent_preferences
    from agent.skills.media_sources.relevance_scorer import resolve_scoring_model_chain

    gemini_ctx = await fetch_api_key(
        ctx.user_id, "gemini", purpose="media_relevance_scoring", tier="free"
    )
    session.gemini_api_key = gemini_ctx.key or ""

    scoring_model: str | None = None
    if ctx.user_id is not None:
        async with AsyncSessionFactory() as db:
            user = await db.get(User, ctx.user_id)
            if user:
                prefs = parse_agent_preferences(user.agent_llm_preferences)
                pref = prefs.get("media_agent_llm")
                if pref:
                    normalized = normalize_agent_preference("media_agent_llm", pref)
                    scoring_model = normalized.model
    session.scoring_models = resolve_scoring_model_chain(scoring_model)
    fal_ctx = await fetch_api_key(ctx.user_id, "fal", purpose="ai_image", tier="paid")
    session.fal_api_key = fal_ctx.key
    runway_ctx = await fetch_api_key(
        ctx.user_id, "runway", purpose="ai_video", tier="paid"
    )
    session.runway_api_key = runway_ctx.key
    gcp_ctx = await fetch_api_key(ctx.user_id, "gcp", purpose="ai_image", tier="paid")
    session.gcp_credentials = parse_gcp_credentials(gcp_ctx)
    session.bind_agent(agent)
