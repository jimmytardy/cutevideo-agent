from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Scenario
from agent.core.learning_context import LEARNING_CONTEXT_BLOCK
from agent.core.short_format import clamp_short_scenario_payload
from agent.core.prompt_safety import (
    UNTRUSTED_CONTENT_POLICY,
    sanitize_search_terms,
    wrap_untrusted,
)

logger = logging.getLogger(__name__)

MOOD_FIELD_DOC = (
    "CHAMP mood — choisis parmi : energique | calme | dramatique | mysterieux | "
    "inspirant | humoristique | tension | revelateur"
)

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
{editorial_format_block}
{scenario_structure_block}

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
  "authorship_angle": {{
    "thesis": "Thèse / point de vue en 1 phrase",
    "reason_to_watch": "Pourquoi regarder cette vidéo maintenant",
    "intro_hook": "Phrase d'ouverture oralisant la thèse (~15 s)"
  }},
  "total_duration_s": 1800
}}

Principes OBLIGATOIRES :
- authorship_angle OBLIGATOIRE : thesis non vide ; segment 1 doit oraliser intro_hook ; description mentionne la thèse
- Structure narrative : arc tension → révélation → payoff dans les titres de segments
- Segment 1 : accroche / paradoxe avec question rhétorique dans les ~15 premières secondes
- Segments milieu : mécanisme, preuves, approfondissement
- Dernier segment : conclusion mémorable + phrase de clôture marquante
- Exploiter les 3 faits surprenants du brief recherche dans le hook ou segment 2
- Hook fort dans les 30 premières secondes
- Chaque segment : MINIMUM 4 mots-clés (2 FR + 2 EN)
- Chaque search_keywords doit être ancré au SUJET DE LA VIDÉO (« {theme} ») et au contenu du segment (titre + narration)
- Inclure des termes précis (nom propre, lieu, concept, espèce, événement…) — jamais de mots-clés purement génériques seuls (ex. « nature », « animal », « histoire » sans qualificatif lié au sujet)
- Narration naturelle si needs_voice true
- Total : environ {duration_min} minutes

ÉCRITURE POUR L'ORAL (narration_text, OBLIGATOIRE si needs_voice true) :
- Phrases courtes : une seule idée par phrase, viser ≤ 20 mots
- Ponctuation forte (. ! ?) pour rythmer les pauses naturelles à la lecture
- Nombres, dates et siècles écrits en toutes lettres (ex. « 1789 » → « dix-sept cent quatre-vingt-neuf », « 75 % » → « soixante-quinze pour cent »)
- Développer les sigles et unités prononçables (ex. « km/h » → « kilomètres heure »)
- Bannir parenthèses, incises longues, listes à puces et tout markdown dans le texte de narration
- Style parlé et direct (s'adresser au spectateur), pas de tournure « écrite »

{mood_field_doc}
CHAMP strip_source_audio — true si la vidéo/image source doit être muette (narration ou musique seule), false si le son ambiant du clip enrichit le contenu (ex: applaudissements, sons de nature, ambiance lieu). Si needs_voice est false, mets strip_source_audio à false par défaut (sauf si tu veux explicitement une vidéo muette + musique seule).
CHAMP needs_music — true si une musique de fond améliore le segment ; false si voix seule, son ambiant seul, ou silence volontaire.

VOIX ET DELIVERY_STYLE (OBLIGATOIRE si needs_voice true) :
- Chaque segment avec voix DOIT avoir un delivery_style DIFFÉRENT des autres segments (varier pace, emotion, azure_style)
- Hook (segment 1) : pace "fast", emotion dynamique, azure_style énergique (excited, cheerful)
- Conclusion : pace "slow", emotion posée (calm, empathetic)
- emphasis_words : 3 à 8 mots par segment voix (noms propres, chiffres, mots-clés du hook)
- pace valides (UNIQUEMENT) : slow, normal, fast — pas de "medium" ni de variante
- azure_style valides : narration-professional, narration-relaxed, documentary-narration, cheerful, empathetic, excited, calm, sad, terrified, whispering, newscast-formal
- Ne JAMAIS répéter le même delivery_style sur tous les segments

{research_rules_block}
{critic_feedback_block}
{fact_check_feedback_block}
{sources_block}
{visual_beats_rules}
Pour source_hint : choisis 2-3 sources dans l'ordre de pertinence pour le sujet du segment."""

USER_PROMPT_SHORT = """Crée un scénario pour un SHORT vertical de {min_duration_s} à {max_duration_s} secondes.

CHAÎNE : {channel_name} (catégorie : {theme_category})
THÈME CHAÎNE : {theme_prompt}
CONTEXTE : {niche_prompt}
TON : {editorial_tone}
{creative_brief_block}SUJET : "{theme}"

{content_plan_block}
{editorial_format_block}
{scenario_structure_block}

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
  "authorship_angle": {{
    "thesis": "Thèse / point de vue en 1 phrase",
    "reason_to_watch": "Pourquoi regarder ce short",
    "intro_hook": "Hook oral (~5 s)"
  }},
  "total_duration_s": {target_duration_s}
}}

RÈGLES SHORT :
- authorship_angle OBLIGATOIRE : thesis non vide ; segment 1 oralise intro_hook
- 1 à 3 segments ; durée totale indicative entre {min_duration_s} et {max_duration_s} s (durée réelle calibrée post-voix)
- Minimum TikTok : {min_duration_s} s — ne pas viser une durée fixe si le contenu demande plus
- needs_voice : true par défaut pour contenu éducatif ; false uniquement si visuel + on_screen_text suffisent
- needs_music : true seulement si la musique de fond apporte de la valeur ; false pour voix seule ou son ambiant
- search_keywords ancrés au SUJET (« {theme} ») et au segment — termes précis obligatoires, pas de mots-clés génériques seuls
- Formats sans voix OK : visuels + on_screen_text, meme-style, musique
- Rythme rapide, punchlines si ton humoristique
- Total indicatif : {min_duration_s}–{max_duration_s} s — total_duration_s DOIT rester ≤ {target_duration_s} s

{mood_field_doc}
CHAMP strip_source_audio — false par défaut si needs_voice est false (conserver sons ambiants des clips) ; true uniquement si tu veux une vidéo muette avec musique/texte seuls.
CHAMP needs_music — false si pas de bed musical pertinent (voix seule, ASMR, son ambiant du clip).

ÉCRITURE POUR L'ORAL (narration_text, si needs_voice true) :
- Phrases courtes et percutantes (≤ 18 mots), une idée par phrase
- Nombres/dates/unités en toutes lettres (« 90 % » → « quatre-vingt-dix pour cent », « km/h » → « kilomètres heure »)
- Aucun markdown ni parenthèse ; style parlé direct

VOIX ET DELIVERY_STYLE (si needs_voice true) :
- delivery_style variable par segment ; hook rapide (pace fast), emphasis_words 3-5 mots
- pace valides (UNIQUEMENT) : slow, normal, fast — pas de "medium" ni de variante
- Ne pas répéter le même azure_style sur tous les segments

{research_rules_block}
{critic_feedback_block}
{fact_check_feedback_block}
{sources_block}
{visual_beats_rules}
Pour source_hint : 2-3 sources dans l'ordre de pertinence pour le sujet du segment."""


WRITER_SYSTEM_PROMPT_LONG = """Tu es un scénariste expert en vidéos YouTube longues (éducation, divertissement, documentaire).
Tu reçois une ARCHITECTURE figée (segments, durées, mood, intentions) conçue en amont.
Ton seul travail : ÉCRIRE le texte (narration vivante, texte à l'écran, direction voix, mots-clés médias).
Tu RESPECTES le squelette à la lettre : mêmes segments, même ordre, mêmes durées/mood/hook_type.
Tu produis toujours des JSON valides, sans texte avant ni après."""

WRITER_SYSTEM_PROMPT_SHORT = """Tu es un scénariste expert en formats courts verticaux (Shorts, TikTok, Reels).
Tu reçois une ARCHITECTURE figée et tu ÉCRIS uniquement le texte (narration percutante, texte à l'écran,
direction voix, mots-clés médias), en respectant le squelette à la lettre.
Tu produis toujours des JSON valides, sans texte avant ni après."""

WRITER_PROMPT_LONG = """Écris la narration complète à partir de l'ARCHITECTURE figée ci-dessous.

CHAÎNE : {channel_name} (catégorie : {theme_category})
TON ÉDITORIAL : {editorial_tone}
SUJET DE LA VIDÉO : "{theme}"

{research_block}

{learning_block}

ARCHITECTURE FIGÉE (squelette à respecter — n'ajoute/ne supprime aucun segment) :
{outline_block}

Retourne UNIQUEMENT un JSON valide avec cette structure (un objet par segment du squelette) :
{{
  "title": "{outline_title}",
  "description": "Description YouTube SEO (max 500 caractères)",
  "segments": [
    {{
      "order": 1,
      "title": "(reprends le titre du squelette)",
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

RÈGLES DE FIDÉLITÉ AU SQUELETTE (impératif) :
- Reprends EXACTEMENT : order, title, duration_s, needs_voice, needs_music, mood, hook_type, strip_source_audio
- Écris la narration qui réalise l'`intent` de chaque segment (sans recopier l'`intent`)
- N'invente AUCUN segment ; ne fusionne/scinde pas le squelette

Principes d'écriture :
- Exploiter les faits du brief recherche au bon segment (selon les intentions du squelette)
- Chaque segment : MINIMUM 4 mots-clés (2 FR + 2 EN)
- Chaque search_keywords ancré au SUJET (« {theme} ») et au contenu du segment — termes précis (nom propre, lieu, concept…), jamais génériques seuls

ÉCRITURE POUR L'ORAL (narration_text, OBLIGATOIRE si needs_voice true) :
- Phrases courtes : une idée par phrase, viser ≤ 20 mots
- Ponctuation forte (. ! ?) pour rythmer les pauses
- Nombres, dates et siècles en toutes lettres ; sigles/unités prononçables développés
- Aucune parenthèse, incise longue, liste à puces ou markdown
- Style parlé et direct (s'adresser au spectateur)

VOIX ET DELIVERY_STYLE (OBLIGATOIRE si needs_voice true) :
- delivery_style DIFFÉRENT pour chaque segment voix (varier pace, emotion, azure_style)
- Hook : pace "fast", azure_style énergique (excited, cheerful) ; conclusion : pace "slow", posé (calm, empathetic)
- emphasis_words : 3 à 8 mots par segment voix
- pace valides (UNIQUEMENT) : slow, normal, fast — pas de "medium" ni de variante
- azure_style valides : narration-professional, narration-relaxed, documentary-narration, cheerful, empathetic, excited, calm, sad, terrified, whispering, newscast-formal

{research_rules_block}
{critic_feedback_block}
{fact_check_feedback_block}
{sources_block}
{visual_beats_rules}
Pour source_hint : choisis 2-3 sources dans l'ordre de pertinence pour le sujet du segment."""

WRITER_PROMPT_SHORT = """Écris la narration à partir de l'ARCHITECTURE figée ci-dessous (SHORT vertical).

CHAÎNE : {channel_name} (catégorie : {theme_category})
TON : {editorial_tone}
SUJET : "{theme}"

{research_block}

{learning_block}

ARCHITECTURE FIGÉE (squelette à respecter — n'ajoute/ne supprime aucun segment) :
{outline_block}

Retourne UNIQUEMENT ce JSON (un objet par segment du squelette) :
{{
  "title": "{outline_title}",
  "description": "Description courte",
  "segments": [
    {{
      "order": 1,
      "title": "(reprends le titre du squelette)",
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
  "total_duration_s": {target_duration_s}
}}

RÈGLES DE FIDÉLITÉ AU SQUELETTE (impératif) :
- Reprends EXACTEMENT : order, title, duration_s, needs_voice, needs_music, mood, hook_type, strip_source_audio
- Écris la narration qui réalise l'`intent` de chaque segment (sans recopier l'`intent`)
- N'invente AUCUN segment

RÈGLES SHORT :
- search_keywords ancrés au SUJET (« {theme} ») — termes précis, pas de mots-clés génériques seuls
- Rythme rapide, punchlines si ton humoristique

ÉCRITURE POUR L'ORAL (narration_text, si needs_voice true) :
- Phrases courtes et percutantes (≤ 18 mots), une idée par phrase
- Nombres/dates/unités en toutes lettres ; aucun markdown ni parenthèse ; style parlé direct

VOIX ET DELIVERY_STYLE (si needs_voice true) :
- delivery_style variable par segment ; hook rapide (pace fast), emphasis_words 3-5 mots
- pace valides (UNIQUEMENT) : slow, normal, fast — pas de "medium" ni de variante
- Ne pas répéter le même azure_style sur tous les segments

{research_rules_block}
{critic_feedback_block}
{fact_check_feedback_block}
{sources_block}
{visual_beats_rules}
Pour source_hint : 2-3 sources dans l'ordre de pertinence pour le sujet du segment."""


def _format_outline_block(outline: dict[str, Any]) -> str:
    """Sérialise le squelette en texte lisible pour le prompt d'écriture."""
    lines: list[str] = []
    for seg in outline.get("segments", []):
        hook = seg.get("hook_type")
        hook_txt = f", hook={hook}" if hook else ""
        music = "musique" if seg.get("needs_music") else "sans musique"
        voice = "voix" if seg.get("needs_voice", True) else "SANS voix"
        lines.append(
            f"- Segment {seg.get('order')} « {seg.get('title')} » "
            f"({seg.get('duration_s')}s, {voice}, {music}, mood={seg.get('mood')}{hook_txt})\n"
            f"  Intention : {seg.get('intent') or '(non précisé)'}"
        )
    return "\n".join(lines)


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
    voice_segments: bool = True,
) -> dict[str, str]:
    from agent.core.visual_beats_prompt import (
        SCENARIO_VOICE_BEATS_CONTEXT,
        build_visual_beats_prompt_context,
    )

    if voice_segments:
        return dict(SCENARIO_VOICE_BEATS_CONTEXT)
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


def _format_fact_check_feedback_block(feedback: list[dict] | None) -> str:
    if not feedback:
        return ""
    lines = [
        "CORRECTIONS FACTUELLES OBLIGATOIRES (échec vérification factuelle — à corriger impérativement) :",
    ]
    for item in feedback:
        seg = item.get("segment_order", "?")
        claim = item.get("claim", "")
        issue = item.get("issue", "")
        severity = item.get("severity", "major")
        lines.append(f'- [segment {seg}] ({severity}) « {claim} » → {issue}')
    lines.append(
        "Corrige UNIQUEMENT les affirmations factuelles erronées. "
        "Conserve le style, la structure et les segments non concernés."
    )
    lines.append("")
    return "\n".join(lines)


def _format_content_plan_block(plan: dict[str, Any] | None) -> str:
    if not plan:
        return ""
    from agent.skills.scenario.authorship_angle import format_editorial_format_block

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
    block = "\n".join(lines) + "\n"
    return block + format_editorial_format_block(plan)


def _format_scenario_structure_block(
    plan: dict[str, Any] | None,
    channel_raw_config: dict[str, Any] | None,
) -> str:
    if not plan:
        return ""
    from agent.core.editorial_formats import get_format_by_id

    fmt_id = str(plan.get("editorial_format_id") or "").strip()
    fmt = get_format_by_id(fmt_id, channel_raw_config)
    if not fmt or not fmt.scenario_structure:
        return ""
    intro = plan.get("intro_variant") or ""
    outro = plan.get("outro_variant") or ""
    lines = [
        "STRUCTURE DE SCÉNARIO (format assigné — à respecter) :",
        fmt.scenario_structure,
    ]
    if intro:
        lines.append(f"Variante intro imposée : {intro}")
    if outro:
        lines.append(f"Variante outro imposée : {outro}")
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
    min_short_duration_s: int = 60
    max_short_duration_s: int = 120
    content_plan_block: str = ""
    editorial_format_block: str = ""
    scenario_structure_block: str = ""
    content_plan: dict[str, Any] | None = None
    research_block: str = ""
    research_rules_block: str = ""
    critic_feedback_block: str = ""
    fact_check_feedback_block: str = ""
    creative_brief_block: str = ""


class ScenarioAgent(BaseAgent):
    """Agent 1 — Scénariste : crée la structure narrative complète."""

    name = "scenario_agent"

    async def run(self, ctx: "PipelineContext", outline: dict[str, Any] | None = None) -> Scenario:  # type: ignore[override]
        if outline is None:
            from agent.agents.outline_agent import load_outline

            outline = await load_outline(ctx.project_id)
        theme_prompt = ctx.channel.theme_prompt or ctx.niche_prompt or ""
        critic_feedback_block = _format_critic_feedback_block(ctx.critic_feedback)
        fact_check_feedback_block = _format_fact_check_feedback_block(ctx.fact_check_feedback)
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
            min_short_duration_s=ctx.channel_config.min_short_duration_s,
            max_short_duration_s=ctx.channel_config.max_short_duration_s,
            content_plan_block=_format_content_plan_block(ctx.content_plan),
            editorial_format_block="",
            scenario_structure_block=_format_scenario_structure_block(
                ctx.content_plan, dict(ctx.channel.config or {})
            ),
            content_plan=ctx.content_plan,
            research_block=_format_research_block(ctx.research_brief),
            research_rules_block=_format_research_rules_block(ctx.research_brief),
            critic_feedback_block=critic_feedback_block,
            fact_check_feedback_block=fact_check_feedback_block,
            creative_brief_block=_format_creative_brief_block(ctx.channel_config.creative_brief),
        )
        run = await self.start_run(ctx.project_id, input_data)
        try:
            scenario = await self._generate_scenario(
                input_data, outline, channel_config=ctx.channel_config
            )
            await self.end_run(run, {"scenario_id": str(scenario.id)})
            return scenario
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _generate_scenario(
        self,
        input_data: ScenarioInput,
        outline: dict[str, Any] | None = None,
        *,
        channel_config: "ChannelRuntimeConfig | None" = None,
    ) -> Scenario:
        is_short = input_data.production_mode == "shorts_only" or input_data.target_duration_seconds <= 120
        # Le contexte d'apprentissage dérive de retours audience/commentaires (non fiables) :
        # on le balise comme donnée pour qu'il ne soit pas pris pour des instructions (OWASP LLM01).
        learning_block = LEARNING_CONTEXT_BLOCK.format(
            learning_context_prompt=wrap_untrusted(
                input_data.learning_context_prompt, label="audience_feedback"
            ),
        )

        if is_short:
            segment_duration = min(30, max(15, input_data.target_duration_seconds // 2))
            target_duration = min(
                input_data.max_short_duration_s,
                max(input_data.min_short_duration_s, input_data.target_duration_seconds),
            )
            vb_ctx = _build_visual_beats_prompt_context(
                input_data.editorial_tone,
                input_data.theme_category,
                content_language=input_data.content_language,
                min_diagram_duration_long=input_data.min_diagram_duration_s,
                min_diagram_duration_short=input_data.min_diagram_duration_short_s,
                is_short=True,
                voice_segments=True,
            )
            if outline and outline.get("segments"):
                prompt = WRITER_PROMPT_SHORT.format(
                    target_duration_s=target_duration,
                    segment_duration=segment_duration,
                    channel_name=input_data.channel_name,
                    theme_category=input_data.theme_category,
                    editorial_tone=input_data.editorial_tone,
                    theme=input_data.theme,
                    research_block=input_data.research_block,
                    learning_block=learning_block,
                    outline_block=_format_outline_block(outline),
                    outline_title=outline.get("title", ""),
                    research_rules_block=input_data.research_rules_block,
                    critic_feedback_block=input_data.critic_feedback_block,
                    fact_check_feedback_block=input_data.fact_check_feedback_block,
                    sources_block=AVAILABLE_SOURCES,
                    **vb_ctx,
                )
                system = WRITER_SYSTEM_PROMPT_SHORT
            else:
                prompt = USER_PROMPT_SHORT.format(
                    min_duration_s=input_data.min_short_duration_s,
                    max_duration_s=input_data.max_short_duration_s,
                    target_duration_s=target_duration,
                    segment_duration=segment_duration,
                    channel_name=input_data.channel_name,
                    theme_category=input_data.theme_category,
                    theme_prompt=input_data.theme_prompt or input_data.niche_prompt,
                    niche_prompt=input_data.niche_prompt or "Contenu court vertical",
                    editorial_tone=input_data.editorial_tone,
                    creative_brief_block=input_data.creative_brief_block,
                    theme=input_data.theme,
                    content_plan_block=input_data.content_plan_block,
                    editorial_format_block=input_data.editorial_format_block,
                    scenario_structure_block=input_data.scenario_structure_block,
                    research_block=input_data.research_block,
                    research_rules_block=input_data.research_rules_block,
                    learning_block=learning_block,
                    critic_feedback_block=input_data.critic_feedback_block,
                    fact_check_feedback_block=input_data.fact_check_feedback_block,
                    sources_block=AVAILABLE_SOURCES,
                    mood_field_doc=MOOD_FIELD_DOC,
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
                voice_segments=True,
            )
            if outline and outline.get("segments"):
                prompt = WRITER_PROMPT_LONG.format(
                    channel_name=input_data.channel_name,
                    theme_category=input_data.theme_category,
                    editorial_tone=input_data.editorial_tone,
                    theme=input_data.theme,
                    research_block=input_data.research_block,
                    learning_block=learning_block,
                    outline_block=_format_outline_block(outline),
                    outline_title=outline.get("title", ""),
                    research_rules_block=input_data.research_rules_block,
                    critic_feedback_block=input_data.critic_feedback_block,
                    fact_check_feedback_block=input_data.fact_check_feedback_block,
                    sources_block=AVAILABLE_SOURCES,
                    **vb_ctx,
                )
                system = WRITER_SYSTEM_PROMPT_LONG
            else:
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
                    editorial_format_block=input_data.editorial_format_block,
                    scenario_structure_block=input_data.scenario_structure_block,
                    research_block=input_data.research_block,
                    research_rules_block=input_data.research_rules_block,
                    learning_block=learning_block,
                    critic_feedback_block=input_data.critic_feedback_block,
                    fact_check_feedback_block=input_data.fact_check_feedback_block,
                    sources_block=AVAILABLE_SOURCES,
                    mood_field_doc=MOOD_FIELD_DOC,
                    **vb_ctx,
                )
                system = SYSTEM_PROMPT_LONG

        # Le SUJET (theme) et les retours audience peuvent venir de tiers : politique de
        # contenu non fiable côté system prompt (OWASP LLM01 / reco Anthropic).
        system = f"{system}\n\n{UNTRUSTED_CONTENT_POLICY}"
        raw = await self._call_claude(prompt, system=system, max_tokens=8192)
        data = self._parse_json(raw)

        # Nettoie les mots-clés issus du LLM avant qu'ils n'atteignent les requêtes média
        # externes (anti-injection de requête — un scénario empoisonné ne doit pas pouvoir
        # forger une requête SRU/Lucene).
        for seg in data.get("segments", []):
            if isinstance(seg, dict) and "search_keywords" in seg:
                seg["search_keywords"] = sanitize_search_terms(seg.get("search_keywords"))

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
            user_id=self._user_id,
        )
        data = apply_brief_to_scenario_data(data, brief)

        from agent.skills.scenario.authorship_angle import normalize_authorship_angle

        authorship = normalize_authorship_angle(data, content_plan=input_data.content_plan)
        data["authorship_angle"] = authorship
        if authorship.get("thesis") and not str(data.get("description") or "").strip():
            data["description"] = authorship["thesis"]

        if is_short and channel_config is not None:
            data = clamp_short_scenario_payload(
                data,
                target_duration_seconds=input_data.target_duration_seconds,
                channel_config=channel_config,
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
            project_config["authorship_angle"] = authorship

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
