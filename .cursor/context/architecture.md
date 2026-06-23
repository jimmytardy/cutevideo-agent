# Architecture CuteVideo Agent

Pipeline multi-agents pour vidéos éducatives longues (10–60 min) + shorts dérivés.

## Pipeline création (`orchestrator.py`)

```
ContentPlanner (cron) → projects pending
Research → Outline → Scenario
  ├─ FactChecker / HookOptimizer / Revision (boucles)
Narrator (TTS + Whisper)
  ├─ ArtDirector (style_block)
  ├─ BeatPlanner (visual_beats, on_screen_text)
  └─ DiagramSpecialist
MediaAgent (stock → IA Flux/Imagen par beat)
MontagePlanner → Editor (FFmpeg) → Subtitle
Critic (boucle, max_critic_iterations)
Metadata → Thumbnail → Clipper → ShortEditor
```

## Publication

`distribution_agent` (cron 15 min) → `publisher/executor.py` (YouTube, TikTok, Instagram).

## Communication

- Orchestrateur lit/écrit PostgreSQL ; file Redis pour concurrence pipelines
- Reprise partielle : `pipeline_restart.py`, indices `_STEP_TO_LOOP_IDX` dans `orchestrator.py`
- Learning context : `ChannelLearningContext` (Analytics + Comments)

## Qualité vidéo (deux couches)

| Couche | Fichiers clés | Statut |
|--------|---------------|--------|
| Amont (images, critic) | `prompt_builder.py`, `art_director_agent.py`, `critic_agent.py` | Livré (voir `docs/plan-amelioration-qualite-video.md` §7) |
| Aval (montage FFmpeg) | `editor_agent.py`, `sound_design.py`, `animated_text.py`, `filter_graph_builder.py` | Socle livré ; gaps long 16:9 → `docs/roadmap-qualite-video.md` |

## Formats

| Type | Résolution |
|------|------------|
| Longue | 1920×1080 |
| Shorts | 1080×1920 |

Config : `data/agent_config.json` → `video.long` / `video.short`.
