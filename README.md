# CuteVideo Agent — Pipeline IA Multi-Agents

Génération automatique de vidéos éducatives longues + shorts via un pipeline de 8 agents IA spécialisés.

## Stack

- **Backend** : Python (FastAPI, SQLAlchemy async, Alembic)
- **IA** : Claude (Anthropic) — cerveau de chaque agent
- **DB** : PostgreSQL 16 + Redis
- **Frontend** : Next.js 14 App Router + Material UI v6
- **Vidéo** : FFmpeg, Whisper, edge-tts
- **Sources médias** : Gallica BnF, Europeana, Wikimedia, Unsplash, Pexels

## Pipeline des 8 agents

```
Scénariste → Chercheur Média → Narrateur Voix → Monteur Vidéo
    → Sous-titreur → Critique IA → Découpeur Shorts → Éditeur Shorts
```

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

## Variables d'environnement requises

Voir `.env.example` pour la liste complète.
# cutevideo-agent
