#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Starting pipeline worker..."
export PYTHONPATH=/app
exec python /app/scripts/pipeline_worker.py
