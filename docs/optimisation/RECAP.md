# Recap — session autonome d'optimisation (2026-10-13 → 2026-10-14)

> Tenu à jour par la session au fil des jalons. Brief : `docs/optimisation/BRIEF.md`.
> Reprendre : `tmux attach -t cutevideo-optim` (si encore ouverte) ou `cd /home/ubuntu/cutevideo && claude --resume`.

## État
Session lancée le 2026-10-13 vers 20:10 — en cours.

## Générations
| # | Sujet | Version | Score | Analyse | Durée | Rendu | Mémoire min | Chemin |
|---|---|---|---|---|---|---|---|---|
| baseline | Pourquoi la Lune s'éloigne de la Terre | v1 → v2 | 79 → 85 (approuvée) | critique Claude (frames) | 30,9 s | ~6 min | 1,13 Go | `~/.cache/cutevideo/optim/baseline_lune/renders/v2.mp4` |

## Changements (quoi, pourquoi, effet mesuré)

## Choix rejetés

## Obstacles & contournements

## Actions nécessaires de l'utilisateur
- Clés Azure Speech et Gemini en 401 (voix de secours edge-tts utilisée).
- Docker : `CLAUDE_CODE_OAUTH_TOKEN` absent de `.env` (Claude non connecté dans les conteneurs).
- Ancien conteneur `cutevideo-worker` (image ghcr de 3 mois) toujours actif sur la même file Redis.

## Prochaines étapes

## Commits
