# Graph Report - /home/jimmy/Perso/cutevideo-agent  (2026-06-13)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1146 nodes · 3298 edges · 66 communities (59 shown, 7 thin omitted)
- Extraction: 69% EXTRACTED · 31% INFERRED · 0% AMBIGUOUS · INFERRED: 1030 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `bfa7543f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Agent Runtime Core|Agent Runtime Core]]
- [[_COMMUNITY_Channel Planner Agent|Channel Planner Agent]]
- [[_COMMUNITY_Analytics Agent|Analytics Agent]]
- [[_COMMUNITY_Content Planner Agent|Content Planner Agent]]
- [[_COMMUNITY_Audio Mixing Pipeline|Audio Mixing Pipeline]]
- [[_COMMUNITY_Distribution Agent|Distribution Agent]]
- [[_COMMUNITY_Storage Management|Storage Management]]
- [[_COMMUNITY_API Entry Point|API Entry Point]]
- [[_COMMUNITY_Media Agent|Media Agent]]
- [[_COMMUNITY_Base Agent Claude|Base Agent Claude]]
- [[_COMMUNITY_Multi-Agent Video Pipeline|Multi-Agent Video Pipeline]]
- [[_COMMUNITY_Flux Image Generation|Flux Image Generation]]
- [[_COMMUNITY_Azure TTS Synthesis|Azure TTS Synthesis]]
- [[_COMMUNITY_Frontend Dependencies|Frontend Dependencies]]
- [[_COMMUNITY_Frontend API Client|Frontend API Client]]
- [[_COMMUNITY_TikTok OAuth Integration|TikTok OAuth Integration]]
- [[_COMMUNITY_Channel Config Resolver|Channel Config Resolver]]
- [[_COMMUNITY_Scheduler Service|Scheduler Service]]
- [[_COMMUNITY_TypeScript Config|TypeScript Config]]
- [[_COMMUNITY_Agent Task Queue|Agent Task Queue]]
- [[_COMMUNITY_AI Cost Estimator|AI Cost Estimator]]
- [[_COMMUNITY_Frontend Pages|Frontend Pages]]
- [[_COMMUNITY_AI Image Providers|AI Image Providers]]
- [[_COMMUNITY_Frontend Components|Frontend Components]]
- [[_COMMUNITY_Project Management API|Project Management API]]
- [[_COMMUNITY_Channel Cost Estimation|Channel Cost Estimation]]
- [[_COMMUNITY_Channels Frontend Pages|Channels Frontend Pages]]
- [[_COMMUNITY_YouTube Discovery|YouTube Discovery]]
- [[_COMMUNITY_Whisper Transcription|Whisper Transcription]]
- [[_COMMUNITY_Channel Settings Page|Channel Settings Page]]
- [[_COMMUNITY_Video Transitions|Video Transitions]]
- [[_COMMUNITY_Frontend Layout Theme|Frontend Layout Theme]]
- [[_COMMUNITY_DB Migration Runner|DB Migration Runner]]
- [[_COMMUNITY_Project Card Component|Project Card Component]]
- [[_COMMUNITY_Scheduler Frontend Page|Scheduler Frontend Page]]
- [[_COMMUNITY_Music Selector|Music Selector]]
- [[_COMMUNITY_Image Provider Protocol|Image Provider Protocol]]
- [[_COMMUNITY_MCP Config|MCP Config]]
- [[_COMMUNITY_Analytics Comments Agents|Analytics Comments Agents]]
- [[_COMMUNITY_Next.js Config|Next.js Config]]
- [[_COMMUNITY_Docker Entrypoint|Docker Entrypoint]]
- [[_COMMUNITY_Async Postgres Client|Async Postgres Client]]
- [[_COMMUNITY_Redis Python Client|Redis Python Client]]
- [[_COMMUNITY_Uvicorn Server|Uvicorn Server]]

## God Nodes (most connected - your core abstractions)
1. `Channel` - 104 edges
2. `BaseAgent` - 90 edges
3. `Video` - 71 edges
4. `Scenario` - 56 edges
5. `Project` - 53 edges
6. `ChannelRuntimeConfig` - 42 edges
7. `ChannelPlannerAgent` - 37 edges
8. `Publication` - 37 edges
9. `Orchestrator` - 36 edges
10. `resolve_channel_config()` - 34 edges

## Surprising Connections (you probably didn't know these)
- `Connection` --uses--> `Base`  [INFERRED]
  alembic/env.py → agent/core/database.py
- `Path` --uses--> `AiImagePlan`  [INFERRED]
  tests/test_ai_image_providers.py → agent/core/channel_config.py
- `_FakeChannel` --uses--> `AiImagePlan`  [INFERRED]
  tests/test_cost_estimator.py → agent/core/channel_config.py
- `Path` --uses--> `AiFallbackConfig`  [INFERRED]
  tests/test_ai_image_providers.py → agent/core/channel_config.py
- `test_resolved_provider_chain()` --calls--> `AiFallbackConfig`  [EXTRACTED]
  tests/test_ai_image_providers.py → agent/core/channel_config.py

## Import Cycles
- 1-file cycle: `agent/agents/distribution_agent.py -> agent/agents/distribution_agent.py`
- 1-file cycle: `agent/agents/publisher_agent.py -> agent/agents/publisher_agent.py`
- 1-file cycle: `agent/scheduler/cleanup.py -> agent/scheduler/cleanup.py`
- 1-file cycle: `agent/scheduler/distribution_slots.py -> agent/scheduler/distribution_slots.py`
- 1-file cycle: `agent/scheduler/editorial_calendar.py -> agent/scheduler/editorial_calendar.py`
- 1-file cycle: `agent/scheduler/engagement.py -> agent/scheduler/engagement.py`
- 1-file cycle: `api/main.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/projects.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/scheduler.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/analytics.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/media_serve.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/cost.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/engagement.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/agents.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/content_planning.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/media.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/channel_onboarding.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/config.py -> api/main.py`
- 2-file cycle: `api/main.py -> api/routes/distribution.py -> api/main.py`

## Communities (66 total, 7 thin omitted)

### Community 0 - "Agent Runtime Core"
Cohesion: 0.07
Nodes (70): Any, CriticReport, Scenario, Video, Scenario, Video, AudioFile, Path (+62 more)

### Community 1 - "Channel Planner Agent"
Cohesion: 0.13
Nodes (78): Any, _build_market_report(), ChannelPlannerAgent, _parse_json(), Suggère des niches, analyse le marché et génère le kit de marque pour une nouvel, Analyse marché multi-plateformes avec données YouTube live + synthèse IA., Convertit les thèmes recommandés de l'analyse marché en variantes onboarding., _slugify() (+70 more)

### Community 2 - "Analytics Agent"
Cohesion: 0.06
Nodes (59): Any, PublicationJob, UUID, Any, PublicationJob, UUID, datetime, Any (+51 more)

### Community 3 - "Content Planner Agent"
Cohesion: 0.08
Nodes (51): Any, Channel, DailyContentPlan, date, UUID, date, UUID, date (+43 more)

### Community 4 - "Audio Mixing Pipeline"
Cohesion: 0.06
Nodes (53): Path, Any, Any, AudioFile, MediaAsset, Path, UUID, Path (+45 more)

### Community 5 - "Distribution Agent"
Cohesion: 0.10
Nodes (44): Any, Channel, date, datetime, UUID, Video, AsyncSession, Any (+36 more)

### Community 6 - "Storage Management"
Cohesion: 0.08
Nodes (47): Path, Video, datetime, Path, Channel, ChannelRuntimeConfig, Publication, UUID (+39 more)

### Community 7 - "API Entry Point"
Cohesion: 0.06
Nodes (37): AgentRun, Any, lifespan(), AgentRunResponse, AgentRun, AsyncSession, UUID, Any (+29 more)

### Community 8 - "Media Agent"
Cohesion: 0.07
Nodes (26): Any, MediaAsset, Path, Scenario, MediaAgent, Agent 2 — Chercheur média : trouve les images/vidéos libres de droits., get_weekly_ai_image_count(), increment_weekly_ai_image_count() (+18 more)

### Community 9 - "Base Agent Claude"
Cohesion: 0.10
Nodes (37): ABC, UUID, Any, AsyncSession, UUID, Any, date, ChannelLearningContext (+29 more)

### Community 10 - "Multi-Agent Video Pipeline"
Cohesion: 0.06
Nodes (45): Chercheur Média Agent, Content Planner Agent, Critique IA Agent, Découpeur Shorts Agent, Distribution Agent, Éditeur Shorts Agent, Monteur Vidéo Agent, Narrateur Voix Agent (+37 more)

### Community 11 - "Flux Image Generation"
Cohesion: 0.14
Nodes (24): ImageGenerationRequest, ImageGenerationResult, ImageGenerationRequest, ImageGenerationResult, ImageGenerationRequest, ImageGenerationResult, ImageGenerationRequest, ImageGenerationResult (+16 more)

### Community 12 - "Azure TTS Synthesis"
Cohesion: 0.13
Nodes (23): Path, Any, Any, Path, segment_needs_voice(), Synthèse Azure Neural TTS depuis SSML., synthesize_ssml(), build_azure_ssml() (+15 more)

### Community 13 - "Frontend Dependencies"
Cohesion: 0.07
Nodes (26): dependencies, @emotion/cache, @emotion/react, @emotion/styled, @mui/icons-material, @mui/material, @mui/x-charts, next (+18 more)

### Community 14 - "Frontend API Client"
Cohesion: 0.13
Nodes (22): analyzeMarket(), applyYoutubeBranding(), ChannelBrandKit, ChannelIntegrations, completeOnboarding(), connectTikTok(), createOnboardingDraft(), CriticReport (+14 more)

### Community 15 - "TikTok OAuth Integration"
Cohesion: 0.20
Nodes (19): Any, Channel, Any, Channel, _get_composio(), initiate_tiktok_oauth(), _parse_tool_result(), _poll_publish_status() (+11 more)

### Community 16 - "Channel Config Resolver"
Cohesion: 0.18
Nodes (17): Any, Channel, DailyQuotasConfig, MediaSourcesConfig, _priority_for_category(), Fusionne agent_config.json global et channel.config (surcharges)., _resolve_ai_fallback(), resolve_channel_config() (+9 more)

### Community 17 - "Scheduler Service"
Cohesion: 0.16
Nodes (8): Any, SchedulerRun, F, Service centralisé pour les tâches planifiées., SchedulerService, Enregistre le début/fin d'un job planifié en base., track_job_run(), SchedulerRun

### Community 18 - "TypeScript Config"
Cohesion: 0.10
Nodes (19): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+11 more)

### Community 19 - "Agent Task Queue"
Cohesion: 0.11
Nodes (9): Any, AgentQueue, Queue Redis pour la communication inter-agents., Pousse une tâche dans une queue Redis., Récupère la prochaine tâche (bloquant si timeout > 0)., Met à jour le statut d'un agent en temps réel., Lit le statut d'un agent., Lit tous les statuts agents d'un projet. (+1 more)

### Community 20 - "AI Cost Estimator"
Cohesion: 0.29
Nodes (16): AiFallbackConfig, Any, Channel, ChannelRuntimeConfig, AiImagePlan, ai_fallback_from_preview(), AiCostBreakdown, AiCostEstimate (+8 more)

### Community 21 - "Frontend Pages"
Cohesion: 0.12
Nodes (7): STATUS_COLOR, Publication, FEATURES, NAV_ITEMS, AgentRun, fetchChannel(), STEP_LABELS

### Community 22 - "AI Image Providers"
Cohesion: 0.19
Nodes (13): AiFallbackConfig, Path, provider_family(), _dimensions_for_aspect(), generate_image(), Génère une image IA en secours via Flux ou Google Imagen 3., Path, Tests providers images IA Flux + Imagen 3. (+5 more)

### Community 23 - "Frontend Components"
Cohesion: 0.15
Nodes (6): CriticReport, Props, AGENTS, Props, Props, fetcher()

### Community 24 - "Project Management API"
Cohesion: 0.43
Nodes (13): ProjectCreate, ProjectResponse, AsyncSession, Project, UUID, ProjectCreate, ProjectResponse, create_project() (+5 more)

### Community 25 - "Channel Cost Estimation"
Cohesion: 0.47
Nodes (9): AsyncSession, UUID, ChannelCostEstimate, AiFallbackConfig, ChannelCostEstimate, AiFallbackPreview, CostEstimatePreviewRequest, get_channel_cost_estimate() (+1 more)

### Community 26 - "Channels Frontend Pages"
Cohesion: 0.20
Nodes (6): THEME_CATEGORIES, Channel, createChannel(), createProject(), fetchChannelIntegrations(), fetchChannels()

### Community 27 - "YouTube Discovery"
Cohesion: 0.31
Nodes (8): Any, _build_credentials(), _discover_sync(), discover_youtube_landscape(), Dérive des requêtes YouTube à partir de l'idée utilisateur., Collecte chaînes et vidéos concurrentes via YouTube Data API., search_queries_from_prompt(), test_search_queries_dedup()

### Community 28 - "Whisper Transcription"
Cohesion: 0.43
Nodes (7): Path, _build_srt(), _get_audio_duration(), Transcrit une liste de fichiers audio en fichier .srt via Whisper., _seconds_to_srt_time(), _transcribe_sync(), transcribe_to_srt()

### Community 29 - "Channel Settings Page"
Cohesion: 0.25
Nodes (6): AI_PLANS, CostEstimate, FALLBACK_OPTIONS, MODES, PLATFORMS, Props

### Community 30 - "Video Transitions"
Cohesion: 0.38
Nodes (6): Path, Enum, str, add_transition(), Applique une transition entre deux clips vidéo via FFmpeg xfade., TransitionType

### Community 31 - "Frontend Layout Theme"
Cohesion: 0.38
Nodes (3): metadata, ThemeRegistry(), theme

### Community 32 - "DB Migration Runner"
Cohesion: 0.40
Nodes (4): do_run_migrations(), run_async_migrations(), run_migrations_online(), Connection

### Community 33 - "Project Card Component"
Cohesion: 0.40
Nodes (4): ProjectCardProps, STATUS_COLOR, Project, runPipeline()

### Community 34 - "Scheduler Frontend Page"
Cohesion: 0.40
Nodes (3): JobInfo, SchedulerRun, STATUS_COLOR

### Community 35 - "Music Selector"
Cohesion: 0.50
Nodes (3): Path, Sélectionne un fichier musical CC adapté à la période historique., select_music_for_period()

### Community 36 - "Image Provider Protocol"
Cohesion: 0.50
Nodes (3): ImageProvider, Génère une image et la sauvegarde localement., Protocol

## Knowledge Gaps
- **103 isolated node(s):** `/home/jimmy/Perso/cutevideo-agent/.venv/bin/python3`, `AsyncSession`, `Redis`, `Any`, `Any` (+98 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BaseAgent` connect `Agent Runtime Core` to `Channel Planner Agent`, `Analytics Agent`, `Content Planner Agent`, `Distribution Agent`, `API Entry Point`, `Media Agent`, `Base Agent Claude`?**
  _High betweenness centrality (0.179) - this node is a cross-community bridge._
- **Why does `Channel` connect `Agent Runtime Core` to `Channel Planner Agent`, `Analytics Agent`, `Content Planner Agent`, `Distribution Agent`, `Storage Management`, `TikTok OAuth Integration`, `Channel Config Resolver`, `AI Cost Estimator`, `Project Management API`, `Channel Cost Estimation`?**
  _High betweenness centrality (0.121) - this node is a cross-community bridge._
- **Why does `AiFallbackConfig` connect `Channel Cost Estimation` to `Agent Runtime Core`, `Channel Planner Agent`, `Channel Config Resolver`, `AI Cost Estimator`, `AI Image Providers`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Are the 87 inferred relationships involving `Channel` (e.g. with `Any` and `Channel`) actually correct?**
  _`Channel` has 87 INFERRED edges - model-reasoned connections that need verification._
- **Are the 65 inferred relationships involving `BaseAgent` (e.g. with `Any` and `PublicationJob`) actually correct?**
  _`BaseAgent` has 65 INFERRED edges - model-reasoned connections that need verification._
- **Are the 56 inferred relationships involving `Video` (e.g. with `Any` and `CriticReport`) actually correct?**
  _`Video` has 56 INFERRED edges - model-reasoned connections that need verification._
- **Are the 45 inferred relationships involving `Scenario` (e.g. with `Any` and `CriticReport`) actually correct?**
  _`Scenario` has 45 INFERRED edges - model-reasoned connections that need verification._