"""Contrats des fichiers échangés entre les rôles Claude Studio et le runner Python.

Chaque rôle écrit un fichier JSON dans le run dir ; les outils (`studio.tools`)
et le runner (`agent.core.claude_studio`) les valident avec ces modèles pour
renvoyer des erreurs explicites à Claude plutôt que d'échouer plus loin.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

# Rôles auxquels la critique peut demander des changements (la miniature n'est pas critiquée).
Role = Literal["scenariste", "voix", "monteur"]
Motion = Literal["zoom", "pan_left", "pan_right", "static"]
# Style visuel d'une chaîne (réglages → Général), imposé au scénario par `allowed_visual_modes()`.
# motion3d : plans clés en 3D (studio3d.js), réservé aux abonnements qui l'autorisent ; auto : Claude choisit
# le style par vidéo (la 3D comprise si l'abonnement l'autorise).
VisualStyle = Literal["animation", "mixed", "realistic", "motion3d", "auto"]
VISUAL_STYLES: tuple[str, ...] = ("animation", "mixed", "realistic", "motion3d", "auto")
# Styles où la 3D peut servir (si l'abonnement l'autorise et que les animations ne sont pas coupées).
MOTION3D_STYLES: tuple[str, ...] = ("motion3d", "auto")
# Préfixe de `visual_intent` qui désigne un plan 3D (exigé au moins une fois en style motion3d).
MOTION3D_BEAT_PREFIX = "3D"
# Débit de voix conseillé (mots/s), réglable par chaîne (`production.words_per_second`) : repère pour le
# scénariste, la voix et les analyses, jamais un critère bloquant.
DEFAULT_WORDS_PER_SECOND = 3.1
MIN_WORDS_PER_SECOND = 2.0
MAX_WORDS_PER_SECOND = 4.0


def clamp_words_per_second(value: Any) -> float:
    """Débit conseillé ramené dans ses bornes ; une valeur absente ou invalide donne le défaut."""
    try:
        wps = float(value)
    except (TypeError, ValueError):
        return DEFAULT_WORDS_PER_SECOND
    if not math.isfinite(wps):
        return DEFAULT_WORDS_PER_SECOND
    return round(min(max(wps, MIN_WORDS_PER_SECOND), MAX_WORDS_PER_SECOND), 2)
TextPosition = Literal["top", "center", "bottom"]
Sfx = Literal["", "whoosh", "pop", "ding", "click", "riser", "impact"]

# Tolérance (s) entre la fin de la timeline et la durée de la voix.
TIMELINE_DURATION_TOLERANCE_S = 0.5


class Brief(BaseModel):
    """Commande de production écrite par le runner (ou `studio.run`)."""

    theme: str
    niche: str = ""
    angle: str = ""
    language: str = "fr"
    target_duration_s: int = Field(default=45, ge=10, le=180)
    # Débit conseillé de la chaîne (mots/s) : repère, pas une contrainte.
    words_per_second: float = Field(default=DEFAULT_WORDS_PER_SECOND, ge=MIN_WORDS_PER_SECOND, le=MAX_WORDS_PER_SECOND)
    voice: str = ""
    tts_engine: str = ""
    # Boucle vidéo (monteur ⇄ critique) : plafond et seuil de `critique_N.json`.
    max_iterations: int = Field(default=5, ge=1, le=6)
    min_score: int = Field(default=80, ge=0, le=100)
    # Boucle scénario (scénariste ⇄ critique-scenario) : plafond et seuil de `scenario_critique_N.json`.
    max_scenario_iterations: int = Field(default=5, ge=1, le=6)
    min_scenario_score: int = Field(default=90, ge=0, le=100)
    editorial_tone: str = ""
    # Brief créatif de la chaîne (réglages → Général) : ton, style narratif, interdits éditoriaux.
    creative_brief: str = ""
    content_plan: dict | None = None
    # Animations autorisées : off | templates (modèles intégrés) | scripts (scripts jetables + modèles).
    animations: Literal["off", "templates", "scripts"] = "scripts"
    # Style visuel de la chaîne : animation (kit), mixed (images réelles + animations), realistic (images réelles),
    # motion3d (plans clés en 3D), auto (au choix de Claude).
    visual_style: VisualStyle = "animation"
    # Rendus 3D autorisés pour ce Short (abonnement ∧ style motion3d/auto ∧ animations) : `motion3d_enabled()`.
    motion3d: bool = False
    # Images IA autorisées pour ce Short (0 = désactivées par la chaîne ou l'abonnement ;
    # None = plafond plateforme STUDIO_MAX_AI_IMAGES).
    max_ai_images: int | None = Field(default=None, ge=0)
    # Modèles d'image IA que `ai-image --model` accepte (le premier = défaut) : plan de la chaîne
    # et modèles moins chers (`models_up_to`). Vide = défaut plateforme `flux_2_dev`.
    ai_models: list[str] = Field(default_factory=list)


class ScenarioBeat(BaseModel):
    text: str = Field(min_length=1)
    visual_intent: str = ""
    on_screen_text: str = ""


class PublishMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    # YouTube : 2-3 phrases orientées recherche (hashtags et crédits ajoutés à la publication).
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    # Légendes dédiées (hashtags ajoutés à la publication) : TikTok = accroche courte qui donne envie de
    # regarder jusqu'au bout ; Instagram = 1-2 phrases + question pour faire commenter. Vides → repli
    # sur le titre (TikTok) / la description (Instagram).
    tiktok_caption: str = Field(default="", max_length=150)
    instagram_caption: str = Field(default="", max_length=2000)


class ScenarioSource(BaseModel):
    """Fait du script vérifié sur le web par le scénariste."""

    claim: str = Field(min_length=1)
    url: str = Field(min_length=1)
    checked: bool = True


class Scenario(BaseModel):
    title: str = Field(min_length=1)
    hook: str = Field(min_length=1)
    beats: list[ScenarioBeat] = Field(min_length=1)
    cta: str = ""
    mood: str = ""
    music_mood: str = ""
    # Direction visuelle commune à toute la vidéo (charte anim/lib/studio.js).
    visual_mode: Literal["animation", "mixed", "footage"] = "animation"
    theme: str = "night"
    accent: str = ""
    # Historique : la fiche de publication est désormais `publish.json`, écrite par le miniaturiste après la boucle
    # (anciens run dirs : lue ici en repli).
    publish: PublishMetadata | None = None
    sources: list[ScenarioSource] = Field(default_factory=list)

    @property
    def narration(self) -> str:
        return " ".join(b.text.strip() for b in self.beats if b.text.strip())


class TimelineClip(BaseModel):
    media: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    motion: Motion = "zoom"
    video_offset: float = Field(default=0.0, ge=0)
    text: str = ""
    text_position: TextPosition = "top"
    # Bruitage synthétique joué au début du clip (riser : se termine au début du clip).
    sfx: Sfx = ""

    @model_validator(mode="after")
    def _ordered(self) -> TimelineClip:
        if self.end <= self.start:
            raise ValueError(f"clip {self.media}: end ({self.end}) <= start ({self.start})")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class Timeline(BaseModel):
    voice: str = "voice.wav"
    words: str = "words.json"
    music: str | None = None
    music_volume: float = Field(default=0.08, ge=0, le=0.5)
    subtitles: bool = True
    # Mots surlignés en couleur d'accent dans les sous-titres (les nombres le sont toujours).
    subtitle_keywords: list[str] = Field(default_factory=list)
    # Centre du texte : high ≈ 67 % de la hauteur (hors interface TikTok), center, low.
    subtitle_position: Literal["high", "center", "low"] = "high"
    clips: list[TimelineClip] = Field(min_length=1)

    @model_validator(mode="after")
    def _contiguous(self) -> Timeline:
        clips = self.clips
        if abs(clips[0].start) > 0.05:
            raise ValueError(f"le premier clip doit commencer à 0 (start={clips[0].start})")
        for prev, cur in zip(clips, clips[1:]):
            if abs(cur.start - prev.end) > 0.05:
                raise ValueError(
                    f"trou ou chevauchement entre {prev.media} (end={prev.end}) "
                    f"et {cur.media} (start={cur.start}) : les clips doivent se suivre"
                )
        return self

    @property
    def duration(self) -> float:
        return self.clips[-1].end


class RequestedChange(BaseModel):
    role: Role
    instruction: str = Field(min_length=1)
    # Rôle `voix` : lignes de narration.txt à resynthétiser (1 = première ligne) ; les autres sont réutilisées.
    lines: list[int] = Field(default_factory=list)

    @field_validator("lines")
    @classmethod
    def _line_numbers(cls, lines: list[int]) -> list[int]:
        if any(n < 1 for n in lines):
            raise ValueError("lines : numéros de ligne à partir de 1 (1 = première ligne de narration.txt)")
        if len(set(lines)) != len(lines):
            raise ValueError("lines : numéros en double")
        return lines


class ScenarioCritique(BaseModel):
    """Analyse du script avant la voix (`scenario_critique_N.json`)."""

    iteration: int = Field(ge=1)
    score: int = Field(ge=0, le=100)
    decision: Literal["approve", "iterate"]
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    # Faits que le scénariste doit vérifier sur le web (ou retirer).
    unverified_claims: list[str] = Field(default_factory=list)
    # Instructions pour le scénariste, localisées (« beat 4 : … »).
    changes: list[str] = Field(default_factory=list)
    # Notes par critère (hook, structure, valeur_verite, oralite, duree, chute_boucle, brief).
    scores: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _changes_when_iterating(self) -> ScenarioCritique:
        if self.decision == "iterate" and not (self.changes or self.unverified_claims):
            raise ValueError("decision=iterate exige au moins un élément dans changes ou unverified_claims")
        return self


class Critique(BaseModel):
    iteration: int = Field(ge=1)
    video: str
    score: int = Field(ge=0, le=100)
    decision: Literal["approve", "iterate"]
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    changes: list[RequestedChange] = Field(default_factory=list)
    # Notes par critère de la grille virale (hook, retention, valeur, visuels, voix_son, sous_titres, chute_partage).
    scores: dict[str, int] = Field(default_factory=dict)
    # Résumé de `analyze` : {"source": "gemini"|"gemini-vertex"|"claude", "path": "review/vN/analysis/analysis.json", "flags": […]}.
    analysis: dict | None = None

    @model_validator(mode="after")
    def _changes_when_iterating(self) -> Critique:
        if self.decision == "iterate" and not self.changes:
            raise ValueError("decision=iterate exige au moins un élément dans changes")
        if any(c.role == "scenariste" for c in self.changes):
            raise ValueError(
                "le scénario est déjà validé (scenario_critique) : la critique vidéo ne s'adresse qu'à "
                "`monteur` ou `voix` (avec `lines`)"
            )
        if any(c.role == "voix" and not c.lines for c in self.changes):
            raise ValueError("un changement `voix` exige `lines` (numéros de ligne de narration.txt à refaire)")
        return self


class Thumbnail(BaseModel):
    vertical: str
    horizontal: str | None = None
    text: str = ""
    background: str = ""


class StudioResult(BaseModel):
    status: Literal["approved", "max_iterations", "failed"]
    iterations: int = Field(ge=0)
    final_video: str | None = None
    notes: str = ""


ModelT = TypeVar("ModelT", bound=BaseModel)


def motion3d_enabled(visual_style: str, animations: str, allowed: bool) -> bool:
    """La 3D sert-elle à ce Short : droit d'abonnement, style qui la prévoit, animations actives."""
    return allowed and visual_style in MOTION3D_STYLES and animations != "off"


def allowed_visual_modes(visual_style: str, animations: str) -> tuple[str, ...]:
    """`scenario.visual_mode` autorisés par le style visuel de la chaîne et la politique d'animations.

    La 3D n'est pas un `visual_mode` : ses plans sont des animations (beats « 3D : … »), d'où motion3d → animation
    ou mixed, et auto → au choix comme animation.
    """
    if animations == "off":
        return ("footage",)
    if visual_style == "mixed":
        return ("mixed",)
    if visual_style == "realistic":
        return ("footage", "mixed")
    if visual_style == "motion3d":
        return ("animation", "mixed")
    return ("animation", "mixed", "footage")  # animation, auto (ou style inconnu) : au choix


_MOTION3D_BEAT = re.compile(rf"^\s*{MOTION3D_BEAT_PREFIX}\s*:", re.IGNORECASE)


def has_motion3d_beat(scenario: Scenario) -> bool:
    return any(_MOTION3D_BEAT.match(b.visual_intent) for b in scenario.beats)


class ContractError(ValueError):
    """Fichier de contrat absent ou invalide (message destiné à Claude)."""


def resolve_in_run_dir(run_dir: Path, rel: str, *, within: str | None = None) -> Path:
    """Chemin absolu de `rel`, refusé s'il sort du run dir (ou du sous-dossier `within`)."""
    root = (run_dir / within if within else run_dir).resolve()
    path = (run_dir / rel).resolve()
    if not path.is_relative_to(root):
        where = f"{within}/" if within else "du run dir"
        raise ContractError(f"chemin hors {where} interdit : {rel}")
    return path


# Une synthèse par ligne de `narration.txt` (studio.tools tts) ; supprimé avec le run dir en fin de création.
VOICE_CACHE_DIR = "voice_cache"

# Tout ce que `studio.tools ai-image` écrit : images brutes par nom, cache et registre de dépense.
# Supprimé en entier une fois la vidéo persistée.
AI_DIR = "media/.ai"
# Images déjà générées, clé = prompt + modèle + format : relancer un prompt identique entre deux
# itérations ne repasse pas par le fournisseur, donc ne coûte rien.
AI_CACHE_DIR = f"{AI_DIR}/.cache"
# Compteur monotone des générations facturées, qui borne le plafond. Il ne peut pas se déduire de
# `media/credits.json` : les crédits sont indexés par chemin, donc régénérer sous le même nom écrase
# l'entrée et un comptage d'entrées sous-compterait les appels payants.
AI_USAGE_FILE = f"{AI_DIR}/usage.json"
AI_LOCK_FILE = f"{AI_DIR}/usage.lock"


def cache_key(payload: dict[str, Any]) -> str:
    """Clé de cache stable d'un dict JSON-sérialisable (caches TTS par ligne et segments de rendu)."""
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:32]


def read_json(path: Path, default: Any = None) -> Any:
    """JSON d'un fichier du run dir, `default` s'il n'existe pas."""
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")


def load_contract(path: Path, model: type[ModelT]) -> ModelT:
    if not path.exists():
        raise ContractError(f"{path.name} introuvable")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"{path.name} n'est pas un JSON valide : {exc}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ContractError(f"{path.name} invalide : {exc}") from exc
