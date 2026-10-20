#!/bin/sh
set -e

sh /app/scripts/wait-for-redis.sh

# Entrypoint du worker (dev comme prod) : exécute le pipeline_worker sans hot reload — un watcher tuerait
# la création en cours à chaque fichier .py modifié. Redéploiement : `scripts/deploy_prod_container.sh worker`.

echo "Applying database migrations..."
alembic upgrade head

export PYTHONPATH=/app

_shutdown() {
  echo "Shutting down pipeline worker..."
  if [ -n "$WORKER_PID" ]; then
    kill -TERM "$WORKER_PID" 2>/dev/null || true
    wait "$WORKER_PID" 2>/dev/null || true
  fi
  exit 0
}

trap _shutdown TERM INT

echo "Starting pipeline worker..."
python /app/scripts/pipeline_worker.py &
WORKER_PID=$!
wait "$WORKER_PID"
