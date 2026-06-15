#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

start_api() {
  uvicorn api.main:app --host 0.0.0.0 --port 8000 \
    --reload \
    --reload-dir /app/api \
    --reload-dir /app/agent \
    --reload-delay 2 \
    --reload-exclude '*.pyc' \
    --reload-exclude '*/__pycache__/*'
}

echo "Starting API supervisor with hot reload on port 8000..."
(
  while true; do
    echo "Starting uvicorn..."
    start_api &
    API_PID=$!
    wait "$API_PID"
    EXIT_CODE=$?
    echo "API exited with code $EXIT_CODE — restarting in 2s..."
    sleep 2
  done
) &
SUPERVISOR_PID=$!

echo "Waiting for API health check..."
ready=0
for i in $(seq 1 60); do
    if curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 1
done

if [ "$ready" -ne 1 ]; then
    echo "API failed to become healthy within 60s"
    kill "$SUPERVISOR_PID" 2>/dev/null || true
    exit 1
fi

echo "Starting dashboard in dev mode on port 3000..."
cd /app/dashboard
trap 'kill "$SUPERVISOR_PID" 2>/dev/null || true' EXIT INT TERM
exec npm run dev -- -p 3000 -H 0.0.0.0
