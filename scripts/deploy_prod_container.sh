#!/usr/bin/env bash
# Déploiement du conteneur prod `cutevideo` (API uvicorn + dashboard `next start`) lancé à la main depuis
# l'image de dev `cutevideo-dev:local`, le dépôt monté en lecture seule et le build Next dans le volume nommé
# `cutevideo_dashboard_next` (voir CLAUDE.md → Development Commands).
#
#   scripts/deploy_prod_container.sh build-dashboard   # next build hors ligne (~2 min) puis copie dans le volume
#   scripts/deploy_prod_container.sh recreate          # docker rm -f + docker run (coupure 10-20 s) ; migrations au démarrage
#   scripts/deploy_prod_container.sh health            # API, dashboard, BUILD_ID, aucun jeton en clair dans les logs
#
# DRY_RUN=1 affiche les commandes sans les exécuter. Les changements Python ou .env demandent `recreate` ;
# les changements du dashboard demandent `build-dashboard` puis `recreate`.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-cutevideo-dev:local}"
NAME="${NAME:-cutevideo}"
NETWORK="${NETWORK:-local-network}"
PORT="${PORT:-127.0.0.1:3333}"
NEXT_VOLUME="${NEXT_VOLUME:-cutevideo_dashboard_next}"
INTERNAL_API_URL="${INTERNAL_API_URL:-http://127.0.0.1:8000}"
# Base et Redis partagés du réseau Docker (docker-compose.yml) : surchargent les valeurs locales du .env.
DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://cutevideo:cutevideo@shared-postgres:5432/cutevideo}"
REDIS_URL="${REDIS_URL:-redis://redis:6379}"

run() {
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf '+'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

build_dashboard() {
  # Build dans un conteneur jetable, hors du volume servi, puis synchronisation : le site ne tombe pas pendant
  # les 2 min de build. `rewrites()` de next.config.mjs lit INTERNAL_API_URL au build.
  run docker run --rm --cpus 1.5 --memory 3g \
    -v "$REPO/dashboard:/src/dashboard:ro" \
    -v "$NEXT_VOLUME:/out" \
    -e NODE_ENV=production -e NEXT_TELEMETRY_DISABLED=1 -e "INTERNAL_API_URL=$INTERNAL_API_URL" \
    --entrypoint sh "$IMAGE" -c '
      set -e; cd /app/dashboard
      for d in app components lib public; do rm -rf "$d"; cp -r "/src/dashboard/$d" .; done
      for f in next.config.mjs tsconfig.json next-env.d.ts package.json; do cp "/src/dashboard/$f" .; done
      if ! cmp -s /src/dashboard/package-lock.json package-lock.json; then cp /src/dashboard/package-lock.json .; npm ci; fi
      rm -rf .next && npx next build --no-lint
      find /out -mindepth 1 -maxdepth 1 -exec rm -rf {} +
      cp -a .next/. /out/
      echo "BUILD_ID: $(cat /out/BUILD_ID)"'
}

recreate() {
  run docker rm -f "$NAME"
  run docker run -d --name "$NAME" --restart unless-stopped --network "$NETWORK" -p "$PORT:3000" \
    --env-file "$REPO/.env" \
    -e STUDIO_SANDBOX=container -e "INTERNAL_API_URL=$INTERNAL_API_URL" -e SCHEDULER_ENABLED=false \
    -e NODE_ENV=production -e "DATABASE_URL=$DATABASE_URL" -e "REDIS_URL=$REDIS_URL" \
    -v "$REPO/agent:/app/agent:ro" -v "$REPO/studio:/app/studio:ro" -v "$REPO/api:/app/api:ro" \
    -v "$REPO/alembic:/app/alembic:ro" -v "$REPO/alembic.ini:/app/alembic.ini:ro" -v "$REPO/scripts:/app/scripts:ro" \
    -v "$REPO/data:/app/data" \
    -v "$REPO/dashboard/public:/app/dashboard/public:ro" \
    -v "$REPO/dashboard/next.config.mjs:/app/dashboard/next.config.mjs:ro" \
    -v "$NEXT_VOLUME:/app/dashboard/.next" -v cutevideo_app_output:/app/output -v cutevideo_app_tmp:/app/tmp \
    -v cutevideo_studio_runs:/var/lib/cutevideo/studio-runs \
    --entrypoint sh "$IMAGE" /app/scripts/docker-entrypoint.sh
}

health() {
  local ok=0
  for _ in $(seq 1 60); do
    if docker exec "$NAME" curl -sf "$INTERNAL_API_URL/health" >/dev/null 2>&1 \
       && curl -sf -o /dev/null "http://$PORT/api/v1/auth/totp/enabled"; then ok=1; break; fi
    sleep 2
  done
  [[ $ok == 1 ]] || { echo "KO : API ou dashboard injoignable après 120 s"; docker logs --tail 40 "$NAME"; exit 1; }
  echo "API /health OK ; dashboard HTTP $(curl -s -o /dev/null -w '%{http_code}' "http://$PORT/")"
  echo "BUILD_ID: $(docker exec "$NAME" cat /app/dashboard/.next/BUILD_ID)"
  local leaks
  leaks=$(docker logs --since 1h "$NAME" 2>&1 | grep -E 'access_token=' | grep -vc 'access_token=\*\*\*' || true)
  echo "jetons en clair dans les logs (dernière heure) : ${leaks:-0}"
}

case "${1:-}" in
  build-dashboard) build_dashboard ;;
  recreate) recreate ;;
  health) health ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
