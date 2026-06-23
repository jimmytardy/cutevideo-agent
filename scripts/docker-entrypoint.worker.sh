#!/bin/sh
set -e

# Entrypoint worker PROD : exécute le pipeline_worker sans hot-reload.
# (La variante .worker.dev.sh utilise watchfiles pour le développement.)

echo "Applying database migrations..."
alembic upgrade head

export PYTHONPATH=/app

echo "Starting pipeline worker supervisor..."
while true; do
  echo "Starting pipeline worker..."
  python /app/scripts/pipeline_worker.py || true
  echo "Pipeline worker exited — restarting in 2s..."
  sleep 2
done
