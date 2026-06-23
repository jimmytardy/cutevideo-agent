#!/bin/sh
# Attend que Redis réponde (DNS + ping). Utilisé au démarrage app/worker en prod.
set -e

REDIS_URL="${REDIS_URL:-redis://redis:6379}"
MAX_ATTEMPTS="${REDIS_WAIT_ATTEMPTS:-60}"
NETWORK_HINT="${DOCKER_NETWORK:-local-network}"

echo "Waiting for Redis at ${REDIS_URL}..."

for i in $(seq 1 "$MAX_ATTEMPTS"); do
  if REDIS_URL="$REDIS_URL" python - <<'PY'
import os
import sys

try:
    import redis

    client = redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=2)
    client.ping()
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
  then
    echo "Redis is ready."
    exit 0
  fi
  sleep 1
done

echo "ERROR: Redis unavailable at ${REDIS_URL} after ${MAX_ATTEMPTS}s."
echo ""
echo "L'API a besoin d'un conteneur Redis sur le même réseau Docker que l'application."
echo "Exemple (réseau ${NETWORK_HINT}) :"
echo "  docker run -d --name redis --network ${NETWORK_HINT} --restart unless-stopped redis:7-alpine"
echo ""
echo "Ou, depuis le dépôt avec docker compose :"
echo "  docker compose up -d redis"
exit 1
