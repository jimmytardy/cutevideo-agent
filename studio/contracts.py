"""Contrats des fichiers échangés entre les rôles Claude Studio et le runner Python.

Chaque rôle écrit un fichier JSON dans le run dir ; les outils (`studio.tools`)
et le runner (`agent.core.claude_studio`) les valident avec ces modèles pour
renvoyer des erreurs explicites à Claude plutôt que d'échouer plus loin.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError, model_validator

Role = Literal["scenariste", "voix", "monteur", "miniaturiste"]
Motion = Literal["zoom", "pan_left", "pan_right", "static"]
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
    voice: str = ""
    tts_engine: str = ""
    max_iterations: int = Field(default=3, ge=1, le=6)
    min_score: int = Field(default=75, ge=0, le=100)
    editorial_tone: str = ""
    # Brief créatif de la chaîne (réglages → Général) : ton, style narratif, interdits éditoriaux.
    creative_brief: str = ""
    content_plan: dict | None = None
    # Animations autorisées : off | templates (modèles intégrés) | scripts (scripts jetables + modèles).
    animations: Literal["off", "templates", "scripts"] = "scripts"
    # Images IA autorisées pour ce Short (0 = désactivées par la chaîne ou l'abonnement ;
    # None = plafond plateforme STUDIO_MAX_AI_IMAGES).
    max_ai_images: int | None = Field(default=None, ge=0)


class ScenarioBeat(BaseModel):
    text: str = Field(min_length=1)
    visual_intent: str = ""
    on_screen_text: str = ""


class PublishMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)


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
    publish: PublishMetadata

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
    # Résumé de `analyze` : {"source": "gemini"|"claude", "path": "review/vN/analysis/analysis.json", "flags": […]}.
    analysis: dict | None = None

    @model_validator(mode="after")
    def _changes_when_iterating(self) -> Critique:
        if self.decision == "iterate" and not self.changes:
            raise ValueError("decision=iterate exige au moins un élément dans changes")
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
