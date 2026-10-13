# Brief — session autonome d'optimisation des Shorts explicatifs

Tu es une session Claude Code **autonome** lancée le **2026-10-13 vers 20:10** sur le VPS du projet cutevideo
(`/home/ubuntu/cutevideo`). L'utilisateur est absent jusqu'à demain : personne ne répondra à tes questions.
**Échéance : 2026-10-14 06:10** (10 h). Vérifie l'heure (`date`) régulièrement. À l'échéance, ou dès que tu as
fini, mets `docs/optimisation/RECAP.md` à jour, commit + push, puis arrête-toi. Si on t'interrompt avec
« Temps écoulé », fais la même chose immédiatement. La session sera peut-être reprise demain avec `claude --resume`.

Lis d'abord `CLAUDE.md` (racine) : architecture Claude Studio, garde-fous ffmpeg/bac à sable, tests.

## Objectif
Produire des Shorts TikTok / YouTube **explicatifs avec voix française** (concepts expliqués, avec ou sans images
réelles) de la **meilleure qualité possible**, et les rendre **utiles, intéressants et viraux**. Optimise toute la
chaîne de production (prompts du workspace `studio/workspace/`, outils `studio/`, modèles d'animation, voix, son,
sous-titres, critique) **en mesurant** : ne garde que ce qui améliore réellement le résultat.

## Principe : aucun blocage
Chaque obstacle (clé API en erreur, service qui refuse, quota, outil absent, rendu qui échoue) doit être
**contourné** par une alternative : autre service gratuit, autre moteur, traitement local, ou toi-même (Claude) à
partir de ce que tu peux percevoir. Ne t'arrête jamais sur un obstacle : note-le avec son contournement dans RECAP.md
(section « Obstacles & contournements ») et continue.

## Vidéos de référence (virales, +100 k vues chacune)
- https://www.tiktok.com/@archibald.media/video/7692490480222768406
- https://www.tiktok.com/@archibald.media/video/7692112798662315286
- https://www.tiktok.com/@alfred.explique/video/7693294289111108896
- https://www.tiktok.com/@alfred.explique/video/7695327542118518049
- https://www.tiktok.com/@alfred.explique/video/7694991216433286433

Ce sont des explications « full animation » **virales mais imparfaites** : leur voix et leur finition visuelle
peuvent être dépassées. Télécharge-les (yt-dlp est installé dans `.venv` ; sinon autre méthode) dans
`~/.cache/cutevideo/references/` — **jamais dans le repo, jamais commitées** (droits d'auteur). Analyse-les
(structure, durée, hook, rythme des plans, style graphique, mouvements/transitions, sous-titres, voix, musique,
bruitages, CTA) et **sépare** :
- ce qui fait leur **viralité** (choix et angle du sujet, hook, structure narrative, boucles ouvertes, rythme,
  chute, format full animation, durée) → à **reproduire systématiquement** ;
- leur **exécution** (voix, finition visuelle) → à **surpasser**.
Écris `docs/optimisation/REFERENCES.md` (leviers de viralité → règles concrètes) et intègre ces règles dans les
prompts (scénariste, monteur, critique) et dans la grille de la critique. Ne copie jamais leurs contenus.

## Chantiers (par ordre de priorité)
0. **Analyse multimodale des vidéos** — nouvel outil `python -m studio.tools analyze --video <mp4>` utilisé par la
   critique et par toi pour comparer avant/après et noter les références avec la même grille :
   - **Gemini gratuit d'abord** (`GOOGLE_GEMINI_API_KEY` dans `.env`, modèle flash de l'offre gratuite) : envoie la
     vidéo complète avec le son, obtiens un avis JSON structuré (hook, rythme, cohérence image/voix, naturel et
     intonation de la voix, musique/mixage, lisibilité des sous-titres, moments d'ennui, potentiel viral).
     La clé a renvoyé 401 pour la synthèse vocale : vérifie si elle marche pour l'analyse vidéo.
   - **Repli automatique sur Claude** si Gemini échoue : l'outil produit ce que Claude peut percevoir (planches de
     frames denses autour des coupes, transcription Whisper avec débit et pauses, mesures audio par segment —
     loudness, rapport voix/musique, silences, hauteur et variation de la voix via librosa — et spectrogramme en
     image) et la critique les lit (Read) pour juger voix, son, images et cohérence.
   - Résultat (source `gemini` | `claude`) intégré à `critique_N.json`.
1. **Scénario & rétention** : hooks (paradoxe, question, chiffre choc), boucles ouvertes, relance toutes les
   5-8 s, une seule idée, chute, CTA court, titres et hashtags orientés recherche. Rigueur factuelle maintenue.
2. **Visuels explicatifs** : mode **full animation** pour les concepts (sans images réelles) comme mode principal,
   images réelles quand elles apportent vraiment ; charte d'animation réutilisable (bibliothèque JS locale de
   composants dans `studio/workspace/anim/lib/` : personnages simples/formes, flèches, zooms, transitions ;
   nouveaux modèles `studio/anim_templates/` : comparaison A/B, étapes, carte/trajectoire, avant/après…) ;
   cohérence de style dans chaque vidéo.
3. **Voix & son** : meilleur rendu possible avec les moteurs disponibles (edge-tts fonctionne ; Azure et Gemini
   TTS sont en 401 — cherche d'autres options gratuites ou locales si elles sont meilleures) : choix de voix, débit,
   pauses, emphase ; loudness, ducking de la musique, bruitages légers de transition (sources libres).
4. **Sous-titres** style viral : mot actif surligné, mots-clés en couleur, position hors de l'interface TikTok.
5. **Critique** : grille recalibrée sur la viralité (hook 1-2 s, rétention, valeur, partageabilité) et les zones
   sûres TikTok, appuyée sur `analyze`.
6. **Performance / robustesse** : temps de rendu, mémoire, erreurs (`ai-image` échoue : « génération IA
   échouée » — diagnostique et corrige ou contourne).

## Méthode
Boucle : mesurer → hypothèse → changement → tests → vraie génération → comparaison → RECAP.md.
- **Baseline** : `~/.cache/cutevideo/optim/baseline_lune/` (« Pourquoi la Lune s'éloigne de la Terre », v1 79/100 →
  v2 **85/100** approuvée, 3 animations, `renders/v2.mp4`, critiques, timeline). Ajoute 1 ou 2 sujets types
  (un concept abstrait sans image réelle évidente ; une histoire ou un chiffre) et compare avant/après sur les
  mêmes sujets.
- **Au plus 6 vraies générations** au total (chacune consomme le quota de l'abonnement Claude) :
  `STUDIO_SANDBOX=bwrap .venv/bin/python -m studio.run "sujet" --duration 40 --run-dir ~/.cache/cutevideo/optim/runs/<nom>`
  (une seule à la fois, toujours lancée en arrière-plan avec un log, et surveillée). Le reste se valide hors ligne :
  tests, rendus d'animations, `analyze` sur des vidéos existantes.

## Garde-fous (impératifs)
- **VPS partagé, sans swap, 2 cœurs / 7,5 Go**. D'autres projets tournent en production (ball-animation, dont un
  « run d'équilibrage » qui occupe ~1 cœur, n8n, bases…). Ne touche **jamais** aux autres conteneurs ni projets :
  pas de `docker system prune`, pas de `sudo`, pas de redémarrage de services, pas de `kill` hors de tes propres
  processus.
- Tu tournes en priorité basse avec `FFMPEG_THREADS=1`, `WHISPER_CPU_THREADS=1`, `STUDIO_SANDBOX_CPU_QUOTA=100%`,
  `PIPELINE_FANOUT_CONCURRENCY=2` (déjà dans ton environnement : ne les relève pas).
- Un chien de garde (`scripts/vps_watchdog.sh`) tourne : log `~/.cache/cutevideo/optim/watchdog.log`. Il arrête une
  génération si la mémoire libre passe sous 600 Mo. **Lis ce log avant chaque génération** et ne lance rien si la
  mémoire disponible est sous 1,5 Go (attends). Si une génération est tuée par le chien de garde, trouve la cause
  et corrige-la avant de relancer.
- Respecte les règles ffmpeg / bac à sable de `CLAUDE.md` (`run_ffmpeg()`, `thread_args()`, `bounded_gather()`).
- Ne modifie pas `.env`, ne commite jamais de secret, ne publie rien sur YouTube / TikTok / Instagram, n'écris pas
  dans la base de dev (`shared-postgres`) ni sur S3.
- `pytest` vert avant chaque commit (dont `tests/test_studio_generation.py` et `tests/test_studio_animate.py`) ;
  mets à jour `tests/fixtures/fake_claude.py` si un contrat ou un outil change ; `graphify update .` après un
  changement significatif.
- Commits petits et explicites sur `main`, message terminé par
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, puis
  `git push git@github.com:jimmytardy/cutevideo-agent.git main` (le remote HTTPS n'a pas d'identifiants).

## RECAP.md (à tenir à jour après chaque jalon, pas seulement à la fin)
`docs/optimisation/RECAP.md`, en français, pour que l'utilisateur reprenne demain :
état final ; tableau des générations (sujet, version, score critique, source d'analyse, durée vidéo, temps de rendu,
mémoire min) ; changements faits avec pourquoi et effet mesuré ; choix rejetés ; obstacles & contournements ;
actions nécessaires de l'utilisateur (ex. clés Azure / Gemini à refaire) ; prochaines étapes priorisées ; commits ;
chemins des meilleures vidéos produites.
