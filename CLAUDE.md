# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

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
ScenarioAgent → MediaAgent → NarratorAgent → EditorAgent
    → SubtitleAgent → CriticAgent (up to 3 iterations) → ClipperAgent → ShortEditorAgent
```

`Orchestrator._run_creation_pipeline()` drives this sequentially. Each agent receives a `PipelineContext` with the DB entities and `ChannelRuntimeConfig`.

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

- `audio/` — `tts.py` (edge-tts / Azure Neural via `azure_tts.py`), `audio_mixer.py`, `ssml_builder.py`, `whisper_utils.py`
- `video/` — `ffmpeg_utils.py` (encode/concat/subtitle burn), `ken_burns.py`, `shorts.py`, `transitions.py`
- `media_sources/` — one file per source (Gallica, Europeana, Wikimedia, Unsplash, Pexels, Pixabay, NASA, Internet Archive) + `ai/` for Flux/Imagen3 fallback
- `publisher/` — `youtube.py`, `tiktok_comments.py`, `instagram.py`, `composio_client.py` (TikTok OAuth), `executor.py`

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
