#!/usr/bin/env bash
# Lance la session Claude autonome d'optimisation dans tmux (survit à la fermeture du terminal).
#
#   scripts/optim_session.sh [durée_h=10]
#
# - tmux `cutevideo-optim` : `claude` interactif, permissions bypass, priorité basse, 1 cœur pour ffmpeg/Whisper/
#   bac à sable, sans ANTHROPIC_API_KEY (abonnement Claude) ; brief : docs/optimisation/BRIEF.md
# - chien de garde mémoire : scripts/vps_watchdog.sh (log ~/.cache/cutevideo/optim/watchdog.log)
# - minuteur : à l'échéance, interrompt la session et lui demande de finaliser RECAP.md (elle reste ouverte).
# Reprise : `tmux attach -t cutevideo-optim`, ou `claude --resume` depuis le repo.
set -euo pipefail
HOURS=${1:-10}
SESSION=cutevideo-optim
REPO=$(cd "$(dirname "$0")/.." && pwd)
STATE=$HOME/.cache/cutevideo/optim
mkdir -p "$STATE"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "La session $SESSION existe déjà (tmux attach -t $SESSION)." >&2
  exit 1
fi

PROMPT="Lis docs/optimisation/BRIEF.md et exécute-le intégralement, en autonomie, jusqu'à l'échéance qu'il indique."
tmux new-session -d -s "$SESSION" -c "$REPO" -x 220 -y 50 \
  "env -u ANTHROPIC_API_KEY FFMPEG_THREADS=1 WHISPER_CPU_THREADS=1 STUDIO_SANDBOX_CPU_QUOTA=100% \
   PIPELINE_FANOUT_CONCURRENCY=2 STUDIO_SANDBOX=bwrap \
   nice -n 10 claude --dangerously-skip-permissions --model claude-opus-5-5 \"$PROMPT\"; \
   echo; echo 'Session claude terminée — reprise : claude --resume'; exec bash"

setsid nohup "$REPO/scripts/vps_watchdog.sh" "$STATE/watchdog.log" "$SESSION" >/dev/null 2>&1 < /dev/null &

DEADLINE_S=$((HOURS * 3600))
setsid nohup bash -c "
  sleep $DEADLINE_S
  if tmux has-session -t $SESSION 2>/dev/null; then
    tmux send-keys -t $SESSION Escape
    sleep 5
    tmux send-keys -t $SESSION -l 'Temps écoulé : mets docs/optimisation/RECAP.md à jour (état, résultats, choix, prochaines étapes), commit + push, puis arrête-toi.'
    sleep 1
    tmux send-keys -t $SESSION Enter
    echo \"\$(date '+%F %T') échéance atteinte, finalisation demandée\" >> '$STATE/timer.log'
  fi
" >/dev/null 2>&1 < /dev/null &

echo "Session $SESSION lancée ($(date '+%F %T'), échéance dans ${HOURS} h)."
echo "Suivre : tmux attach -t $SESSION   (détacher : Ctrl-b puis d)"
