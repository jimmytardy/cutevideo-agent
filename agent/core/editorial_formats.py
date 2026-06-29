from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent.core.config import load_agent_config


class EditorialFormatDefinition(BaseModel):
    """Format éditorial : structure scénario + profil montage + variation visuelle."""

    id: str
    label: str
    scenario_structure: str = ""
    intro_variants: list[str] = Field(default_factory=list)
    outro_variants: list[str] = Field(default_factory=list)
    montage_overrides: dict[str, Any] = Field(default_factory=dict)
    palette_presets: list[list[str]] = Field(default_factory=list)
    caption_style: dict[str, Any] = Field(default_factory=dict)
    thumbnail_style_hint: str = ""


class EditorialFormatRotationConfig(BaseModel):
    window_k: int = 3
    min_distinct_formats: int = 5


DEFAULT_EDITORIAL_FORMATS: list[EditorialFormatDefinition] = [
    EditorialFormatDefinition(
        id="enquete",
        label="Enquête",
        scenario_structure=(
            "Structure en 4 actes : (1) mystère / question ouverte, (2) indices et témoignages, "
            "(3) révélation progressive, (4) conclusion qui répond à la question initiale."
        ),
        intro_variants=["question-mystere", "fait-inexplicable", "temoignage-choc"],
        outro_variants=["reponse-claire", "piste-ouverte"],
        montage_overrides={"pacing": {"hook_transition": "fadeblack"}},
        palette_presets=[["#1a1a2e", "#16213e", "#0f3460"], ["#2d132c", "#801336", "#c72c41"]],
        caption_style={"primary_color": "#FFFFFF", "highlight_color": "#FF4444"},
        thumbnail_style_hint="mysterious noir atmosphere, dramatic shadows, investigative mood",
    ),
    EditorialFormatDefinition(
        id="liste-classement",
        label="Liste / Classement",
        scenario_structure=(
            "Structure countdown : intro annonce le classement, segments du N au 1 (ou 1 au N), "
            "chaque entrée = fait + preuve, outro récapitule le top 3."
        ),
        intro_variants=["compte-a-rebours", "stat-choc", "promesse-top"],
        outro_variants=["recap-top3", "surprise-numero1"],
        montage_overrides={"sfx": {"beat_cuts_enabled": True, "max_cues_per_minute": 14}},
        palette_presets=[["#FFD700", "#1a1a1a", "#FFFFFF"], ["#FF6B35", "#004E89", "#F7F7F7"]],
        caption_style={"primary_color": "#FFFFFF", "highlight_color": "#FFD700", "uppercase_highlight": True},
        thumbnail_style_hint="bold ranking visual, numbered energy, high contrast listicle style",
    ),
    EditorialFormatDefinition(
        id="mythe-vs-realite",
        label="Mythe vs Réalité",
        scenario_structure=(
            "Alternance mythe / réalité : segment 1 pose le mythe populaire, segments suivants "
            "démontent avec preuves, conclusion sépare croyance et faits."
        ),
        intro_variants=["mythe-populaire", "on-croit-que", "legend-urbaine"],
        outro_variants=["verdict-facts", "nuance-finale"],
        montage_overrides={"inter_segment_flash": True},
        palette_presets=[["#E63946", "#F1FAEE", "#1D3557"], ["#6A0572", "#AB83A1", "#F5F5F5"]],
        caption_style={"primary_color": "#F1FAEE", "highlight_color": "#E63946"},
        thumbnail_style_hint="split contrast myth vs fact, before-after visual tension",
    ),
    EditorialFormatDefinition(
        id="etude-de-cas",
        label="Étude de cas",
        scenario_structure=(
            "Zoom sur un cas concret : contexte, protagoniste, mécanisme, conséquences, leçon générale."
        ),
        intro_variants=["cas-concret", "personnage-cle", "situation-reelle"],
        outro_variants=["lecon-generale", "application-viewer"],
        montage_overrides={"pacing": {"hook_transition": "dissolve"}},
        palette_presets=[["#2C3E50", "#ECF0F1", "#3498DB"], ["#34495E", "#BDC3C7", "#E74C3C"]],
        caption_style={"primary_color": "#ECF0F1", "highlight_color": "#3498DB"},
        thumbnail_style_hint="case study focus, single subject hero shot, documentary realism",
    ),
    EditorialFormatDefinition(
        id="chronologie",
        label="Chronologie",
        scenario_structure=(
            "Narration temporelle : intro annonce la période, segments ordonnés chronologiquement, "
            "transitions datées, conclusion sur l'héritage ou la leçon."
        ),
        intro_variants=["date-cle", "avant-apres", "ligne-temps"],
        outro_variants=["heritage", "bilan-temporel"],
        montage_overrides={"pacing": {"mood_transitions": {"dramatique": "wiperight"}}},
        palette_presets=[["#8B4513", "#DEB887", "#2F4F4F"], ["#1B4332", "#40916C", "#D8F3DC"]],
        caption_style={"primary_color": "#FFFFFF", "highlight_color": "#DEB887"},
        thumbnail_style_hint="timeline aesthetic, historical sepia tones, era-evoking composition",
    ),
    EditorialFormatDefinition(
        id="questions-reponses",
        label="Questions-Réponses",
        scenario_structure=(
            "Format FAQ : intro pose 3-5 questions du public, un segment par question-réponse, "
            "outro invite à poser d'autres questions."
        ),
        intro_variants=["questions-viewers", "tu-te-demandes", "quiz-rapide"],
        outro_variants=["question-ouverte", "call-to-discuss"],
        montage_overrides={"sfx": {"text_pop_enabled": True}},
        palette_presets=[["#4361EE", "#7209B7", "#F72585"], ["#06D6A0", "#118AB2", "#073B4C"]],
        caption_style={"primary_color": "#FFFFFF", "highlight_color": "#4361EE"},
        thumbnail_style_hint="Q&A energy, question mark visual, engaging direct address",
    ),
]


def _parse_format(raw: dict[str, Any]) -> EditorialFormatDefinition | None:
    fmt_id = str(raw.get("id", "")).strip()
    if not fmt_id:
        return None
    return EditorialFormatDefinition(
        id=fmt_id,
        label=str(raw.get("label", fmt_id)),
        scenario_structure=str(raw.get("scenario_structure", "")),
        intro_variants=[str(v) for v in (raw.get("intro_variants") or [])],
        outro_variants=[str(v) for v in (raw.get("outro_variants") or [])],
        montage_overrides=dict(raw.get("montage_overrides") or {}),
        palette_presets=[
            [str(c) for c in colors]
            for colors in (raw.get("palette_presets") or [])
            if isinstance(colors, list)
        ],
        caption_style=dict(raw.get("caption_style") or {}),
        thumbnail_style_hint=str(raw.get("thumbnail_style_hint", "")),
    )


def resolve_editorial_formats(channel_overrides: dict[str, Any] | None = None) -> list[EditorialFormatDefinition]:
    """Banque de formats : defaults globaux + override chaîne (remplace par id)."""
    global_cfg = load_agent_config()
    global_editorial = global_cfg.get("editorial") or {}
    channel_editorial = (channel_overrides or {}).get("editorial") or {}

    raw_list = global_editorial.get("formats") or []
    if not raw_list:
        bank = list(DEFAULT_EDITORIAL_FORMATS)
    else:
        bank = [f for item in raw_list if (f := _parse_format(item)) is not None]

    channel_formats = channel_editorial.get("formats") or []
    if channel_formats:
        by_id = {f.id: f for f in bank}
        for item in channel_formats:
            parsed = _parse_format(item) if isinstance(item, dict) else None
            if parsed:
                by_id[parsed.id] = parsed
        bank = list(by_id.values())

    return bank or list(DEFAULT_EDITORIAL_FORMATS)


def resolve_format_rotation_config(channel_overrides: dict[str, Any] | None = None) -> EditorialFormatRotationConfig:
    global_cfg = load_agent_config()
    global_rot = (global_cfg.get("editorial") or {}).get("format_rotation") or {}
    channel_rot = ((channel_overrides or {}).get("editorial") or {}).get("format_rotation") or {}
    merged = {**global_rot, **channel_rot}
    return EditorialFormatRotationConfig(
        window_k=int(merged.get("window_k", 3)),
        min_distinct_formats=int(merged.get("min_distinct_formats", 5)),
    )


def get_format_by_id(
    format_id: str,
    channel_overrides: dict[str, Any] | None = None,
) -> EditorialFormatDefinition | None:
    fid = (format_id or "").strip()
    if not fid:
        return None
    for fmt in resolve_editorial_formats(channel_overrides):
        if fmt.id == fid:
            return fmt
    return None


def format_bank_summary(formats: list[EditorialFormatDefinition]) -> str:
    """Résumé compact pour le prompt content planner."""
    lines = [f"- {f.id} : {f.label}" for f in formats]
    return "\n".join(lines)
