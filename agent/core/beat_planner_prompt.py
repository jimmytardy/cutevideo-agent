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
- PERTINENCE AVANT VARIÉTÉ : si le beat a un référent concret photographiable (lieu, monument, statue,
  espèce, personne, objet, paysage, œuvre), choisis un type PHOTO RÉELLE (documentary_photo,
  establishing_shot, aerial, archival_footage, artwork…). N'emploie un type diagramme/IA
  (scientific_diagram, cross_section, infographic, timeline, map) QUE pour une notion abstraite/invisible
  sans référent photographiable. Un visuel hors-sujet "varié" est pire qu'une photo réelle du sujet.
- Varier les ANGLES/plans d'un même sujet réel plutôt que d'introduire un diagramme hors-sujet pour varier
- 1 beat = 1 idée visuelle unique
- Diagrammes : diagram_labels obligatoires (1-6 entrées)
- duration_hint_s >= valeur fournie dans le beat d'entrée
- APPUIS-TEXTE (on_screen_text) : incrustation courte affichée à l'écran sur le plan.
  Le remplir UNIQUEMENT sur les beats à information forte — une date clé ("1889"),
  un chiffre marquant ("18 038 pièces"), un nom propre, ou un mot-choc du hook.
  Maximum 1 à 4 mots, sans phrase ni ponctuation finale. Cadence : au plus ~1 beat
  sur 3 ; laisser "" sur tous les autres (un texte permanent tue l'effet).
"""

SCENARIO_NO_BEATS_NOTE = """
NOTE : Ne génère PAS de visual_beats pour les segments avec needs_voice true.
Les plans visuels seront générés automatiquement après la synthèse vocale (beat_planner_agent).
Concentre-toi sur narration_text, structure, mood, search_keywords, delivery_style.
"""
