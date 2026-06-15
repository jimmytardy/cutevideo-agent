#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Starting pipeline worker with hot reload (watchfiles)..."
export PYTHONPATH=/app
# Un pipeline en cours sera interrompu si un fichier .py change — acceptable en dev.
exec watchfiles --filter python \
  "python /app/scripts/pipeline_worker.py" \
  /app/agent /app/api /app/scripts/pipeline_worker.py
