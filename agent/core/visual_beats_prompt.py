from __future__ import annotations

VISUAL_BEATS_RULES = """
VISUAL_BEATS (OBLIGATOIRE si needs_voice true) :
- Chaque segment avec voix DOIT inclure visual_beats : liste ordonnée de plans visuels synchronisés à la narration
- Short : {min_beats_short} à {max_beats} beats par segment | Long : 5 à {max_beats} beats pour segments explicatifs
- phrase_anchor : extrait EXACT ou quasi-exact tiré de narration_text (début du plan)
- visual_type : clé EXACTE du catalogue ci-dessous — ne jamais inventer de type hors catalogue ; utiliser "custom" + style_hint si aucun type ne convient
- prompt : description visuelle en français (sans mention de texte à afficher — traduite automatiquement pour FLUX)
- Langue des labels : {content_language} (identique à la narration)
- Types diagramme (scientific_diagram, infographic, data_chart, cross_section, timeline, map, quote_card, statistic_highlight, battle_map) :
  - diagram_labels OBLIGATOIRE : 1 à 6 entrées {{"text": "...", "role": "organe|flux|étape|..."}} en {content_language}
  - duration_hint_s OBLIGATOIRE : {min_diagram_duration_short} s (short) / {min_diagram_duration_long} s (long), plus si schéma dense
  - Max 1–2 diagrammes par segment explicatif
- on_screen_text : rétrocompat (1 seul label court) si diagram_labels absent
- Varier les visual_type — ne pas répéter documentary_photo sur tous les beats
- 1 visual_beat = 1 idée visuelle UNIQUE — interdit 2 beats sur le même concept
- Max 1 documentary_photo CONSÉCUTIF ; alterner photo / schéma / vidéo / carte
- duration_hint_s par beat : défaut ≤ 6 s (sauf diagrammes ≥ min diagramme)
- Segment 1 (hook) : question rhétorique obligatoire dans les ~15 premières secondes de narration
- Structure narrative longue : arc tension → révélation → payoff explicite dans les titres de segments
- Exploiter les 3 faits surprenants du brief recherche dans le hook ou segment 2
- Segment explicatif (science, mécanisme) : au moins 1 scientific_diagram, infographic ou comparison
- Chaîne sport : privilégier sports_action, stadium_establishing, sports_celebration, athlete_portrait
- Chaîne true_crime : privilégier crime_documentary, courtroom, evidence_detail, document_closeup
- Chaîne science/espace : privilégier space_photo, telescope_view, laboratory_scene, scientific_diagram
- Ton humoristique : inclure meme_template, cartoon ou visual_pun si pertinent
- Actualité/politique : news_broll, quote_card, statistic_highlight

{catalog}
"""

VISUAL_BEATS_JSON = """
      "visual_beats": [
        {{
          "order": 1,
          "phrase_anchor": "extrait exact de la narration",
          "visual_type": "scientific_diagram",
          "prompt": "Description visuelle en français sans texte à afficher",
          "style_hint": "",
          "diagram_labels": [
            {{"text": "Label court", "role": "element"}}
          ],
          "on_screen_text": "",
          "duration_hint_s": {min_diagram_duration_long}
        }}
      ],
"""

SCENARIO_NO_BEATS_NOTE = """
VISUAL_BEATS — NE PAS GÉNÉRER au scénario pour les segments avec needs_voice true :
- Les plans visuels (visual_beats) seront créés automatiquement après la synthèse vocale (beat_planner_agent).
- Concentre-toi sur narration_text, delivery_style, mood, search_keywords, strip_source_audio.
- Pour needs_voice false uniquement : inclure visual_beats avec on_screen_text et durées estimées.
"""

SCENARIO_NO_BEATS_JSON = """
"""

SCENARIO_VOICE_BEATS_CONTEXT: dict[str, str] = {
    "visual_beats_comma": "",
    "visual_beats_example": "",
    "visual_beats_rules": SCENARIO_NO_BEATS_NOTE.strip(),
}


REVISION_VISUAL_BEATS_BLOCK = """
CATALOGUE visual_type (clés autorisées pour visual_beats[].visual_type) :
{visual_beats_catalog}

Règle : visual_type doit être une clé exacte du catalogue ci-dessus, ou "custom" avec style_hint.
"""


def build_visual_beats_prompt_context(
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
    from agent.skills.media_sources.ai.prompt_builder import build_visual_type_catalog

    catalog = build_visual_type_catalog(editorial_tone, theme_category)
    diagram_dur = min_diagram_duration_short if is_short else min_diagram_duration_long
    return {
        "visual_beats_comma": ",",
        "visual_beats_example": VISUAL_BEATS_JSON.format(
            min_diagram_duration_long=int(diagram_dur),
        ).strip(),
        "visual_beats_rules": VISUAL_BEATS_RULES.format(
            min_beats_short=min_beats_short,
            max_beats=max_beats,
            catalog=catalog,
            content_language=content_language,
            min_diagram_duration_short=int(min_diagram_duration_short),
            min_diagram_duration_long=int(min_diagram_duration_long),
        ),
        "visual_beats_catalog": catalog,
    }


def build_revision_visual_beats_block(
    editorial_tone: str,
    theme_category: str,
) -> str:
    from agent.skills.media_sources.ai.prompt_builder import build_visual_type_catalog

    catalog = build_visual_type_catalog(editorial_tone, theme_category)
    return REVISION_VISUAL_BEATS_BLOCK.format(visual_beats_catalog=catalog)
