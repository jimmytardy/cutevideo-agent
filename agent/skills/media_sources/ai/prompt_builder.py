from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VisualTypeEntry:
    template: str
    allows_text: bool = False
    editorial_tags: tuple[str, ...] = ()
    description_fr: str = ""


DIAGRAM_VISUAL_TYPES: frozenset[str] = frozenset({
    "scientific_diagram",
    "infographic",
    "data_chart",
    "cross_section",
    "timeline",
    "map",
    "quote_card",
    "statistic_highlight",
    "text_card",
    "headline_overlay",
    "battle_map",
    "versus_card",
    "lower_third",
    "countdown_timer",
    "ui_mockup",
    "microscope_view",
})

DIAGRAM_NO_TEXT_RULE = (
    "No text, no labels, no numbers, no letters anywhere. Icons, arrows and shapes only. "
    "No caption boxes, no title banner, no rectangular text placeholders. "
    "Clean illustration without annotation areas."
)

VISUAL_TYPE_FAMILIES: dict[str, list[str]] = {
    "SPORT": [
        "sports_action",
        "stadium_establishing",
        "sports_celebration",
        "athlete_portrait",
    ],
    "TRUE_CRIME": [
        "crime_documentary",
        "courtroom",
        "evidence_detail",
        "document_closeup",
    ],
    "ESPACE_SCIENCE": [
        "space_photo",
        "telescope_view",
        "laboratory_scene",
        "microscope_view",
        "scientific_diagram",
        "infographic",
        "data_chart",
        "comparison",
        "cross_section",
    ],
    "ART_HISTOIRE": [
        "artwork",
        "museum_interior",
        "historical_artifact",
        "portrait_historical",
        "battle_map",
        "period_reenactment",
        "archival_footage",
        "timeline",
        "map",
    ],
    "NATURE": [
        "wildlife_action",
        "macro_detail",
        "underwater",
        "weather_phenomenon",
        "habitat_wide",
        "aerial",
        "establishing_shot",
    ],
    "DOCUMENTAIRE": [
        "documentary_photo",
        "pov",
        "press_photo",
        "news_broll",
        "reaction_shot",
        "crowd_scene",
        "before_after",
        "split_screen",
        "metaphor_visual",
        "abstract_mood",
    ],
    "ACTUALITE_POLITIQUE": [
        "protest_scene",
        "political_figure",
        "institution_building",
        "quote_card",
        "statistic_highlight",
        "headline_overlay",
    ],
    "HUMOUR": [
        "meme_template",
        "cartoon",
        "satirical_illustration",
        "exaggerated_reaction",
        "visual_pun",
    ],
    "TECH_FINANCE_LIFESTYLE": [
        "product_shot",
        "office_workspace",
        "money_finance",
        "food_closeup",
        "cooking_action",
    ],
    "OVERLAYS": [
        "ui_mockup",
        "versus_card",
        "lower_third",
        "countdown_timer",
        "text_card",
    ],
}

VISUAL_TYPE_REGISTRY: dict[str, VisualTypeEntry] = {
    # Documentaire / nature
    "documentary_photo": VisualTypeEntry(
        "Documentary photorealistic photograph, natural lighting, high detail. Subject: {subject}.",
        editorial_tags=("documentaire", "nature", "animaux", "histoire", "science"),
        description_fr="Photo documentaire réaliste",
    ),
    "archival_footage": VisualTypeEntry(
        "Historical archival photograph or film still, aged texture, authentic period look. Subject: {subject}.",
        editorial_tags=("histoire", "documentaire", "france"),
        description_fr="Archive historique, texture d'époque",
    ),
    "establishing_shot": VisualTypeEntry(
        "Wide cinematic establishing shot, landscape or location context. Subject: {subject}.",
        editorial_tags=("documentaire", "nature", "geographie"),
        description_fr="Plan large d'ambiance, lieu ou paysage",
    ),
    "aerial": VisualTypeEntry(
        "Aerial drone view, high altitude perspective. Subject: {subject}.",
        editorial_tags=("nature", "geographie", "documentaire"),
        description_fr="Vue aérienne, drone",
    ),
    "macro_detail": VisualTypeEntry(
        "Extreme macro close-up, shallow depth of field, texture detail. Subject: {subject}.",
        editorial_tags=("nature", "animaux", "science"),
        description_fr="Gros plan macro, détail de texture",
    ),
    "wildlife_action": VisualTypeEntry(
        "Dynamic wildlife action shot, motion, natural habitat. Subject: {subject}.",
        editorial_tags=("animaux", "nature", "documentaire"),
        description_fr="Animal en action dans son habitat",
    ),
    "pov": VisualTypeEntry(
        "First-person point of view perspective shot, immersive angle. Subject: {subject}.",
        editorial_tags=("documentaire", "animaux", "nature", "sport"),
        description_fr="Vue subjective, immersion première personne",
    ),
    "underwater": VisualTypeEntry(
        "Underwater scene, marine life, reef or deep ocean. Subject: {subject}.",
        editorial_tags=("nature", "animaux", "documentaire"),
        description_fr="Scène sous-marine, récif ou fond marin",
    ),
    "weather_phenomenon": VisualTypeEntry(
        "Dramatic weather phenomenon, storm, aurora or natural disaster sky. Subject: {subject}.",
        editorial_tags=("nature", "science", "documentaire"),
        description_fr="Phénomène météo (orage, aurore, catastrophe)",
    ),
    "habitat_wide": VisualTypeEntry(
        "Wide ecosystem habitat shot, forest, savanna or biome context. Subject: {subject}.",
        editorial_tags=("nature", "animaux", "geographie"),
        description_fr="Écosystème large (forêt, savane, biome)",
    ),
    # Sport
    "sports_action": VisualTypeEntry(
        "Dynamic sports action photograph, match moment, athletic motion. Subject: {subject}.",
        editorial_tags=("sport", "divertissement"),
        description_fr="Action de match (but, dribble, plaquage)",
    ),
    "stadium_establishing": VisualTypeEntry(
        "Sports stadium establishing shot, pitch, stands, pre-match atmosphere. Subject: {subject}.",
        editorial_tags=("sport", "divertissement"),
        description_fr="Stade, pelouse, ambiance avant match",
    ),
    "sports_celebration": VisualTypeEntry(
        "Sports celebration moment, cheering crowd, victory joy. Subject: {subject}.",
        editorial_tags=("sport", "divertissement"),
        description_fr="Célébration sportive, joie, tribune",
    ),
    "athlete_portrait": VisualTypeEntry(
        "Athletic portrait, player or coach in sports context. Subject: {subject}.",
        editorial_tags=("sport", "divertissement"),
        description_fr="Portrait sportif, joueur ou entraîneur",
    ),
    # True crime
    "crime_documentary": VisualTypeEntry(
        "Crime documentary atmosphere, investigation mood, non-graphic noir tone. Subject: {subject}.",
        editorial_tags=("true_crime", "documentaire"),
        description_fr="Ambiance enquête (non graphique)",
    ),
    "courtroom": VisualTypeEntry(
        "Courtroom interior, judge bench, legal proceedings atmosphere. Subject: {subject}.",
        editorial_tags=("true_crime", "documentaire", "politique"),
        description_fr="Tribunal, audience, juge",
    ),
    "evidence_detail": VisualTypeEntry(
        "Investigation evidence detail, case file, forensic object on table, non-graphic. Subject: {subject}.",
        editorial_tags=("true_crime", "documentaire"),
        description_fr="Objet ou dossier de preuve (non sanglant)",
    ),
    "document_closeup": VisualTypeEntry(
        "Close-up of newspaper article, police report or archival document. Subject: {subject}.",
        editorial_tags=("true_crime", "histoire", "documentaire"),
        description_fr="Article, rapport ou coupure de presse",
    ),
    # Espace / science
    "space_photo": VisualTypeEntry(
        "Space photography, planet, nebula, cosmos or spacecraft. Subject: {subject}.",
        editorial_tags=("science", "documentaire"),
        description_fr="Planète, nébuleuse, cosmos",
    ),
    "telescope_view": VisualTypeEntry(
        "Observatory telescope, stargazing, night sky observation. Subject: {subject}.",
        editorial_tags=("science", "documentaire"),
        description_fr="Observatoire, télescope, ciel nocturne",
    ),
    "laboratory_scene": VisualTypeEntry(
        "Science laboratory scene, experiment setup, glassware and equipment. Subject: {subject}.",
        editorial_tags=("science", "education", "documentaire"),
        description_fr="Laboratoire, expérience, verrerie",
    ),
    "microscope_view": VisualTypeEntry(
        "Microscopic view illustration, cells or micro-organisms, scientific. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("science", "education"),
        description_fr="Vue microscopique, cellules",
    ),
    "scientific_diagram": VisualTypeEntry(
        "Educational scientific cross-section diagram with arrows showing process flow, dark background, clean illustration without annotation areas. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("science", "documentaire", "education"),
        description_fr="Schéma scientifique avec flux et flèches",
    ),
    "infographic": VisualTypeEntry(
        "Clean modern infographic illustration, vector style, clean illustration without annotation areas. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("science", "education", "documentaire"),
        description_fr="Infographie moderne épurée",
    ),
    "data_chart": VisualTypeEntry(
        "Clear data visualization chart or graph, professional presentation, no axis text. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("science", "actualite", "politique", "education", "finance"),
        description_fr="Graphique ou tableau de données",
    ),
    "comparison": VisualTypeEntry(
        "Split-screen before and after comparison, side by side. Subject: {subject}.",
        editorial_tags=("science", "documentaire", "education"),
        description_fr="Comparaison avant/après côte à côte",
    ),
    "timeline": VisualTypeEntry(
        "Horizontal timeline illustration showing chronological events. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("histoire", "documentaire", "science"),
        description_fr="Frise chronologique horizontale",
    ),
    "map": VisualTypeEntry(
        "Geographic map illustration highlighting relevant location. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("histoire", "geographie", "politique", "actualite"),
        description_fr="Carte géographique avec lieu mis en avant",
    ),
    "cross_section": VisualTypeEntry(
        "Technical cross-section cutaway illustration, clean illustration without annotation areas. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("science", "documentaire"),
        description_fr="Coupe technique en éclaté",
    ),
    "battle_map": VisualTypeEntry(
        "Military battle map illustration, fronts and troop movements. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("histoire", "documentaire"),
        description_fr="Carte militaire, front, bataille",
    ),
    # Art / histoire
    "artwork": VisualTypeEntry(
        "Museum artwork photograph, painting or sculpture masterpiece. Subject: {subject}.",
        editorial_tags=("art", "histoire", "culture"),
        description_fr="Tableau, sculpture, œuvre d'art",
    ),
    "museum_interior": VisualTypeEntry(
        "Museum gallery interior, exhibition hall with artworks. Subject: {subject}.",
        editorial_tags=("art", "histoire", "culture"),
        description_fr="Salle de musée, exposition",
    ),
    "historical_artifact": VisualTypeEntry(
        "Historical archaeological artifact, ancient object or relic. Subject: {subject}.",
        editorial_tags=("histoire", "art", "culture"),
        description_fr="Objet archéologique, relique",
    ),
    "portrait_historical": VisualTypeEntry(
        "Historical portrait, engraving or period painting of a figure. Subject: {subject}.",
        editorial_tags=("histoire", "documentaire", "france"),
        description_fr="Portrait de personnage historique",
    ),
    "period_reenactment": VisualTypeEntry(
        "Historical reenactment scene, period costumes and setting. Subject: {subject}.",
        editorial_tags=("histoire", "documentaire"),
        description_fr="Reconstitution historique",
    ),
    # Actualité / politique
    "news_broll": VisualTypeEntry(
        "News broadcast B-roll footage style, photorealistic, journalistic. Subject: {subject}.",
        editorial_tags=("actualite", "politique", "documentaire", "sport"),
        description_fr="B-roll journalistique, style JT",
    ),
    "press_photo": VisualTypeEntry(
        "Press photography, photojournalism style, candid moment. Subject: {subject}.",
        editorial_tags=("actualite", "politique", "histoire", "sport"),
        description_fr="Photo de presse, photojournalisme",
    ),
    "protest_scene": VisualTypeEntry(
        "Crowd protest or public demonstration scene, documentary style. Subject: {subject}.",
        editorial_tags=("politique", "actualite", "histoire"),
        description_fr="Manifestation, foule en protestation",
    ),
    "political_figure": VisualTypeEntry(
        "Portrait of public figure in official or press context. Subject: {subject}.",
        editorial_tags=("politique", "actualite", "histoire"),
        description_fr="Portrait de personnalité politique",
    ),
    "institution_building": VisualTypeEntry(
        "Government or institutional building exterior, architectural photography. Subject: {subject}.",
        editorial_tags=("politique", "histoire", "france"),
        description_fr="Bâtiment institutionnel, architecture officielle",
    ),
    "quote_card": VisualTypeEntry(
        "Quote card design with bold typography on clean background. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("politique", "actualite", "documentaire"),
        description_fr="Carte citation, typographie forte",
    ),
    "statistic_highlight": VisualTypeEntry(
        "Bold statistic highlight card, large number emphasis. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("science", "actualite", "politique", "documentaire", "finance"),
        description_fr="Carte chiffre clé mis en avant",
    ),
    # Humour / satire
    "meme_template": VisualTypeEntry(
        "Internet meme template style image, humorous composition. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("humour", "divertissement"),
        description_fr="Template mème internet",
    ),
    "cartoon": VisualTypeEntry(
        "Cartoon illustration, expressive characters, vibrant colors. Subject: {subject}.",
        editorial_tags=("humour", "divertissement", "education"),
        description_fr="Illustration cartoon colorée",
    ),
    "satirical_illustration": VisualTypeEntry(
        "Satirical editorial illustration, exaggerated features. Subject: {subject}.",
        editorial_tags=("humour", "politique", "actualite"),
        description_fr="Illustration satirique éditoriale",
    ),
    "exaggerated_reaction": VisualTypeEntry(
        "Exaggerated comedic reaction shot, expressive face or gesture. Subject: {subject}.",
        editorial_tags=("humour", "divertissement"),
        description_fr="Réaction comique exagérée",
    ),
    "visual_pun": VisualTypeEntry(
        "Visual pun or clever literal interpretation, humorous concept. Subject: {subject}.",
        editorial_tags=("humour", "divertissement"),
        description_fr="Jeu de mots visuel, calembour",
    ),
    # Émotion / narration
    "reaction_shot": VisualTypeEntry(
        "Human reaction shot, emotional expression, cinematic. Subject: {subject}.",
        editorial_tags=("documentaire", "divertissement", "sport"),
        description_fr="Plan réaction humaine, émotion",
    ),
    "crowd_scene": VisualTypeEntry(
        "Crowd scene, many people, public event atmosphere. Subject: {subject}.",
        editorial_tags=("histoire", "actualite", "politique", "sport"),
        description_fr="Foule, événement public",
    ),
    "abstract_mood": VisualTypeEntry(
        "Abstract atmospheric mood image, colors and light evoking emotion. Subject: {subject}.",
        editorial_tags=("art", "documentaire"),
        description_fr="Ambiance abstraite, émotion par la lumière",
    ),
    "metaphor_visual": VisualTypeEntry(
        "Visual metaphor illustration, symbolic representation. Subject: {subject}.",
        editorial_tags=("documentaire", "science", "humour"),
        description_fr="Métaphore visuelle, symbole",
    ),
    "before_after": VisualTypeEntry(
        "Before and after transformation visual. Subject: {subject}.",
        editorial_tags=("science", "documentaire", "nature"),
        description_fr="Transformation avant/après",
    ),
    # Tech / finance / lifestyle
    "product_shot": VisualTypeEntry(
        "Product photography, tech gadget or consumer object on clean background. Subject: {subject}.",
        editorial_tags=("tech", "finance", "documentaire"),
        description_fr="Photo produit, gadget ou objet",
    ),
    "office_workspace": VisualTypeEntry(
        "Modern office workspace, meeting room or laptop desk scene. Subject: {subject}.",
        editorial_tags=("tech", "finance", "psychologie"),
        description_fr="Bureau, réunion, laptop",
    ),
    "money_finance": VisualTypeEntry(
        "Finance context visual, currency, trading floor mood without readable text. Subject: {subject}.",
        editorial_tags=("finance", "documentaire"),
        description_fr="Contexte finance (sans texte lisible)",
    ),
    "food_closeup": VisualTypeEntry(
        "Food close-up photography, dish or ingredient detail. Subject: {subject}.",
        editorial_tags=("cuisine", "divertissement", "documentaire"),
        description_fr="Gros plan plat ou ingrédient",
    ),
    "cooking_action": VisualTypeEntry(
        "Cooking action shot, hands preparing food, flame or kitchen motion. Subject: {subject}.",
        editorial_tags=("cuisine", "divertissement"),
        description_fr="Mains en cuisine, flamme, préparation",
    ),
    # Texte / overlay
    "text_card": VisualTypeEntry(
        "Minimal text card on solid background for video overlay. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("documentaire", "education", "actualite"),
        description_fr="Carte texte minimaliste pour overlay",
    ),
    "headline_overlay": VisualTypeEntry(
        "News headline style overlay background, bold typography area. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("actualite", "politique"),
        description_fr="Fond style titre de une",
    ),
    "split_screen": VisualTypeEntry(
        "Split screen composition showing two related visuals side by side. Subject: {subject}.",
        editorial_tags=("documentaire", "science", "comparaison"),
        description_fr="Écran partagé, deux visuels côte à côte",
    ),
    "ui_mockup": VisualTypeEntry(
        "App user interface mockup, dashboard or mobile screen layout. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("tech", "education"),
        description_fr="Maquette interface app ou dashboard",
    ),
    "versus_card": VisualTypeEntry(
        "Versus comparison card layout, A vs B split design. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("sport", "divertissement", "education"),
        description_fr="Carte comparaison A vs B",
    ),
    "lower_third": VisualTypeEntry(
        "Broadcast lower third title bar design area at bottom of frame. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("actualite", "documentaire", "sport"),
        description_fr="Bandeau nom/titre bas d'écran",
    ),
    "countdown_timer": VisualTypeEntry(
        "Suspense countdown timer visual, dramatic timing graphic. Subject: {subject}.",
        allows_text=True,
        editorial_tags=("divertissement", "sport", "true_crime"),
        description_fr="Décompte, suspense chronomètre",
    ),
    "custom": VisualTypeEntry(
        "{style_hint}. Subject: {subject}.",
        allows_text=True,
        editorial_tags=(),
        description_fr="Type non listé — style_hint obligatoire",
    ),
}


# Bloc cinématographie injecté par famille (objectif, lumière, palette, profondeur).
# Suit les bonnes pratiques FLUX : décrire lumière/objectif/grade plutôt que des mots-clés.
_FAMILY_CINEMATOGRAPHY: dict[str, str] = {
    "SPORT": "shot on telephoto 200mm, fast shutter freezing motion, stadium floodlights, vivid saturated colors, dynamic angle",
    "TRUE_CRIME": "35mm lens, low-key chiaroscuro lighting, desaturated muted palette, shallow depth of field, somber tense mood",
    "ESPACE_SCIENCE": "ultra-detailed, deep contrast, cool blue and teal tones, crisp clarity, dramatic rim light",
    "ART_HISTOIRE": "soft directional museum lighting, warm amber tones, fine surface texture, archival authentic look",
    "NATURE": "natural daylight, golden hour warmth, high dynamic range, rich greens and earth tones, shallow depth of field",
    "DOCUMENTAIRE": "35mm lens, natural available light, neutral realistic color grade, shallow depth of field, cinematic framing",
    "ACTUALITE_POLITIQUE": "photojournalistic, natural light, candid moment, neutral balanced tones, documentary realism",
    "HUMOUR": "bright high-key lighting, bold vivid colors, playful exaggerated composition",
    "TECH_FINANCE_LIFESTYLE": "clean studio lighting, soft shadows, modern minimal palette, shallow depth of field, crisp product detail",
}
_DEFAULT_CINEMATOGRAPHY = (
    "cinematic lighting, balanced composition, natural color grade, shallow depth of field, sharp focus"
)

_FAMILY_OF_TYPE: dict[str, str] = {}
for _family_name, _family_types in VISUAL_TYPE_FAMILIES.items():
    for _vtype in _family_types:
        _FAMILY_OF_TYPE.setdefault(_vtype, _family_name)


def _cinematography_for(visual_type: str) -> str:
    family = _FAMILY_OF_TYPE.get(visual_type, "")
    return _FAMILY_CINEMATOGRAPHY.get(family, _DEFAULT_CINEMATOGRAPHY)


def _all_catalog_types() -> list[str]:
    """Tous les types du registre sauf custom, dans l'ordre des familles."""
    ordered: list[str] = []
    seen: set[str] = set()
    for types in VISUAL_TYPE_FAMILIES.values():
        for vtype in types:
            if vtype in VISUAL_TYPE_REGISTRY and vtype not in seen:
                ordered.append(vtype)
                seen.add(vtype)
    for vtype in sorted(VISUAL_TYPE_REGISTRY):
        if vtype != "custom" and vtype not in seen:
            ordered.append(vtype)
    return ordered


def _is_recommended_for_channel(
    vtype: str,
    tone: str,
    category: str,
) -> bool:
    tags = editorial_tags_for_type(vtype)
    if not tags:
        return False
    for tag in tags:
        if tag in tone or tag in category:
            return True
        if category and category in tag:
            return True
    return False


def is_known_visual_type(visual_type: str) -> bool:
    return visual_type in VISUAL_TYPE_REGISTRY


def is_diagram_visual_type(visual_type: str) -> bool:
    return visual_type in DIAGRAM_VISUAL_TYPES


def list_visual_types() -> list[str]:
    return _all_catalog_types()


def editorial_tags_for_type(visual_type: str) -> tuple[str, ...]:
    entry = VISUAL_TYPE_REGISTRY.get(visual_type)
    return entry.editorial_tags if entry else ()


def description_for_type(visual_type: str) -> str:
    entry = VISUAL_TYPE_REGISTRY.get(visual_type)
    return entry.description_fr if entry else ""


def build_visual_type_catalog(
    editorial_tone: str = "",
    theme_category: str = "",
) -> str:
    """Catalogue exhaustif pour les prompts LLM (ScenarioAgent, RevisionAgent)."""
    return format_type_catalog(editorial_tone, theme_category)


def format_type_catalog(editorial_tone: str = "", theme_category: str = "") -> str:
    tone = (editorial_tone or "").lower()
    category = (theme_category or "").lower()
    lines = [
        "CATALOGUE visual_type — utiliser UNIQUEMENT ces clés exactes :",
        "",
    ]

    assigned: set[str] = set()
    for family_name, family_types in VISUAL_TYPE_FAMILIES.items():
        valid = [t for t in family_types if t in VISUAL_TYPE_REGISTRY and t != "custom"]
        if not valid:
            continue
        valid.sort(
            key=lambda t: (
                0 if _is_recommended_for_channel(t, tone, category) else 1,
                t,
            )
        )
        has_star = any(_is_recommended_for_channel(t, tone, category) for t in valid)
        header = f"{family_name}" + (" (*)" if has_star else "")
        lines.append(header)
        for vtype in valid:
            desc = description_for_type(vtype)
            star = " *" if _is_recommended_for_channel(vtype, tone, category) else ""
            lines.append(f"- {vtype}{star} : {desc}")
            assigned.add(vtype)
        lines.append("")

    orphan = [t for t in _all_catalog_types() if t not in assigned]
    if orphan:
        lines.append("AUTRES")
        for vtype in orphan:
            desc = description_for_type(vtype)
            star = " *" if _is_recommended_for_channel(vtype, tone, category) else ""
            lines.append(f"- {vtype}{star} : {desc}")
        lines.append("")

    lines.append("- custom : Type non listé — style_hint obligatoire")
    lines.append("(* = recommandé pour le ton/catégorie de cette chaîne)")
    return "\n".join(lines)


def build_visual_prompt(
    visual_type: str,
    subject: str,
    *,
    style_hint: str = "",
    theme_category: str = "",
    editorial_tone: str = "",
    aspect_ratio: str = "16:9",
    style_block: str = "",
) -> str:
    """Compose un prompt FLUX en menant par le sujet (FLUX pondère le début du prompt).

    Ordre : sujet → descripteur du visual_type → cinématographie → style bible →
    cadrage → thème/ton → qualité → contraintes texte.
    """
    key = visual_type if visual_type in VISUAL_TYPE_REGISTRY else "custom"
    entry = VISUAL_TYPE_REGISTRY[key]
    orientation = (
        "portrait 9:16 vertical framing"
        if aspect_ratio == "9:16"
        else "landscape 16:9 horizontal framing"
    )

    subject_lead = (subject or "").strip().rstrip(".")

    # Descripteur du type sans la mention "Subject: ..." pour ne pas répéter le sujet en milieu.
    rendered = entry.template.format(subject=subject, style_hint=style_hint or subject)
    descriptor = rendered.replace(f"Subject: {subject}.", "").replace(f"Subject: {subject}", "")
    descriptor = descriptor.strip().rstrip(".").strip()

    is_diagram = key in DIAGRAM_VISUAL_TYPES
    text_rule = DIAGRAM_NO_TEXT_RULE if is_diagram else "No text, no watermark, no logo, no caption."

    # P1 — FLUX 2 (encodeur Mistral) sort net par défaut : pas de tag qualité ("high quality,
    # sharp focus…") ni de descripteur abstrait non rendu ("Theme: …. Tone: …"). On réserve le
    # budget de tokens à la description de scène concrète (sujet + cinématographie + style block).
    # Réf. : guide officiel Black Forest Labs (docs.bfl.ml/guides/prompting_guide_flux2).
    parts: list[str] = [subject_lead] if subject_lead else []
    if descriptor:
        parts.append(descriptor)
    if not is_diagram:
        parts.append(_cinematography_for(key))
    if style_block.strip():
        parts.append(style_block.strip().rstrip("."))
    parts.append(orientation)
    if is_diagram:
        # Pour les schémas, "clean / lisible" oriente utilement la composition (pas un tag qualité).
        parts.append("clean, clear readable composition")
    prompt = ". ".join(p for p in parts if p) + f". {text_rule} No collage."
    return prompt[:4000]


def build_documentary_prompt(
    prompt: str,
    *,
    theme_category: str = "",
    editorial_tone: str = "",
    aspect_ratio: str = "16:9",
    style_block: str = "",
) -> str:
    return build_visual_prompt(
        "documentary_photo",
        prompt,
        theme_category=theme_category,
        editorial_tone=editorial_tone,
        aspect_ratio=aspect_ratio,
        style_block=style_block,
    )
