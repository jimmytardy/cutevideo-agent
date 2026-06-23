# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After any significant change to the application (new/renamed/deleted files, new agents or skills, changed cross-file relationships), run `graphify update .` to keep the graph current (AST-only, no API cost). Minor edits within a single function don't require it, but when in doubt, run it.

## Development Commands

### Local dev (Option B — PostgreSQL + Redis via Docker, app locally)

```bash
# Start infra only
docker compose up -d postgres redis

# Python backend
pip install -r requirements.txt
alembic upgrade head
uvicorn api.main:app --reload        # API on :8000

# Frontend
cd dashboard && npm install && npm run dev   # Next.js on :3000
```

### Docker all-in-one (Option A)

```bash
cp .env.example .env   # fill ANTHROPIC_API_KEY etc.
docker compose build app && docker compose up -d
# Dashboard: http://localhost:${APP_PORT:-3000}
```

### Database migrations

```bash
alembic upgrade head           # apply all
alembic revision --autogenerate -m "description"  # new migration
```

### Tests

```bash
pytest                          # all tests
pytest tests/test_cost_estimator.py   # single file
pytest -k "test_resolved"             # single test by name
```

Tests are in `tests/` and use `pytest-asyncio`. No mocking of the database — tests use real SQLAlchemy models.

## Architecture

### God nodes (most connected abstractions)

- `Channel` — top-level entity; every pipeline, publication, and config is scoped to a channel
- `BaseAgent` — abstract base for all 12 agents; holds the Anthropic client, AgentRun DB logging, and learning context injection
- `Orchestrator` — sequences the creation pipeline for one project; calls agents in order and gates on `CriticAgent` score
- `ChannelRuntimeConfig` — Pydantic model resolved by `resolve_channel_config()` from `Channel.config` JSON + `data/agent_config.json` defaults; consumed by every agent
- `resolve_channel_config()` (agent/core/channel_config.py:181) — the single merge point between per-channel DB config and global defaults

### Pipeline flow

**Creation pipeline** (one `Project` per video, status `pending → running → approved/rejected`):

```
ResearchAgent → OutlineAgent → ScenarioAgent → [FactCheckerAgent, HookOptimizerAgent]
    → NarratorAgent → [ArtDirectorAgent, BeatPlannerAgent, DiagramSpecialistAgent]
    → MediaAgent → MontagePlannerAgent → EditorAgent → SubtitleAgent
    → CriticAgent (loop, up to max_critic_iterations; RevisionAgent on `iterate`)
    → ClipperAgent → ShortEditorAgent
```

`Orchestrator._run_main_loop()` (called by `_run_creation_pipeline()`) drives this sequentially. The canonical step list and restart points are `_STEPS` / `_STEP_TO_LOOP_IDX` in `orchestrator.py` — **the source of truth if this diagram drifts**. Note the order: `NarratorAgent` runs **before** `BeatPlannerAgent` (beats are split post-TTS from Whisper timestamps) which runs **before** `MediaAgent`. Each agent receives a `PipelineContext` with the DB entities and `ChannelRuntimeConfig`.

**Scheduler jobs** (APScheduler, defined in `agent/scheduler/jobs.py`, wired in `agent/scheduler/service.py`):

| Schedule | Job |
|----------|-----|
| Daily 06:00 Paris | `ContentPlannerAgent` — creates `pending` projects for tomorrow |
| Every 15 min | `DistributionAgent` — schedules and publishes approved videos |
| Hourly :15 (Mon, Thu) | `AnalyticsAgent` then `CommentsAgent` (engagement loop) |
| Daily 03:00 | S3 storage cleanup |

**Concurrency**: `can_start_pipeline()` (agent/core/concurrency.py) gates new runs against `Channel.max_concurrent_pipelines` (default 1 per channel).

### Agent structure

Every agent extends `BaseAgent` (agent/core/base_agent.py):
- Constructor instantiates `anthropic.AsyncAnthropic`
- `start_run()` / `end_run()` / `fail_run()` record an `AgentRun` row in DB
- `run(input_data)` is the only abstract method
- Learning context is injected via `load_channel_context()` and compacted via `compact_learning_context()`

LLM model and token limits are resolved per-agent from `data/agent_config.json` → `llm.agent_models` by `resolve_model()` / `resolve_max_tokens()` in `agent/core/llm_config.py`. Default model: `claude-opus-4-5`; economy tier: `claude-sonnet-4-5`.

### Channel config layering

`ChannelRuntimeConfig` is built by merging (lowest → highest priority):
1. Hardcoded Pydantic defaults in `ChannelRuntimeConfig`
2. `data/agent_config.json` global defaults
3. `Channel.config` JSON stored in DB (per-channel overrides)

Theme-based media source priority lives in `THEME_SOURCE_PRIORITY` (agent/core/channel_config.py) and `data/agent_config.json → media_sources.priority_by_theme`.

### Learning context (engagement loop)

`ChannelLearningContext` (DB table) stores a rolling JSON of insights per channel, updated after each `AnalyticsAgent` + `CommentsAgent` run. `ScenarioAgent`, `CriticAgent`, and `ClipperAgent` receive a compacted summary via `compact_learning_context()`.

### Skills (agent/skills/)

Reusable building blocks called by agents — not agents themselves:

- `audio/` — `tts.py` (edge-tts / Azure Neural via `azure_tts.py`), `audio_mixer.py`, `ssml_builder.py` (maps `delivery_style`/mood → Azure SSML `express-as` style + prosody; tolerant of model vocab via `STYLE_ALIASES` / `_normalize_pace`; **DragonHD voices drop `express-as`, only `rate`/`pitch` apply**), `whisper_utils.py`, `sound_design.py` (SFX whoosh/pop/impact/click/riser, beat-cut cues long+short, ambient bed)
- `video/` — `ffmpeg_utils.py` (encode/concat/subtitle burn; flash blanc inter-chapitres long via `long_montage_profile`), `filter_graph_builder.py` (per-segment `filter_complex` render — editor hot path; applies motion, xfade transitions, `drawtext`/`svg_overlay`), `montage_profile.py` (`short_montage_profile` / `long_montage_profile`, `load_sfx_config`), `pacing_director.py` (hints hook long `fadewhite`, mood transitions), `montage_decisions.py` (per-beat creative decisions: `resolve_motion_style` alternates Ken Burns for photos, `resolve_overlay_mode` triggers a text overlay whenever a beat has `on_screen_text`, `resolve_transition`), `ken_burns.py`, `shorts.py`, `viral_subtitles.py`, `ffmpeg_runtime.py` (shared CPU/RAM guardrails)
- `media_sources/` — one file per source (Gallica, Europeana, Wikimedia, Unsplash, Pexels, Pixabay, NASA, Internet Archive) + `ai/` for Flux/Imagen3 fallback
- `publisher/` — `youtube.py`, `tiktok_comments.py`, `instagram.py`, `composio_client.py` (TikTok OAuth), `executor.py` (publication YouTube utilise `Project.config.thumbnail` de `thumbnail_agent`, fallback `generate_thumbnail`)

### FFmpeg CPU/RAM guardrails

Dev/prod machines may be CPU/RAM-limited and shared with other workloads. All heavy video encodes go through `agent/skills/video/ffmpeg_runtime.py`:

- `FFMPEG_THREADS` (default `2`) — caps cores per ffmpeg process; without it libx264 grabs every core (`*thread_args()` is injected into encode commands).
- `FFMPEG_PRESET` (default `medium`) — libx264 preset for the editor render; set `fast` for a lighter, faster encode (~10–20% larger file, near-identical quality).
- `run_ffmpeg()` holds a global semaphore (=1) so only **one ffmpeg process runs at a time** across the whole process, even when an agent fans out via `asyncio.gather`. **Both video and audio encodes** route through it (`tts.py`, `mastering` filters, `sound_design.py`, `audio_mixer.py`, plus all `video/`).
- `*thread_args()` must be placed in the **output** section (after the last `-i`, before `-c:v`) — as an input option it only caps the decoder, not the libx264 encoder.
- `*thread_args()` (`-threads`) caps **only the libx264 encoder**, not filtering. Any encode with `-vf` or `-filter_complex` (editor `filter_graph_builder`, `ken_burns`, `shorts`, `viral_subtitles`) **must also** include `*filter_thread_args()` (`-filter_threads`/`-filter_complex_threads`, placed **before the first `-i`** as global options) — otherwise ffmpeg defaults filter threads to the logical core count and the filter stage saturates the CPU despite `-threads`. The editor's cost is dominated by `-filter_complex`, so this is the main CPU lever there.
- Whisper (`whisper_utils._get_whisper_model`) passes `cpu_threads=` (`WHISPER_CPU_THREADS`, else `FFMPEG_THREADS`); faster-whisper otherwise uses every core, and `large-v3` runs on CPU right after the editor.

Per-segment fan-outs (`NarratorAgent`, `MediaAgent`, shorts `derivation.py`) use `bounded_gather()` (agent/core/concurrency.py) instead of raw `asyncio.gather` — at most `PIPELINE_FANOUT_CONCURRENCY` (default 3) tasks run at once, so a 15-segment video doesn't launch 15 concurrent TTS/ffmpeg/downloads.

The creation pipeline already renders sequentially (one segment at a time) and `max_concurrent_pipelines` defaults to `1`. **Any new ffmpeg encode must call `run_ffmpeg()` and include `*thread_args()`** (in the output section); cheap `ffprobe` / `ffmpeg -filters` probes may bypass it. **Any new per-segment fan-out must use `bounded_gather()`.**

### API (FastAPI, api/)

All routes are under `/api/v1/`. Key route modules:
- `agents.py` — manual trigger of any agent run
- `projects.py` — CRUD for projects
- `content_planning.py` — content planner trigger + channel plan
- `distribution.py` — distribution queue
- `engagement.py` — analytics/comments trigger + learning context read
- `channel_onboarding.py` — 6-step wizard (market analysis, brand kit, OAuth, TikTok via Composio)
- `cost.py` — weekly AI image cost estimates
- `scheduler.py` — APScheduler status and manual job trigger

The scheduler is embedded in the API process (not a separate worker) when `SCHEDULER_ENABLED=true`.

### Frontend (dashboard/)

Next.js 14 App Router + Material UI v6. API calls go through `dashboard/lib/api.ts` using a `fetcher()` wrapper. The Next.js dev server proxies `/api/` to the FastAPI backend (see `next.config.mjs`).

Key pages: `/channels` (list), `/channels/new` (6-step wizard), `/channels/[id]/settings`, `/scheduler`, `/projects/[id]`.

### Storage

`STORAGE_BACKEND=s3` uploads final videos to S3 with presigned URLs for TikTok/Instagram. `STORAGE_BACKEND=local` serves files via `MEDIA_PUBLIC_BASE_URL` (dev only). Quota enforcement and retention cleanup are handled by `agent/core/storage.py`.

### Key config files

- `data/agent_config.json` — global defaults for pipeline, TTS, video encoding, media sources, LLM tiers, quotas, engagement thresholds
- `.env` / `.env.example` — secrets and runtime overrides (DATABASE_URL, REDIS_URL, API keys)
- `alembic/` — migration history; apply with `alembic upgrade head`
