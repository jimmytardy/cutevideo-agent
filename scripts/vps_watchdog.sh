#!/usr/bin/env bash
# Chien de garde mémoire du VPS pendant les générations Claude Studio (machine partagée, sans swap).
#
#   scripts/vps_watchdog.sh [fichier_log] [session_tmux]
#
# Toutes les 5 s : mémoire disponible, charge, nombre de Chromium / ffmpeg. Alerte sous WARN_MB ;
# sous KILL_MB, arrête la génération en cours (`studio.run` → le launcher tue tout son groupe de
# processus) avant que le noyau ne tue des processus au hasard. S'arrête avec la session tmux surveillée.
set -u
LOG=${1:-$HOME/.cache/cutevideo/optim/watchdog.log}
SESSION=${2:-}
WARN_MB=${WATCHDOG_WARN_MB:-900}
KILL_MB=${WATCHDOG_KILL_MB:-600}
mkdir -p "$(dirname "$LOG")"
n=0
min=999999
while :; do
  if [[ -n "$SESSION" ]] && ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "$(date '+%F %T') session $SESSION terminée — mémoire minimale observée : ${min} Mo" >>"$LOG"
    exit 0
  fi
  avail=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
  load=$(cut -d' ' -f1 /proc/loadavg)
  (( avail < min )) && min=$avail
  chrome=$(pgrep -fc "chrome-headless-shell" || true)
  ff=$(pgrep -xc ffmpeg || true)
  state="mémoire ${avail} Mo (min ${min}), load ${load}, chromium=${chrome}, ffmpeg=${ff}"
  if (( avail < KILL_MB )); then
    echo "$(date '+%F %T') ALERTE ${state} : arrêt de la génération en cours" >>"$LOG"
    pkill -TERM -f "python -m studio\.run" || true
    sleep 8
    pkill -KILL -f "chrome-headless-shell" || true
  elif (( avail < WARN_MB )); then
    echo "$(date '+%F %T') ATTENTION ${state}" >>"$LOG"
  elif (( n % 60 == 0 )); then
    echo "$(date '+%F %T') ok ${state}" >>"$LOG"
  fi
  n=$((n + 1))
  sleep 5
done
