"""Contrats des fichiers échangés entre les rôles Claude Studio et le runner Python.

Chaque rôle écrit un fichier JSON dans le run dir ; les outils (`studio.tools`)
et le runner (`agent.core.claude_studio`) les valident avec ces modèles pour
renvoyer des erreurs explicites à Claude plutôt que d'échouer plus loin.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError, model_validator

Role = Literal["scenariste", "voix", "monteur", "miniaturiste"]
Motion = Literal["zoom", "pan_left", "pan_right", "static"]
TextPosition = Literal["top", "center", "bottom"]

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
    content_plan: dict | None = None
    # Animations autorisées : off | templates (modèles intégrés) | scripts (scripts jetables + modèles).
    animations: Literal["off", "templates", "scripts"] = "scripts"


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
    publish: PublishMetadata

    @property
    def narration(self) -> str:
        return " ".join(b.text.strip() for b in self.beats if b.text.strip())


class Word(BaseModel):
    word: str
    start: float
    end: float


class TimelineClip(BaseModel):
    media: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    motion: Motion = "zoom"
    video_offset: float = Field(default=0.0, ge=0)
    text: str = ""
    text_position: TextPosition = "top"

    @model_validator(mode="after")
    def _ordered(self) -> "TimelineClip":
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
    clips: list[TimelineClip] = Field(min_length=1)

    @model_validator(mode="after")
    def _contiguous(self) -> "Timeline":
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

    @model_validator(mode="after")
    def _changes_when_iterating(self) -> "Critique":
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
