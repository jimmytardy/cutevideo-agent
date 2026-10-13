FROM node:20-alpine AS dashboard-builder

WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    libsndfile1 \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Torch CPU-only AVANT requirements : silero-vad/torchaudio tireraient sinon
# ~4 Go de libs CUDA NVIDIA inutiles (le VPS tourne en CPU).
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Claude Code CLI : orchestre la création des vidéos (studio/, `claude -p /make-video`).
ARG CLAUDE_CODE_VERSION=2.1.296
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

COPY agent/ ./agent/
COPY studio/ ./studio/
COPY api/ ./api/
COPY alembic/ ./alembic/
COPY data/ ./data/
COPY alembic.ini .

COPY --from=dashboard-builder /app/dashboard/package.json /app/dashboard/package-lock.json* ./dashboard/
WORKDIR /app/dashboard
RUN npm ci --omit=dev
COPY --from=dashboard-builder /app/dashboard/.next ./.next
COPY --from=dashboard-builder /app/dashboard/public ./public
COPY --from=dashboard-builder /app/dashboard/next.config.mjs ./next.config.mjs

WORKDIR /app
RUN mkdir -p tmp output/studio /var/lib/cutevideo/studio-runs

COPY scripts/docker-entrypoint.sh ./scripts/docker-entrypoint.sh
COPY scripts/docker-entrypoint.worker.sh ./scripts/docker-entrypoint.worker.sh
COPY scripts/docker-entrypoint.worker.dev.sh ./scripts/docker-entrypoint.worker.dev.sh
COPY scripts/wait-for-redis.sh ./scripts/wait-for-redis.sh
COPY scripts/pipeline_worker.py ./scripts/pipeline_worker.py
RUN chmod +x ./scripts/docker-entrypoint.sh ./scripts/docker-entrypoint.worker.sh ./scripts/docker-entrypoint.worker.dev.sh ./scripts/wait-for-redis.sh

ENV PYTHONUNBUFFERED=1 \
    INTERNAL_API_URL=http://127.0.0.1:8000 \
    STUDIO_RUNS_DIR=/var/lib/cutevideo/studio-runs

EXPOSE 3000

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
