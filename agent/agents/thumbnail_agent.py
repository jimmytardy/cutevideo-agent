from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from agent.core.api_keys import fetch_api_key, parse_gcp_credentials
from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Project, Scenario

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

# Concepts de miniature : on génère un visuel marquant SANS texte (la typo FLUX est peu fiable) ;
# le titre est ajouté en overlay à l'upload. Espace négatif réservé pour ce titre.
_THUMBNAIL_STYLE = (
    "YouTube thumbnail, single bold focal subject, dramatic high-contrast lighting, "
    "vivid saturated colors, strong rim light, shallow depth of field, cinematic, "
    "eye-catching, rule-of-thirds composition, empty negative space on one side for a title"
)
_THUMBNAIL_QUALITY = "High quality, ultra detailed. No text, no watermark, no logo, no caption. No collage."


class ThumbnailAgent(BaseAgent):
    """Génère des concepts de miniature (CTR YouTube) via Flux.2."""

    name = "thumbnail_agent"

    def __init__(self) -> None:
        super().__init__()
        self._fal_api_key: str | None = None
        self._gemini_api_key: str = ""
        self._gcp_credentials: Any = None

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> list[dict[str, Any]]:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id,
            {"scenario_id": str(scenario.id)},
            iteration=ctx.iteration,
        )
        try:
            candidates = await self._generate(ctx, scenario)
            await self._persist(ctx.project_id, candidates)
            await self.end_run(run, {"candidates": len(candidates)})
            return candidates
        except Exception as exc:
            await self.fail_run(run, exc)
            raise

    async def _resolve_keys(self, ctx: "PipelineContext") -> None:
        fal_ctx = await fetch_api_key(ctx.user_id, "fal", purpose="ai_image", tier="paid")
        self._fal_api_key = fal_ctx.key
        gemini_ctx = await fetch_api_key(ctx.user_id, "gemini", purpose="ai_image", tier="free")
        self._gemini_api_key = gemini_ctx.key or ""
        gcp_ctx = await fetch_api_key(ctx.user_id, "gcp", purpose="ai_image", tier="paid")
        self._gcp_credentials = parse_gcp_credentials(gcp_ctx)

    async def _generate(self, ctx: "PipelineContext", scenario: Scenario) -> list[dict[str, Any]]:
        ai_cfg = ctx.channel_config.ai_fallback
        if not ai_cfg.enabled or ai_cfg.plan.value == "off":
            logger.info("Génération IA désactivée — miniature ignorée")
            return []

        await self._resolve_keys(ctx)
        if not self._fal_api_key:
            logger.info("Clé fal absente — miniature ignorée")
            return []

        from agent.skills.media_sources.ai.prompt_synthesizer import synthesize_flux_subject
        from agent.skills.media_sources.ai_image import generate_image

        # Sujet principal de la miniature : titre final (metadata_agent) ou thème.
        title = await self._resolve_title(ctx.project_id) or ctx.theme
        segments = list(scenario.segments or [])
        hook = next((s for s in segments if int(s.get("order", 0) or 0) == 1), None)
        hook_text = str((hook or {}).get("narration_text") or "")[:200]

        output_dir = Path(f"./tmp/{ctx.project_id}/thumbnail")
        output_dir.mkdir(parents=True, exist_ok=True)
        style_block = getattr(ctx, "visual_style_block", "") or ""

        # Deux angles : sujet emblématique vs ambiance/émotion du hook.
        briefs_fr = [
            f"{title} — {ctx.theme}",
            f"{ctx.theme} — {hook_text}" if hook_text else f"{ctx.theme} — {title}",
        ]

        candidates: list[dict[str, Any]] = []
        for idx, brief_fr in enumerate(briefs_fr):
            subject_en = await synthesize_flux_subject(
                visual_type="custom",
                prompt_fr=brief_fr,
                style_hint=_THUMBNAIL_STYLE,
                phrase_anchor=title,
                api_key=self._gemini_api_key or None,
                cache_dir=output_dir / "prompt_cache",
            )
            parts = [subject_en.strip().rstrip("."), _THUMBNAIL_STYLE]
            if style_block.strip():
                parts.append(style_block.strip().rstrip("."))
            parts.append("landscape 16:9 horizontal framing")
            prompt = ". ".join(parts) + f". {_THUMBNAIL_QUALITY}"

            result = await generate_image(
                prompt,
                output_dir / f"concept_{idx + 1:02d}",
                ai_cfg=ai_cfg,
                theme_category=ctx.theme_category,
                editorial_tone=ctx.channel_config.editorial_tone,
                aspect_ratio="16:9",
                plan_override="flux_2_dev",
                use_prompt_as_is=True,
                visual_type="custom",
                style_block=style_block,
                fal_api_key=self._fal_api_key,
                gcp_credentials=self._gcp_credentials,
            )
            if result and result.get("local_generated"):
                candidates.append({
                    "local_path": result["local_generated"],
                    "prompt": prompt,
                    "attribution": result.get("attribution"),
                    "primary": False,
                })

        if candidates:
            await self._rank_candidates_with_vision(candidates, title)
            for c in candidates:
                c["primary"] = False
            primary = max(candidates, key=lambda c: float(c.get("ctr_score", 0)))
            primary["primary"] = True
        logger.info("Miniatures générées : %d concept(s)", len(candidates))
        return candidates

    async def _rank_candidates_with_vision(
        self,
        candidates: list[dict[str, Any]],
        title: str,
    ) -> None:
        """Classement CTR optionnel via Gemini Vision entre candidats."""
        if len(candidates) < 2 or not self._gemini_api_key:
            for c in candidates:
                c.setdefault("ctr_score", 0.5)
            return

        import asyncio
        import json

        try:
            from google import genai
            from google.genai import types

            from agent.core.json_parse import parse_gemini_response
        except ImportError:
            for c in candidates:
                c.setdefault("ctr_score", 0.5)
            return

        prompt = (
            f"Tu es expert CTR YouTube. Titre vidéo : {title!r}. "
            "Pour chaque miniature (dans l'ordre), estime un score CTR de 0 à 10 "
            "(contraste, sujet focal, espace pour titre, émotion). "
            'Retourne JSON : {"scores": [8.5, 6.2]}'
        )
        parts: list[Any] = [prompt]
        for cand in candidates:
            path = Path(str(cand.get("local_path") or ""))
            if path.is_file():
                parts.append(
                    types.Part.from_bytes(data=path.read_bytes(), mime_type="image/jpeg")
                )

        def _run() -> dict[str, Any]:
            client = genai.Client(api_key=self._gemini_api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=parts,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=256,
                    response_mime_type="application/json",
                ),
            )
            return parse_gemini_response(response, "gemini-2.5-flash")

        try:
            data = await asyncio.to_thread(_run)
            scores = data.get("scores") or []
            for idx, cand in enumerate(candidates):
                raw = scores[idx] if idx < len(scores) else 5.0
                cand["ctr_score"] = float(raw) / 10.0
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Classement miniature vision ignoré : %s", exc)
            for c in candidates:
                c.setdefault("ctr_score", 0.5)

    @staticmethod
    async def _resolve_title(project_id) -> str:
        async with AsyncSessionFactory() as session:
            project = await session.get(Project, project_id)
            if not project:
                return ""
            meta = (project.config or {}).get("youtube_metadata") if project.config else None
            if isinstance(meta, dict) and meta.get("title"):
                return str(meta["title"])
            return project.title or ""

    @staticmethod
    async def _persist(project_id, candidates: list[dict[str, Any]]) -> None:
        if not candidates:
            return
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                return
            config = dict(project.config or {})
            config["thumbnail_candidates"] = candidates
            primary = next((c for c in candidates if c.get("primary")), candidates[0])
            config["thumbnail"] = primary
            await session.execute(
                update(Project).where(Project.id == project_id).values(config=config)
            )
            await session.commit()
