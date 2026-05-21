# CuteVideo Agent — Pipeline IA Multi-Agents

Génération automatique de vidéos éducatives longues + shorts via un pipeline multi-agents, avec **plusieurs chaînes thématiques** en parallèle (1 pipeline actif max par chaîne).

## Stack

- **Backend** : Python (FastAPI, SQLAlchemy async, Alembic)
- **IA** : Claude (Anthropic) — cerveau de chaque agent
- **DB** : PostgreSQL 16 + Redis
- **Frontend** : Next.js 14 App Router + Material UI v6
- **Vidéo** : FFmpeg, Whisper, edge-tts
- **Sources médias** : Gallica BnF, Europeana, Wikimedia, Unsplash, Pexels

## Pipeline des agents

**Création** (chaque nouveau projet — charge le contexte d'apprentissage chaîne avant le scénario) :

```
Scénariste → Chercheur Média → Narrateur Voix → Monteur Vidéo
    → Sous-titreur → Critique IA → Découpeur Shorts → Éditeur Shorts → Publisher
```

**Engagement** (scheduler horaire, heures UTC décalées par publication) :

```
Analytics Agent → Comments Agent
```

- **Analytics** : métriques YouTube/TikTok, analyse des performances, mise à jour du contexte (`channel_learning_context`), invalidation d'insights obsolètes.
- **Comments** : commentaires YouTube/TikTok, réponses automatiques si pertinent, extraction des retours constructifs dans le même contexte.
- Les agents **Scénariste**, **Critique** et **Découpeur shorts** intègrent ce contexte dans leurs prompts.

API : `POST /api/v1/engagement/run`, `GET /api/v1/engagement/channels/{id}/learning-context`

## Multi-chaînes

- Chaque **chaîne** a une catégorie (`histoire`, `science`, `nature`…) qui pilote médias, voix TTS et prompts.
- Chaque **projet** est rattaché à une chaîne avec un sujet vidéo précis.
- **YouTube / Instagram** : identifiants OAuth partagés dans `.env`, destinations (`youtube_channel_id`, `instagram_page_id`) par chaîne en base.
- **TikTok** : un compte par chaîne via [Composio](https://docs.composio.dev/toolkits/tiktok) — bouton « Connecter TikTok » dans le dashboard (`POST /api/v1/channels/{id}/connect/tiktok`).

Exemple de chaînes seed : [`data/channels_seed.json`](data/channels_seed.json).

## Démarrage rapide

```bash
# 1. Lancer PostgreSQL + Redis
docker-compose up -d

# 2. Copier et remplir les variables d'environnement
cp .env.example .env

# 3. Installer les dépendances Python
pip install -r requirements.txt

# 4. Appliquer les migrations
alembic upgrade head

# 5. Lancer l'API
uvicorn api.main:app --reload

# 6. Lancer le dashboard
cd dashboard && npm install && npm run dev
```

## Structure

```
cutevideo-agent/
├── agent/
│   ├── core/           # orchestrateur, DB, queue, base agent
│   ├── agents/         # les 8 agents spécialisés
│   ├── skills/         # briques réutilisables (FFmpeg, TTS, sources médias…)
│   └── scheduler/      # tâches planifiées
├── api/                # FastAPI REST
├── dashboard/          # Next.js 14 + Material UI
├── alembic/            # migrations PostgreSQL
└── data/               # configuration + musique CC
```

## Stockage S3

- `STORAGE_BACKEND=s3` : vidéos finales uploadées sur S3, URLs **présignées** pour TikTok/Instagram.
- Quota logique : `S3_MAX_STORAGE_BYTES` (défaut 10 Go). Purge automatique des plus anciennes vidéos **avant upload** si plein.
- Purge planifiée : chaque jour à 03h00, fichiers > `STORAGE_RETENTION_DAYS` (défaut 30 j).
- Mode `local` : `MEDIA_PUBLIC_BASE_URL` pour exposer les fichiers (dev uniquement).

## Variables d'environnement

Voir [`.env.example`](.env.example). Minimum : `ANTHROPIC_API_KEY`. Prod : `STORAGE_BACKEND=s3`, `S3_BUCKET`, credentials AWS, `COMPOSIO_API_KEY` pour TikTok.

## MCP Composio (Cursor)

Configurer `.cursor/mcp.json` avec votre `COMPOSIO_MCP_SERVER_ID` depuis [mcp.composio.dev/tiktok](https://mcp.composio.dev/tiktok) pour tester les connexions TikTok depuis l’IDE.
# cutevideo-agent
