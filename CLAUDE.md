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
cp .env.example .env   # infra + app credentials; paid keys go in the dashboard (Compte → Clés API)
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
uvx ruff check .                      # Python lint (ruff.toml: F, E9, B, UP); --fix applies safe fixes
cd dashboard && npm run typecheck && npm run lint   # tsc --noEmit (noUnusedLocals) + ESLint next/core-web-vitals
```

Do **not** run `npm run build` in `dashboard/` while the `cutevideo` container serves the site: it mounts the repo and runs `next dev` on the same `.next/` directory.

`tests/test_route_authorization.py` fails if a route addressed by `{project_id}` / `{channel_id}` / `{publication_id}` / `{video_id}` lacks the `get_current_user` dependency: always scope resources with `get_user_project` / `get_user_channel` (`api/authorization.py`).

Tests are in `tests/` and use `pytest-asyncio`. No mocking of the database — tests use real SQLAlchemy models.

**Full video generation is covered at three levels** (keep them green when touching `studio/`, `agent/core/claude_studio.py` or the orchestrator):

1. `tests/test_studio_generation.py` — always runs (~1-2 min): generates a complete Short through the real launcher, `studio.tools` and ffmpeg render (iteration 2 adds a template and a disposable-script animation when Chromium + bwrap are available); only the `claude` CLI is replaced by `tests/fixtures/fake_claude.py` (deterministic producer, 2 iterations). Also checks the workspace prompts only cite existing tools.
2. `tests/test_studio_pipeline_db.py` — same flow through `Orchestrator` → `ClaudeStudioRunner` → Postgres/Redis (S3 stubbed). Skipped unless `CUTEVIDEO_TEST_DATABASE_URL` / `CUTEVIDEO_TEST_REDIS_URL` point to **throwaway** infra (docker commands in the module docstring).
3. `tests/test_studio_live.py` — real `claude -p /make-video`, real image banks and TTS (~10-15 min, uses quota): `CUTEVIDEO_LIVE_TESTS=1 pytest tests/test_studio_live.py -s`.

`tests/test_studio_optim.py` covers subtitles, pause tightening/emphasis, SFX, analysis flags/pauses, templates/icons and `cues`. `tests/test_studio_animate.py` covers the animation policy, templates, scripts, the bwrap isolation (no secrets / repo / network) and the container file-queue protocol.

If you change a run-dir contract or a tool's CLI, update `fake_claude.py` accordingly.

## Architecture

### God nodes (most connected abstractions)

- `Channel` — top-level entity; every project, publication, and config is scoped to a channel
- `ClaudeStudioRunner` (agent/core/claude_studio.py) — the creation pipeline: writes `brief.json`, runs Claude Code CLI headless, mirrors progress into `AgentRun`, persists the result
- `Orchestrator` — thin wrapper: builds `PipelineContext`, calls `ClaudeStudioRunner`, sets project status `approved` / `failed` / `stopped`
- `ChannelRuntimeConfig` — Pydantic model resolved by `resolve_channel_config()` from `Channel.config` JSON + `data/agent_config.json` defaults
- `resolve_channel_config()` (agent/core/channel_config.py) — the single merge point between per-channel DB config and global defaults

### Creation pipeline: Claude Studio (`studio/`)

Video creation is done by **Claude Code CLI** (`claude -p /make-video`), not by Python agents. One `Project` = one vertical 9:16 Short.

```
Orchestrator.run_pipeline → ClaudeStudioRunner
  → run dir (STUDIO_RUNS_DIR/<project_id>, OUTSIDE the repo) = copy of studio/workspace/ + brief.json
  → claude -p /make-video  (producer = main session, 5 sub-agents in studio/workspace/.claude/agents/)
       scenariste → scenario.json · voix → voice.wav + words.json · monteur → timeline.json + renders/vN.mp4
       miniaturiste → thumbnails/ + thumbnail.json · critique → critique_N.json (approve / iterate, changes per role)
       loop ≤ brief.max_iterations, then result.json
  → persist: Scenario, Video short_master + short_<platform> (S3), CriticReport per iteration,
    Project.config.youtube_metadata (title/description/hashtags + media credits), .thumbnail, .claude_studio
```

- `studio/workspace/` — the Claude workspace copied into each run dir: `CLAUDE.md` (Short rules + file contracts), `.claude/commands/make-video.md` (producer/loop), `.claude/agents/*.md` (the 5 roles)
- `studio/tools.py` — the **only** commands the agents may run (`python -m studio.tools <cmd>`, JSON output): `search-media` (banks `DEFAULT_SOURCES` in `studio/media.py`), `preview` (contact sheet Claude looks at), `download`, `ai-image` (Flux, capped by `STUDIO_MAX_AI_IMAGES`, lowered per channel: `Brief.max_ai_images` = 0 when the channel/plan disables AI images, applied by the launcher), `music`, `tts` (engine/voice of the channel read from `brief.json`, then Gemini → edge fallback ; edge voice `fr-FR-RemyMultilingualNeural`, `--rate/--pitch`, silences > `--max-pause` 0.4 s shortened by `studio/voicefx.py`, per-line emphasis `[rate=-4% pitch=+12Hz]` relative to the global setting), `transcribe` (Whisper timings, script spelling via `studio/align.py`), `cues` (words of a clip with times relative to the clip start), `render`, `frames`, `analyze` (`studio/analyze.py`: Gemini review if the key works, otherwise material Claude reads — hook/timeline/cut contact sheets, acoustic pauses, speech rate, loudness, voice/bed ratio, pitch variation, annotated spectrogram, numeric `flags`; used by the critique), `thumbnail`, `animate-template`, `animate`, `probe`, `validate`. It `chdir`s to the repo root before importing `agent.*` (relative `.env` / `data/`).
- `studio/contracts.py` — Pydantic contracts of every run-dir file (brief, scenario, timeline, critique, thumbnail, result); validated by tools and by the runner. Also the run-dir helpers: `resolve_in_run_dir()` (refuses paths outside the run dir / a subfolder), `read_json()` / `write_json()`. `Brief.creative_brief` carries the channel's creative brief.
- `studio/assets.py` — shared constants: Short format (`SHORT_WIDTH/HEIGHT/FPS`), `WORKSPACE_LIB` / `FONTS_DIR` / `FONT_FILE`, `IMAGE_EXTENSIONS`, contact-sheet tiles, `max_ai_images()`; `studio/kenburns.py` — Ken Burns ffmpeg filters for image clips
- `studio/render.py` — timeline → Short (Ken Burns / video crop per clip, concat, mix via `studio/audiomix.py` — music loudness-matched ~17 dB under the voice with soft ducking, leading/trailing music silence trimmed, synthetic SFX from `clip.sfx`, final -14 LUFS — and active-word subtitles from `studio/subtitles.py`: Poppins, spoken word highlighted, `timeline.subtitle_keywords` + numbers coloured, centred at y≈1290 above the TikTok UI); `studio/media.py` — search/download/credits/previews/frames; `studio/thumbnail.py`, `studio/textfx.py`
- `studio/launcher.py` — builds the CLI command (permissions passed as `--allowedTools`: Bash restricted to `python -m studio.tools:*`; project settings files are ignored in untrusted dirs), parses stream-json into `agent_start` / `agent_end` / `tool` / `result` events, kills the process on cancel/timeout
- **Animations** (`studio/animate.py`): `animate-template` (built-in HTML templates `studio/anim_templates/`: title, counter, bars, list, compare, steps, map, before_after, paradox — all built on the kit) and `animate` (disposable HTML/JS or Python scripts Claude writes in `anim/`). The **animation kit** `studio/workspace/anim/lib/studio.js` (deterministic SVG scene driven by `renderFrame(t)`: keyword titles, ~355 Noto Emoji icons listed in `icons/INDEX.txt`, tags, counters, arrows, unit arrays, gauge, Natural Earth world map via d3 + topojson, camera, Poppins fonts) also exposes `__studioCheck()`: `sandbox_exec.py` samples it every 0.5 s and `animate` returns `zone_warnings` (content under the subtitles / TikTok UI, empty scene, small icons, text covered by an icon) → `media/anim_<name>.mp4`, used as a normal video clip in `timeline.json`. Policy `off | templates | scripts`: `data/agent_config.json → studio.animations` (default `scripts`), per channel `Channel.config.studio.animations` (dashboard channel settings) → `Brief.animations` → `STUDIO_ANIMATIONS` env set by the launcher (the tools trust only this, not `brief.json`).
- **Sandbox** (`studio/sandbox.py`, `STUDIO_SANDBOX=auto|bwrap|container|none`): scripts run without network, secrets or repo access. Host: bubblewrap. Docker: `studio-sandbox` container (`Dockerfile.sandbox`, `network_mode: none`, no `env_file`, non-root) fed through a file queue on the shared `studio_runs` volume (`studio/sandbox_worker.py`); `studio/sandbox_exec.py` runs inside and must stay self-contained. Rendering is frame by frame (`window.renderFrame(t)` or a paused Playwright clock driving CSS/WAAPI/GSAP). Locally: `playwright install --only-shell chromium`.
- `studio/run.py` — local run without DB: `python -m studio.run "sujet" [--duration 45] [--animations off|templates|scripts] [--interactive]`
- Step names kept for the dashboard/AgentRun: `scenario_agent`, `narrator_agent`, `editor_agent`, `thumbnail_agent`, `critic_agent` (`ROLE_AGENT_NAMES`)
- **Keys are the channel owner's, never the platform's**: `ClaudeStudioRunner` resolves `resolve_user_keys(channel.user_id)` (agent/core/api_keys.py) and fails with a clear message if the owner has no Anthropic **API** key (subscription tokens are refused: Anthropic forbids apps from storing Claude.ai credentials). `build_env()` strips every inherited secret (`studio/user_keys.py → INHERITED_SECRET_VARS`), sets `ANTHROPIC_API_KEY` for the CLI, `STUDIO_GEMINI_API_KEY` / `STUDIO_FAL_KEY` / `STUDIO_AZURE_SPEECH_KEY` / `STUDIO_AZURE_SPEECH_REGION` / `STUDIO_GCP_CREDENTIALS_JSON` for the tools (read only via `studio.user_keys.user_key()`, never `settings`) and a per-user `CLAUDE_CONFIG_DIR` (`<runs>/.claude-config/<user_id>`). `python -m studio.run --user <email>` uses that account's keys; without it no paid key is passed. Other knobs: `CLAUDE_STUDIO_MODEL`, `CLAUDE_STUDIO_TIMEOUT_S`, `CLAUDE_STUDIO_MAX_TURNS`, `CLAUDE_STUDIO_MAX_BUDGET_USD`, `STUDIO_WHISPER_MODEL` (default `small`)

**Remaining Python agents** (`agent/agents/`, extend `BaseAgent`): `ContentPlannerAgent` (creates tomorrow's `pending` projects) and `DistributionAgent` (schedules/publishes approved videos). Their LLM calls go through `BaseAgent._call_llm_for_channel()` → `call_llm()` (agent/core/llm_resolver.py) with the **channel owner's** API keys and LLM preferences (Gemini or Anthropic); default order Vertex (owner's GCP service account) → owner's Gemini → owner's Anthropic, otherwise an error asking for a key. There is no platform key and no `claude_cli` provider (old `claude_cli` preferences are read as `anthropic`).

**Scheduler jobs** (APScheduler, `agent/scheduler/jobs.py`, wired in `agent/scheduler/service.py`): content planner (06:00 Paris), pending-project launch (06:30 + hourly), distribution (every 15 min), S3/media purge (03:00: after `retention_days`, deletes video files — S3 and local — and the Studio output / run dirs of finished projects).

**Numeric env vars** are read with `env_int()` / `env_float()` (agent/core/env.py): invalid values fall back to the default instead of raising.

**Concurrency**: `can_start_pipeline()` (agent/core/concurrency.py) gates new runs against `Channel.max_concurrent_pipelines` (default 1). A restart wipes the previous creation first (`clear_creation_artifacts()` in agent/core/pipeline_reset.py; published videos are kept).

### Channel config layering

`ChannelRuntimeConfig` is built by merging (lowest → highest priority):
1. Hardcoded Pydantic defaults in `ChannelRuntimeConfig`
2. `data/agent_config.json` global defaults
3. `Channel.config` JSON stored in DB (per-channel overrides)

`ChannelRuntimeConfig` only holds fields something reads (voice, publishing, planning, Studio policy, AI images); unknown keys in `Channel.config` are ignored, and the dashboard drops obsolete ones (`runway`, `media_validation`…) on save. `load_agent_config()` is cached by mtime and returns a copy.

### Skills (agent/skills/)

Building blocks used by `studio/tools.py` and the remaining agents:

- `audio/` — `tts.py` (Azure Neural via `azure_tts.py` / Gemini / edge-tts), `ssml_builder.py` (**DragonHD voices drop `express-as`, only `rate`/`pitch` apply**), `mastering.py`, `whisper_utils.py`, `music_fetcher.py` (Freesound / Internet Archive)
- `video/` — `ffmpeg_runtime.py` (shared CPU/RAM guardrails, `probe_duration()`, `measure_loudness()`)
- `media_sources/` — one file per free bank (Pexels, Pixabay, Unsplash, Coverr, Wikimedia, NASA, Europeana, Internet Archive, Gallica; loaded dynamically by `studio/media.py`) + `ai/` for Flux/Imagen3; licences checked by `media/rights_check.py`
- `publisher/` — `youtube.py`, `instagram.py`, `executor.py` (uses `Project.config.thumbnail`, fallback `generate_thumbnail`; a publication is claimed atomically `scheduled → publishing` so concurrent runs never upload twice), `credentials.py` (always resolve tokens through it: YouTube = the channel's OAuth token, else the owner's `youtube` key; Instagram = the owner's `instagram` key on the channel's page, else `metadata.page_id`; no global or admin fallback), TikTok via `tiktok_providers.py`: provider per channel (`Channel.config.tiktok.provider` ∈ `composio` | `postforme` | `zernio`, default `data/agent_config.json → publishing.tiktok_provider`), connected accounts in `Channel.config.tiktok.accounts.<provider>`. Post for Me / Zernio use the **user's** API key (Compte → Clés API, providers `postforme` / `zernio` in `user_api_keys`) and their audited TikTok apps; Composio (`composio_client.py`) uses the platform `COMPOSIO_API_KEY`. Connect flow: `POST /channels/{id}/connect/tiktok` → provider OAuth → dashboard page `/channels/{id}/tiktok-connected` → `POST …/connect/tiktok/finish`; provider choice: `PUT /channels/{id}/tiktok-provider` (settings → Publication tab). Covered by `tests/test_tiktok_providers.py` (mocked HTTP)
- `content_planning/`, `pipeline_progress/` (5 studio steps per iteration from `AgentRun`)

### FFmpeg CPU/RAM guardrails

Dev/prod machines may be CPU/RAM-limited and shared with other workloads. All heavy video encodes go through `agent/skills/video/ffmpeg_runtime.py`:

- `FFMPEG_THREADS` (default `2`) — caps cores per ffmpeg process; without it libx264 grabs every core (`*thread_args()` is injected into encode commands).
- `FFMPEG_PRESET` (default `medium`) — libx264 preset for the editor render; set `fast` for a lighter, faster encode (~10–20% larger file, near-identical quality).
- `run_ffmpeg()` holds a global semaphore (=1) so only **one ffmpeg process runs at a time** across the whole process, even when an agent fans out via `asyncio.gather`. **Both video and audio encodes** route through it (`tts.py`, `mastering` filters and `studio/`), and so do ebur128 loudness measures (`measure_loudness()`; `run_ffmpeg(check=False)` returns stderr).
- `*thread_args()` must be placed in the **output** section (after the last `-i`, before `-c:v`) — as an input option it only caps the decoder, not the libx264 encoder.
- `*thread_args()` (`-threads`) caps **only the libx264 encoder**, not filtering. Any encode with `-vf` or `-filter_complex` (`studio/render.py`, `studio/audiomix.py`, `normalize_wav`, thumbnails) **must also** include `*filter_thread_args()` (`-filter_threads`/`-filter_complex_threads`, placed **before the first `-i`** as global options) — otherwise ffmpeg defaults filter threads to the logical core count and the filter stage saturates the CPU despite `-threads`.
- Whisper (`whisper_utils._get_whisper_model`) passes `cpu_threads=` (`WHISPER_CPU_THREADS`, else `FFMPEG_THREADS`); faster-whisper otherwise uses every core (studio default model `small`; `large-v3` needs ~3 GB RAM).

Fan-outs (e.g. `studio/media.py` multi-source search) use `bounded_gather()` (agent/core/concurrency.py) instead of raw `asyncio.gather` — at most `PIPELINE_FANOUT_CONCURRENCY` (default 3) tasks run at once, so a 15-segment video doesn't launch 15 concurrent TTS/ffmpeg/downloads.

`studio/render.py` renders clips sequentially and `max_concurrent_pipelines` defaults to `1`. **Any new ffmpeg encode must call `run_ffmpeg()` and include `*thread_args()`** (in the output section); cheap `ffprobe` / `ffmpeg -filters` probes may bypass it. **Any new fan-out must use `bounded_gather()`.**

### API (FastAPI, api/)

All routes are under `/api/v1/`. Key route modules:
- `auth.py` — Google OAuth login, plus optional login by Google Authenticator code (`POST /auth/totp/login`, RFC 6238 in `agent/core/totp.py`, no dependency): `TOTP_SECRET` + `TOTP_LOGIN_EMAIL` in `.env` (generate with `scripts/totp_setup.py <email>`), logs into the `User` with that email (Google login later re-attaches by email), Redis anti-replay + 5 failures / 15 min per IP
- `agents.py` — agent runs of a project
- `projects.py` — CRUD for projects (run/stop/restart, scenario, metadata, cost) ; `project_media.py` — videos, streams, final preview, thumbnails
- `content_planning.py` — content planner trigger + channel plan
- `distribution.py` — distribution queue
- `channel_onboarding.py` — wizard (name/niche form, brand kit, YouTube OAuth, TikTok via Composio, Instagram)
- `cost.py` — weekly AI image cost estimates
- `scheduler.py` — APScheduler status and manual job trigger

The scheduler is embedded in the API process (not a separate worker) when `SCHEDULER_ENABLED=true`.

### Frontend (dashboard/)

Next.js 14 App Router + Material UI v6. API calls go through `dashboard/lib/api.ts` using a `fetcher()` wrapper. The Next.js dev server proxies `/api/` to the FastAPI backend (see `next.config.mjs`).

Key pages: `/channels` (list), `/channels/new` (wizard), `/channels/[id]/settings`, `/scheduler`, `/projects/[id]` (Claude Studio steps via `components/StudioPipeline.tsx`, preview, thumbnails, script, credits).

### Storage

S3 is used as soon as `S3_BUCKET` is set (final videos uploaded, presigned URLs for TikTok/Instagram; boto3 reads the standard `AWS_*` variables); otherwise files stay local. Quota enforcement and retention cleanup are handled by `agent/core/storage.py`.

### Key config files

- `data/agent_config.json` — global defaults for pipeline, TTS, video encoding, media sources, LLM tiers, quotas
- `.env` / `.env.example` — secrets and runtime overrides (DATABASE_URL, REDIS_URL, API keys)
- `alembic/` — migration history; apply with `alembic upgrade head`
