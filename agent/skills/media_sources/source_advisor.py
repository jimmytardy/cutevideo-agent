from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

AVAILABLE_SOURCES = [
    "gallica", "europeana", "wikimedia", "internet_archive",
    "pexels", "pixabay", "unsplash",
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
- unsplash       : photos artistiques, ambiances, architecture
- nasa           : espace, astronomie, science
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
) -> list[str]:
    """Demande à Claude de classer les sources médias pour une chaîne."""
    try:
        import anthropic

        from agent.core.config import settings

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        prompt = _PROMPT.format(
            channel_name=channel_name,
            theme_category=theme_category or "général",
            niche_prompt=niche_prompt or "contenu généraliste",
        )
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(raw)
        priority = data.get("media_source_priority", [])
        # Valide que les noms sont connus
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
