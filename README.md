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

**Calendrier J → J+1** (production aujourd'hui, publication **demain** Paris) :

| Heure | Action |
|-------|--------|
| 6h00 | Content planner : sujets + projets `pending` (`target_publish_date` = lendemain) |
| 6h30–23h | Pipeline : produit les vidéos pour publication demain |
| */15 min | Distribution : planifie les créneaux **uniquement sur le jour de publication cible** |
| lendemain | Distribution : publie aux horaires programmés |

```
Content Planner (J) → projets pending → Pipeline (J) → approved → Distribution planifie (J+1) → publish (J+1)
```

**Création** (chaque projet `pending` — mandat content_planner dans `project.config`) :

```
Scénariste → Chercheur Média → Narrateur Voix → Monteur Vidéo
    → Sous-titreur → Critique IA → Découpeur Shorts → Éditeur Shorts
```

**Distribution** (scheduler toutes les 15 min, si `publishing.auto_publish`) :

```
Distribution Agent → planification créneaux YT / TikTok / IG (Europe/Paris)
                  → publication aux horaires optimaux + quotas journaliers
```

- Quotas par défaut : 1 vidéo longue / jour, 3 shorts / jour (configurable dans `data/agent_config.json`).
- Créneaux par plateforme : `publishing.platform_slots` (jours + heures Paris).

**Engagement** (scheduler horaire `:15`, heures UTC décalées par publication) :

```
Analytics Agent → Comments Agent
```

- **Analytics** : métriques YouTube, fenêtre **21 jours** (shorts) / **6 mois** (longues), contexte d'apprentissage chaîne.
- **Comments** : même fenêtre que analytics ; réponses auto si pertinent.

API :
- `POST /api/v1/content-planning/run`, `POST /api/v1/content-planning/channels/{id}/plan`
- `POST /api/v1/distribution/run`, `GET /api/v1/distribution/queue`
- `POST /api/v1/engagement/run`, `GET /api/v1/engagement/channels/{id}/learning-context`

Tu configures le **thème de la chaîne** (`theme_prompt`, `niche_prompt`, `channel.config.editorial`) — le **sujet de chaque vidéo** est choisi par le content planner.

Les agents **Scénariste**, **Critique** et **Découpeur shorts** intègrent le contexte d'apprentissage dans leurs prompts.

## Multi-chaînes

- Chaque **chaîne** a une catégorie (`histoire`, `science`, `nature`…) qui pilote médias, voix TTS et prompts.
- Chaque **projet** est rattaché à une chaîne ; le sujet est généré par **content_planner_agent** (quotas = `publishing.daily_quotas`).
- **YouTube / Instagram** : identifiants OAuth partagés dans `.env`, destinations (`youtube_channel_id`, `instagram_page_id`) par chaîne en base.
- **TikTok** : un compte par chaîne via [Composio](https://docs.composio.dev/toolkits/tiktok) — bouton « Connecter TikTok » dans le dashboard (`POST /api/v1/channels/{id}/connect/tiktok`).

Exemple de chaînes seed : [`data/channels_seed.json`](data/channels_seed.json).

## Wizard de création de chaîne

Le dashboard propose un assistant en 6 étapes : **Dashboard → Chaînes → Créer une chaîne guidée** (`/channels/new`).

| Étape | Contenu |
|-------|---------|
| 1. Thème | Prompt libre → analyse marché optionnelle (`POST /api/v1/channels/onboarding/market-analysis` : YouTube API + concurrence + niches) ou niches rapides (`suggest-themes`) |
| 2. Identité | Kit de marque éditable (YouTube, TikTok, Instagram) puis brouillon en base |
| 3. YouTube | OAuth Google, liste des chaînes du compte, application du branding via API |
| 4. TikTok | OAuth Composio + paramètres d’upload par défaut (`tiktok_publish_defaults`) |
| 5. Instagram | `page_id` + profil (compte Business requis côté Meta) |
| 6. Terminer | Activation de la chaîne (`onboarding_step=complete`, `is_active=true`) |

Reprise d’un onboarding incomplet : lien **Reprendre l’onboarding** sur la carte chaîne → `/channels/{id}/setup`.

### Limites API (création de comptes)

| Plateforme | Automatisable | Limite |
|------------|---------------|--------|
| Thème / branding | Oui (Claude) | Niche, noms, bios, tags, `niche_prompt` |
| YouTube (même compte Google) | Partiel | **Création** d’une sous-chaîne Brand : lien YouTube Studio, validation manuelle 1–2 min. **Ensuite** : `channels.list` + `channels.update` pour titre, description, mots-clés |
| TikTok | Partiel | Pas de création de compte — OAuth Composio + formulaire upload |
| Instagram | Partiel | Page Business existante — `page_id` + bio ; token global `.env` |

Variables utiles dans `.env` :

```bash
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_REFRESH_TOKEN=...          # optionnel si OAuth par chaîne
YOUTUBE_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/channels/youtube/oauth/callback
API_BASE_URL=http://localhost:8000
ANTHROPIC_API_KEY=...              # requis pour onboarding (market-analysis, suggest-themes, generate-brand)
YOUTUBE_REFRESH_TOKEN=...          # recommandé pour l'analyse marché (données concurrents YouTube live)
```

Migration : `alembic upgrade head` (révision `005` — colonnes `brand_kit`, `theme_prompt`, `onboarding_step`, etc.).

Catégorie **`animaux`** : priorité médias `unsplash` → `pexels` → `wikimedia` (voir `data/agent_config.json` et `agent/core/channel_config.py`).

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
