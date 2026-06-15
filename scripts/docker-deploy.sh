#!/bin/bash

# ─────────────────────────────────────────────
#  docker-deploy.sh — Pull & Redémarre une image ghcr.io
#
#  Générique multi-apps. Variables surchargeables via l'environnement
#  ou lues depuis le .env de l'application :
#    PORT             port externe (hôte) exposé — modifiable
#    CONTAINER_PORT   port d'écoute DANS le conteneur (défaut: = PORT)
#    APP_HOST         interface de bind (défaut: 0.0.0.0)
#    DOCKER_NETWORK   réseau principal      (défaut: postgres_network)
#    EXTRA_NETWORKS   réseaux additionnels  (séparés par des virgules)
#    WORKER_ENTRYPOINT  si défini, déploie aussi <app>-worker avec cet entrypoint
# ─────────────────────────────────────────────

GITHUB_USER="${GITHUB_USER:-jimmytardy}"
DOCKER_NETWORK="${DOCKER_NETWORK:-postgres_network}"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# Lit une variable d'un fichier .env (1re occurrence), nettoie espaces/CR/guillemets.
read_env_var() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  grep -E "^${key}=" "$file" | head -n1 | cut -d'=' -f2- | tr -d ' \r"'
}

echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════╗"
echo "  ║     Docker Deploy — VPS          ║"
echo "  ╚══════════════════════════════════╝"
echo -e "${RESET}"

# ── 0. Authentification ghcr.io ──────────────
if [[ -z "$GITHUB_TOKEN" ]]; then
  echo -e "${RED}✗ Variable GITHUB_TOKEN introuvable.${RESET}"
  echo -e "${YELLOW}  Ajoute dans ~/.zshrc :${RESET}"
  echo -e "  ${CYAN}export GITHUB_TOKEN=\"ghp_xxxxxxxxxxxx\"${RESET}"
  exit 1
fi

echo -e "${BOLD}[0/3] Connexion à ghcr.io...${RESET}"

if echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin 2>/dev/null; then
  echo -e "${GREEN}✓ Connecté à ghcr.io${RESET}"
else
  echo -e "${RED}✗ Échec de la connexion. Vérifie que ton GITHUB_TOKEN est valide.${RESET}"
  exit 1
fi

echo ""

# ── 1. Nom de l'application ──────────────────
while true; do
  read -p "$(echo -e ${YELLOW}Nom de l\'application :${RESET} )" APP_NAME
  if [[ -z "$APP_NAME" ]]; then
    echo -e "${RED}✗ Le nom ne peut pas être vide.${RESET}"
  elif [[ ! "$APP_NAME" =~ ^[a-z0-9._-]+$ ]]; then
    echo -e "${RED}✗ Uniquement lettres minuscules, chiffres, - . _${RESET}"
  else
    break
  fi
done

# ── 2. Version ───────────────────────────────
read -p "$(echo -e ${YELLOW}Version \[latest par défaut\] :${RESET} )" VERSION
VERSION=${VERSION:-latest}
IMAGE="ghcr.io/${GITHUB_USER}/${APP_NAME}:${VERSION}"

echo ""
echo -e "${BOLD}Image ciblée :${RESET} ${CYAN}${IMAGE}${RESET}"
echo ""

# ── 3. Détection du .env ─────────────────────
ENV_OPT=""
ENV_PATH=""

ENV_LOCAL="$HOME/${APP_NAME}/.env.local"
ENV_FILE="$HOME/${APP_NAME}/.env"

if [[ -f "$ENV_LOCAL" ]]; then
  echo -e "${GREEN}✓ .env.local trouvé : ${ENV_LOCAL}${RESET}"
  ENV_OPT="--env-file $ENV_LOCAL"
  ENV_PATH="$ENV_LOCAL"
elif [[ -f "$ENV_FILE" ]]; then
  echo -e "${GREEN}✓ .env trouvé : ${ENV_FILE}${RESET}"
  ENV_OPT="--env-file $ENV_FILE"
  ENV_PATH="$ENV_FILE"
else
  echo -e "${YELLOW}⚠ Aucun .env trouvé dans ~/${APP_NAME}/${RESET}"
  read -p "$(echo -e ${YELLOW}Chemin vers ton .env \[Entrée pour ignorer\] :${RESET} )" CUSTOM_ENV

  if [[ -n "$CUSTOM_ENV" ]]; then
    if [[ -f "$CUSTOM_ENV" ]]; then
      echo -e "${GREEN}✓ .env trouvé : ${CUSTOM_ENV}${RESET}"
      ENV_OPT="--env-file $CUSTOM_ENV"
      ENV_PATH="$CUSTOM_ENV"
    else
      echo -e "${RED}✗ Fichier introuvable : ${CUSTOM_ENV}, démarrage sans .env.${RESET}"
    fi
  else
    echo -e "${YELLOW}  Démarrage sans .env.${RESET}"
  fi
fi

# ── 4. Lecture des ports / réseaux / worker ──
# Priorité : variable d'environnement déjà exportée > valeur du .env > défaut.
HOST_PORT="${PORT:-$(read_env_var "$ENV_PATH" PORT)}"
CONTAINER_PORT="${CONTAINER_PORT:-$(read_env_var "$ENV_PATH" CONTAINER_PORT)}"
APP_HOST="${APP_HOST:-$(read_env_var "$ENV_PATH" APP_HOST)}"
EXTRA_NETWORKS="${EXTRA_NETWORKS:-$(read_env_var "$ENV_PATH" EXTRA_NETWORKS)}"
WORKER_ENTRYPOINT="${WORKER_ENTRYPOINT:-$(read_env_var "$ENV_PATH" WORKER_ENTRYPOINT)}"

# Port externe (hôte) — modifiable, défaut 3000.
if [[ -n "$HOST_PORT" ]]; then
  echo -e "  Port externe (hôte) : ${CYAN}${HOST_PORT}${RESET}"
else
  echo -e "${YELLOW}  Aucun PORT trouvé, port externe = 3000 par défaut.${RESET}"
  HOST_PORT=3000
fi

# Port interne (écoute dans le conteneur) — défaut = port externe (rétro-compat).
if [[ -n "$CONTAINER_PORT" ]]; then
  echo -e "  Port interne (conteneur) : ${CYAN}${CONTAINER_PORT}${RESET}"
else
  CONTAINER_PORT="$HOST_PORT"
fi

# Construction du mapping, avec bind d'interface optionnel.
if [[ -n "$APP_HOST" ]]; then
  PORT_MAPPING="-p ${APP_HOST}:${HOST_PORT}:${CONTAINER_PORT}"
  BIND_DESC="${APP_HOST}:${HOST_PORT}"
else
  PORT_MAPPING="-p ${HOST_PORT}:${CONTAINER_PORT}"
  BIND_DESC="0.0.0.0:${HOST_PORT}"
fi

echo ""

# ── 5. Pull ──────────────────────────────────
echo -e "${BOLD}[1/3] Pull de l'image...${RESET}"
if docker pull "$IMAGE"; then
  echo -e "${GREEN}✓ Pull réussi${RESET}"
else
  echo -e "${RED}✗ Impossible de trouver l'image : ${IMAGE}${RESET}"
  exit 1
fi

echo ""

# ── 6. Helper : (re)déploie un conteneur ─────
# Args : <nom_conteneur> <port_mapping|""> <entrypoint_override|"">
deploy_container() {
  local name="$1" port_mapping="$2" entrypoint="$3"

  local existing
  existing=$(docker ps -a --filter "name=^${name}$" --format "{{.Names}}")
  if [[ -n "$existing" ]]; then
    local status
    status=$(docker inspect -f '{{.State.Status}}' "$name")
    echo -e "  Conteneur existant (${status}) → arrêt/suppression de ${CYAN}${name}${RESET}"
    docker stop "$name" >/dev/null 2>&1 && echo -e "${GREEN}    ✓ Arrêté${RESET}"
    docker rm "$name" >/dev/null 2>&1 && echo -e "${GREEN}    ✓ Supprimé${RESET}"
  fi

  local entrypoint_opt=""
  [[ -n "$entrypoint" ]] && entrypoint_opt="--entrypoint $entrypoint"

  if docker run -d \
    --name "$name" \
    --restart unless-stopped \
    --network "$DOCKER_NETWORK" \
    $port_mapping \
    $ENV_OPT \
    $entrypoint_opt \
    "$IMAGE" >/dev/null; then

    # Réseaux additionnels (postgres/redis sur un autre réseau, etc.)
    if [[ -n "$EXTRA_NETWORKS" ]]; then
      IFS=',' read -ra _nets <<< "$EXTRA_NETWORKS"
      for net in "${_nets[@]}"; do
        net=$(echo "$net" | tr -d ' ')
        [[ -z "$net" ]] && continue
        docker network connect "$net" "$name" 2>/dev/null \
          && echo -e "${GREEN}    ✓ Connecté au réseau ${net}${RESET}" \
          || echo -e "${YELLOW}    ⚠ Réseau ${net} introuvable, ignoré${RESET}"
      done
    fi
    echo -e "${GREEN}  ✓ ${name} démarré${RESET}"
    return 0
  else
    echo -e "${RED}  ✗ Échec du démarrage de ${name}.${RESET}"
    return 1
  fi
}

# ── 7. Déploiement de l'app ──────────────────
echo -e "${BOLD}[2/3] Déploiement de l'application...${RESET}"
echo -e "  Réseau   : ${CYAN}${DOCKER_NETWORK}${RESET}"
echo -e "  Mapping  : ${CYAN}${BIND_DESC} → conteneur:${CONTAINER_PORT}${RESET}"
deploy_container "$APP_NAME" "$PORT_MAPPING" "" || exit 1

echo ""

# ── 8. Déploiement du worker (optionnel) ─────
echo -e "${BOLD}[3/3] Worker...${RESET}"
if [[ -n "$WORKER_ENTRYPOINT" ]]; then
  echo -e "  Entrypoint worker : ${CYAN}${WORKER_ENTRYPOINT}${RESET} (sans port exposé)"
  deploy_container "${APP_NAME}-worker" "" "$WORKER_ENTRYPOINT" || exit 1
else
  echo -e "${YELLOW}  WORKER_ENTRYPOINT non défini → aucun worker (app web seule).${RESET}"
fi

echo ""
echo -e "${GREEN}${BOLD}✓ Déployé avec succès !${RESET}"
echo ""
echo -e "  Image    : ${CYAN}${IMAGE}${RESET}"
echo -e "  Conteneur: ${CYAN}${APP_NAME}${RESET}"
[[ -n "$WORKER_ENTRYPOINT" ]] && echo -e "  Worker   : ${CYAN}${APP_NAME}-worker${RESET}"
echo -e "  Réseau   : ${CYAN}${DOCKER_NETWORK}${RESET}"
[[ -n "$EXTRA_NETWORKS" ]] && echo -e "  Réseaux+ : ${CYAN}${EXTRA_NETWORKS}${RESET}"
echo -e "  Bind     : ${CYAN}${BIND_DESC} → ${CONTAINER_PORT}${RESET}"
[[ -n "$ENV_OPT" ]] && echo -e "  Env file : ${CYAN}${ENV_PATH}${RESET}"
echo ""
echo -e "${BOLD}Logs en direct (app) :${RESET}"
docker logs -f "$APP_NAME"
