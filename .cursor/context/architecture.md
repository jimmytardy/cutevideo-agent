# Architecture CuteVideo Agent

## Vue d'ensemble

Pipeline de 8 agents IA spécialisés qui communiquent via PostgreSQL/Redis pour produire
des vidéos éducatives longues (10-60 min) + shorts automatiques.

## Flux de données

```
Content Planner (cron 6h Paris) → DB: projects pending (sujets + planned_shorts)
  ↓
Input (thème mandaté + durée + content_plan)
  ↓
Agent 1 — Scénariste     → DB: scenarios
  ↓
Agent 2 — Chercheur Média → DB: media_assets (images téléchargées localement)
  ↓
Agent 3 — Narrateur Voix  → DB: audio_files (WAV 48kHz)
  ↓
Agent 4 — Monteur Vidéo   → DB: videos (MP4 1920x1080)
  ↓
Agent 5 — Sous-titreur    → fichier .srt (vidéo longue) ou burn-in (shorts)
  ↓
Agent 6 — Critique IA     → DB: critic_reports
  ├── score >= 70 → APPROVE → Agent 7
  └── score < 70  → ITERATE → retour agents concernés (max 3x)
  ↓
Agent 7 — Découpeur Shorts → timestamps sélectionnés
  ↓
Agent 8 — Éditeur Shorts   → DB: videos (3 formats 9:16 par short)
  ↓
(projet approved — publication asynchrone)
  ↓
Distribution Agent (cron 15 min) → DB: publications (scheduled → published)
```

## Communication inter-agents

- L'orchestrateur (`orchestrator.py`) lit les résultats de chaque agent depuis la DB
- La queue Redis gère l'ordre d'exécution et les retries
- `distribution_agent` planifie et publie via `agent/skills/publisher/executor.py`
- En cas d'itération (critique), l'orchestrateur relit le `critic_report` et relance
  uniquement les agents concernés par les changements demandés
- Analytics / comments : fenêtre 21j (shorts), 180j (longues)

## Sources médias (par thème)

| Thème | Sources prioritaires |
|-------|---------------------|
| Histoire France | Gallica BnF, Europeana, Wikimedia |
| Nature/Animaux | Unsplash, Pexels, Internet Archive |
| Sciences | NASA, Wikimedia |
| Art | Met Open Access, Europeana |

## Format vidéo final

| Type | Résolution | Codec | Bitrate |
|------|-----------|-------|---------|
| Longue | 1920×1080 | H.264/AAC | 8 Mbps |
| YouTube Shorts | 1080×1920 | H.264/AAC | 6 Mbps |
| TikTok | 1080×1920 | H.264/AAC | 6 Mbps |
| Instagram Reels | 1080×1920 | H.264/AAC | 6 Mbps |
