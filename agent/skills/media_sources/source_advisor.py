from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger(__name__)

AVAILABLE_SOURCES = [
    "gallica", "europeana", "wikimedia", "internet_archive",
    "pexels", "pixabay", "coverr", "unsplash",
    "nasa", "ai", "runway",
]

_PROMPT = """Tu es un expert en production vidéo et en sourcing d'images/vidéos.

Une chaîne YouTube/TikTok vient d'être créée avec ces caractéristiques :
- Nom : {channel_name}
- Catégorie thématique : {theme_category}
- Niche : {niche_prompt}

Sources disponibles :
- gallica        : archives BnF, France historique (avant 1950)
- europeana      : patrimoine européen, musées, archives
- wikimedia      : encyclopédique, toutes époques, monde entier
- internet_archive : films, docs, médias anciens domaine public
- pexels         : photos/vidéos stock modernes, lifestyle, nature
- pixabay        : idem pexels, plus de variété
- coverr         : vidéos stock B-roll dynamiques (HD/4K), complément vidéo
- unsplash       : photos artistiques, ambiances, architecture
- nasa           : espace, astronomie, science (images + vidéos NASA)
- ai             : génération IA images si aucune source réelle ne convient
- runway         : génération vidéo IA Runway Gen-4, clips 5-10s haute qualité (coût par clip)

Retourne UNIQUEMENT un JSON valide sans texte avant ni après :
{{
  "media_source_priority": ["source1", "source2", "source3", "source4", "source5"],
  "rationale": "Une ligne expliquant le choix"
}}

Règles :
- Liste 4 à 6 sources dans l'ordre de pertinence pour cette chaîne
- Toujours terminer par "ai" si aucune autre source ne couvre le besoin
- Utilise uniquement les noms exacts listés ci-dessus"""


async def suggest_media_source_priority(
    channel_name: str,
    theme_category: str,
    niche_prompt: str,
    *,
    user_id: uuid.UUID | None = None,
) -> list[str]:
    """Demande à Claude de classer les sources médias pour une chaîne."""
    try:
        from agent.core.database import AsyncSessionFactory, User
        from agent.core.llm_resolver import call_llm

        prompt = _PROMPT.format(
            channel_name=channel_name,
            theme_category=theme_category or "général",
            niche_prompt=niche_prompt or "contenu généraliste",
        )
        async with AsyncSessionFactory() as session:
            user = await session.get(User, user_id) if user_id else None
            raw = await call_llm(
                session,
                user,
                "source_advisor",
                prompt,
                max_tokens=256,
                model_override="claude-haiku-4-5-20251001",
            )
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(raw)
        priority = data.get("media_source_priority", [])
        valid = [s for s in priority if s in AVAILABLE_SOURCES]
        if valid:
            logger.info(
                "Source priority IA pour '%s' : %s (rationale: %s)",
                channel_name,
                valid,
                data.get("rationale", ""),
            )
            return valid
    except Exception as e:
        logger.warning("suggest_media_source_priority échoué : %s", e)
    return []
