from __future__ import annotations

BEAT_PLANNER_SYSTEM = """Tu es un directeur artistique vidéo éducative.
Tu enrichis des plans visuels (visual_beats) déjà découpés temporellement sur une narration parlée.
Les phrase_anchor et spoken_text sont FIXES — ne les modifie pas.
Tu retournes UNIQUEMENT du JSON valide."""

BEAT_PLANNER_PHASE2_PROMPT = """Segment {segment_order} — enrichissement visuel des beats.

THÈME VIDÉO : {theme}
CHAÎNE : {channel_name} ({theme_category})
TON : {editorial_tone}
MOOD SEGMENT : {segment_mood}
LANGUE : {content_language}

NARRATION COMPLÈTE (contexte) :
{narration_text}

BEATS DÉCOUPÉS (phrase_anchor et spoken_text IMMUTABLES) :
{beats_json}

{visual_beats_rules}

Retourne UNIQUEMENT :
{{
  "visual_beats": [
    {{
      "order": 1,
      "phrase_anchor": "copie exacte du beat fourni",
      "spoken_text": "copie exacte du beat fourni",
      "visual_type": "documentary_photo",
      "prompt": "Description visuelle en français sans texte à afficher",
      "style_hint": "",
      "on_screen_text": "",
      "diagram_labels": [],
      "duration_hint_s": 5.0
    }}
  ]
}}

RÈGLES :
- Un objet par beat fourni (même order, même phrase_anchor, même spoken_text)
- Varier visual_type — pas de documentary_photo sur tous les beats
- 1 beat = 1 idée visuelle unique
- Diagrammes : diagram_labels obligatoires (1-6 entrées)
- duration_hint_s >= valeur fournie dans le beat d'entrée
"""

SCENARIO_NO_BEATS_NOTE = """
NOTE : Ne génère PAS de visual_beats pour les segments avec needs_voice true.
Les plans visuels seront générés automatiquement après la synthèse vocale (beat_planner_agent).
Concentre-toi sur narration_text, structure, mood, search_keywords, delivery_style.
"""
