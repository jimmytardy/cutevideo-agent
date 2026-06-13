FROM node:20-alpine AS dashboard-builder

WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ ./agent/
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
RUN mkdir -p tmp output/long output/shorts/master output/shorts/platforms

COPY scripts/docker-entrypoint.sh ./scripts/docker-entrypoint.sh
RUN chmod +x ./scripts/docker-entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    INTERNAL_API_URL=http://127.0.0.1:8000

EXPOSE 3000

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
