# Recap — session autonome d'optimisation (2026-10-13 20:05 → 2026-10-14)

> Brief : `docs/optimisation/BRIEF.md` · Références : `docs/optimisation/REFERENCES.md`.
> Reprendre : `tmux attach -t cutevideo-optim` (si encore ouverte) ou `cd /home/ubuntu/cutevideo && claude --resume`.

## État final
- **6 vraies générations sur 6** (budget épuisé), une à la fois, aucune tuée par le chien de garde (aucun
  arrêt dans `~/.cache/cutevideo/optim/watchdog.log`). 5 approuvées (85-87/100), 1 à 84 (plafond d'itérations).
- La chaîne produit désormais des Shorts **full animation** dans l'esprit des références virales (hook-paradoxe,
  « Sauf que… », relances, question au spectateur, fin qui reboucle), avec une finition supérieure (kit vectoriel,
  sous-titres mot à mot, mixage -14 LUFS, bruitages) et une critique qui **mesure** au lieu d'estimer (`analyze`).
- `pytest` vert : 230 passés, 9 ignorés (tests DB/live sans infra jetable), suite complète relancée à la fin.
- Tout est commité et poussé sur `main` (34 commits, liste plus bas).

**Meilleures vidéos** (à regarder en premier) :
1. `~/.cache/cutevideo/optim/runs/g6_papier/renders/v2.mp4` — « Pourquoi on ne peut pas plier une feuille plus de 7 fois », **87/100**
2. `~/.cache/cutevideo/optim/runs/g1_lune/renders/v2.mp4` — « La Lune s'éloigne à la vitesse de vos ongles », 86/100
3. `~/.cache/cutevideo/optim/runs/g3_1582/renders/v2.mp4` — « Les 10 jours qui n'ont jamais existé », 86/100
4. `~/.cache/cutevideo/optim/runs/g2_anniv/renders/v2.mp4` — « Un match de foot sur deux… », 85/100

Miniatures : `thumbnails/v1_9x16.png` et `v1_16x9.png` dans chaque run dir ; métadonnées dans `scenario.json → publish`.

## Générations
| # | Sujet | Versions | Score critique | Analyse | Durée | Temps total (rendu) | Mémoire dispo min* | Chemin |
|---|---|---|---|---|---|---|---|---|
| baseline | Pourquoi la Lune s'éloigne de la Terre (ancienne chaîne) | v1 → v2 | 79 → 85 (ancienne grille) | critique Claude (frames) | 30,9 s | ~6 min de rendu | 1,13 Go | `~/.cache/cutevideo/optim/baseline_lune/renders/v2.mp4` |
| g1 | Lune (nouvelle chaîne) | v1 → v2 | 81 → **86** ✅ | `analyze` claude | 42,5 s | 42 min (rendu 2 min) | 1,9 Go | `~/.cache/cutevideo/optim/runs/g1_lune/renders/v2.mp4` |
| g2 | Paradoxe des anniversaires (concept abstrait) | v1 → v2 | 77 → **85** ✅ | `analyze` claude | 41,8 s | 57 min | 2,3 Go | `~/.cache/cutevideo/optim/runs/g2_anniv/renders/v2.mp4` |
| g3 | 1582, les 10 jours disparus (histoire + chiffre) | v1 → v2 | 81 → **86** ✅ | `analyze` claude | 43,5 s | 42 min | 2,3 Go | `~/.cache/cutevideo/optim/runs/g3_1582/renders/v2.mp4` |
| g4 | Lune (2e passage, correctifs 1-16) | v1 → v2 | 80 → **85** ✅ | `analyze` claude | 42,1 s | 41 min | 2,7 Go | `~/.cache/cutevideo/optim/runs/g4_lune/renders/v2.mp4` |
| g5 | Anniversaires (2e passage, correctifs 1-21) | v1 → v2 | 80 → 84 (plafond) | `analyze` claude | 41,1 s | 49 min | 2,3 Go | `~/.cache/cutevideo/optim/runs/g5_anniv/renders/v2.mp4` |
| g6 | Feuille pliée 42 fois (concept, nouveau sujet) | v1 → v2 | **83** → **87** ✅ | `analyze` claude | 42,4 s | 51 min | 1,8 Go | `~/.cache/cutevideo/optim/runs/g6_papier/renders/v2.mp4` |

\* relevés toutes les 5 min par le chien de garde ; Gemini indisponible → source d'analyse toujours `claude`.
Lancement : `STUDIO_SANDBOX=bwrap .venv/bin/python -m studio.run "<sujet>" --duration 40 --max-iterations 2 --min-score 85`.

**Scores du 1er jet** : 81, 77, 81, 80, 80, **83**. Ils progressent peu car la critique, elle aussi outillée
pendant la nuit, devient plus exigeante (elle relève ce qu'elle ne voyait pas : débordements transitoires,
synchro au mot, intonation). **Les scores sont relatifs** ; les mesures ci-dessous, identiques pour toutes les
vidéos, sont la comparaison fiable.

### Mesures homogènes (`analyze` final, ré-exécuté sur toutes les versions retenues)
| mesure | baseline | g1 | g2 | g3 | g4 | g5 | g6 | réf. Pise (1,4 M vues) |
|---|---|---|---|---|---|---|---|---|
| coupes / 10 s | 2,92 | 2,59 | 2,63 | 2,30 | 3,09 | 3,16 | **3,30** | 1,89 (+ apparitions continues) |
| plan le plus long | 9,0 s | 5,2 | 4,4 | 5,3 | 4,2 | 4,0 | 4,1 | 26,2 |
| 1re coupe | 1,4 s | 3,3 | 4,1 | 4,1 | 3,4 | **1,4** | **2,0** | 2,4 |
| débit (mots/s) | 2,38 | 2,97 | 2,96 | 2,89 | 3,04 | 2,69 | 2,82 | 3,44 |
| pause max (acoustique) | 0,94 s | 0,42 | 0,32 | 0,40 | 0,44 | 0,34 | 0,40 | 0,42 |
| silences francs | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| loudness | -16,2 LUFS | -15,1 | -14,5 | -14,5 | -14,4 | -14,5 | -14,4 | -13,1 |
| voix / fond | **+33 dB** (musique inaudible) | +17,7 | +17,0 | +16,8 | +17,9 | +16,5 | +18,9 | +14,4 |
| alertes `analyze` | 13 | 2 | 1 | 2 | 1 | 0 | 0 | 1 |

Ce que montrent les planches (lecture directe) : baseline = photos de banque sombres et vides, sous-titres sous
l'interface TikTok, karaoké qui colorait toute la ligne ; g1-g6 = 11-14 plans animés par vidéo avec une charte
par vidéo (space / night / paper), mot-clé titre à chaque plan, un élément nouveau toutes les ~2 s, sous-titres
mot à mot au-dessus de l'interface, fin qui reboucle sur la 1re image. Les objets ont grossi de g1 à g6 (alertes
« scène vide »). Faits vérifiés par la critique à chaque fois (Thérèse d'Avila, Mondial 2014, 2^42 × 0,1 mm…).

## Changements (quoi, pourquoi, effet mesuré)
**Analyse et critique**
1. **`python -m studio.tools analyze`** (`studio/analyze.py`) : Gemini d'abord, repli Claude automatique —
   planches hook (0-3 s / 0,25 s), chronologie, avant/après chaque coupe (repères des zones TikTok), débit,
   pauses **acoustiques** (Whisper gonflait les écarts : 1,36 s annoncé pour 0,32 s réel), loudness, rapport
   voix/fond, intonation (pyin), spectrogramme annoté, alertes chiffrées ; coupes exactes avec `--timeline`.
   ~1 min 20 et 1,2 Go pour 30-40 s. Intégré à `critique_N.json` (`analysis`, `scores` par critère).
2. **Grille de critique virale** (hook 20, rétention 15, valeur 15, visuels 20, voix/son 15, sous-titres 5,
   chute/partage 10), lecture obligatoire des planches et du spectrogramme, pauses acoustiques seulement.
3. **Références** → `REFERENCES.md` : leviers de viralité → règles (hook = chute paradoxale, objection « Sauf
   que… », relances, question, fin en boucle « Alors la prochaine fois que… dites-vous que… », full animation,
   mot-clé par plan, jauge d'enjeu, tableaux d'unités) intégrées aux prompts.

**Scénario & rétention** — 4. Prompt scénariste : angle le plus surprenant, structure ci-dessus, 1 mot-clé par
beat, `visual_mode` / `theme` / `accent`, titres orientés recherche, débit cible 3,1 mots/s (mesuré 3,1-3,6 sur les
références). Effet : tous les scénarios g1-g6 suivent la structure, avec des hooks concrets et vrais.

**Visuels** — 5. **Kit `studio/workspace/anim/lib/studio.js`** (scène SVG déterministe, 5 thèmes, titres,
355 icônes Noto Emoji Apache 2.0 avec `icons/INDEX.txt`, étiquettes, compteurs, flèches, trajets, barres,
colonnes, unités, jauge, carte du monde Natural Earth, caméra, secousse, flash teinté, Poppins OFL).
6. **9 modèles** sur le kit : title, counter, bars, list (refaits), compare, steps, map, before_after, paradox.
7. **Garde-fous automatiques** (`zone_warnings` renvoyés par `animate`, contrôle toutes les 0,5 s) : contenu
   sous les sous-titres ou dans la colonne d'icônes TikTok, scène vide (< 28 % de la zone utile), icône < 170 px,
   texte recouvert ; planches d'animation avec la bande des sous-titres en rouge ; titres limités à 820 px (ils
   débordaient à x 1020). Effet : plus aucun « contenu sous les sous-titres » dans les critiques de g5-g6.
8. Règles monteur : image pleine dès la coupe, hook en 2 plans (1re coupe 3,4-4,1 s → 1,4-2,0 s en g5-g6),
   continuité entre plans, outil **`cues`** (instants des mots relatifs au plan) pour caler les révélations.

**Voix & son** — 9. edge-tts : `--rate`/`--pitch` enfin transmis, voix **Rémy Multilingual** (pauses
naturelles 0,3-0,5 s contre 0,9 s pour Denise), silences > 0,4 s raccourcis (`studio/voicefx.py`), emphase par
ligne `[rate=-4% pitch=+12Hz]` relative au réglage global, nombres en chiffres dans les sous-titres.
10. **Mixage** `studio/audiomix.py` : musique calée en loudness ~17 dB sous la voix (+33 dB → +17 dB : la
musique s'entend enfin), ducking doux, silences de la piste retirés, piste plus longue que la voix, **bruitages
synthétisés localement** (whoosh, pop, click, ding, riser, impact ; `clip.sfx`), -14 LUFS avec recalage après
limiteur (-15,1 → -14,4).

**Sous-titres** — 11. `studio/subtitles.py` : seul le mot prononcé est surligné, mots-clés et nombres en
couleur, Poppins, centrés à y = 1290 (hors interface), espaces élargies, ponctuation rattachée, espace
insécable avant ? ! : ;.

**Robustesse** — 12. `ai-image` : la clé FAL n'était jamais transmise (corrigé ; la clé est en 401) et l'erreur
oriente vers le kit. 13. `thumbnail` : `@t` borné à la durée (erreur obscure avant) ; miniatures en Poppins.

## Choix rejetés
- **Pollinations.ai** (IA gratuite) : filigrane imposé, 576×1024, rendu médiocre.
- **TTS locaux** (Piper, Kokoro, XTTS, F5) : moins naturels en français que Rémy Multilingual, ou trop lourds pour
  2 cœurs / 7,5 Go partagés.
- **Capture CDP** pour accélérer le rendu des animations : -17 % seulement (0,143 s/image contre 0,172).
- **Supprimer les sous-titres** comme les références : gardés (accessibilité, visionnage sans son), mais placés
  et stylés pour ne rien masquer.

## Obstacles & contournements
- **Gemini** : clé `AQ.…` refusée partout (AI Studio, Vertex express, SDK `google-genai` ; 401) → voie Claude
  de `analyze`, utilisée aussi pour noter les références.
- **FAL** (images IA) : 401 → full animation par défaut + banques d'images.
- **Azure Speech** : 401 → edge-tts Rémy Multilingual (+ emphase par ligne pour compenser l'absence de SSML).
- **Noto Emoji** : arborescence GitHub déplacée (`2D/svg/`), retrouvée via l'API GitHub.
- **Mesures trompeuses** découvertes en route et corrigées : coupes invisibles entre animations au même fond
  (→ `--timeline`), pauses Whisper gonflées (→ acoustiques), alertes de zone seulement sur la dernière image
  (→ échantillonnage), emphase qui écrasait le débit global (→ relative).
- Le monteur lance parfois 3 rendus d'animation en parallèle : `wait_for_memory` du bac à sable a suffi
  (minimum observé 1,8 Go dispo pendant une génération).

## Actions nécessaires de l'utilisateur
- Refaire les clés **Gemini** (vraie clé AI Studio `AIza…` : `analyze` enverra alors la vidéo à Gemini
  automatiquement), **Azure Speech** (voix DragonHD, meilleure qu'edge) et **FAL** — toutes en 401.
- **Écouter** les vidéos retenues : je n'entends pas ; voix, bruitages synthétiques et musique ont été jugés
  sur mesures et spectrogrammes uniquement.
- Musiques Freesound : attribution requise (déjà dans `media/credits.json` → description).
- Docker : `CLAUDE_CODE_OAUTH_TOKEN` absent de `.env` ; ancien conteneur `cutevideo-worker` toujours actif.
- Disque : ~3,7 Go libres sur `/` (run dirs ≈ 70-110 Mo chacun dans `~/.cache/cutevideo/optim/runs/`).

## Prochaines étapes (priorisées)
1. **Voix** : c'est le critère le plus faible (12-13/15) — objections et relances encore « plates ». Tester
   Azure DragonHD dès que la clé est refaite ; sinon mesurer l'effet de la règle « une phrase par ligne » et de
   l'emphase sur une génération.
2. **Valider les derniers correctifs** (cues, débit 3,1, pop lisible, continuité, emphase relative) par 1-2
   générations : ils n'ont pas encore tourné en vrai.
3. **Calibrer la critique** : lui donner les mesures des références comme repères (`REFERENCES.md`) pour que
   le score ne dérive pas avec son exigence ; envisager `--max-iterations 3` (g5 s'est arrêtée à 84).
4. **Durée** : les références font ~2 min ; tester un format 60-90 s avec deux relances.
5. **Objet-héros persistant** entre plans (même position/échelle) et jauge d'enjeu systématique quand le récit a
   une tension.
6. Performances : 41-57 min par vidéo, dont ~15-20 min de montage (≈ 12 animations à ~30 s de rendu) ; le
   temps est surtout celui de Claude, pas du CPU.

## Commits (sur `main`, poussés)
`8374c41` kit + 5 modèles · `a446424` analyze, voix, mixage, sous-titres, prompts · `8074872` ai-image ·
`6cb7098` modèles refaits sur le kit · `de423fb` 356 icônes + index · `4ac7005` coupes timeline, flash, règles
hook · `48e2ca2` recalage -14 LUFS · `ac7227f` miniatures Poppins · `6cf6c6e` recap g1 · `6e460ef` emphase par
ligne · `af23af0` garde-fous de zone, musique · `c84aa51` ponctuation, mot-clé dès la coupe · `2559b59` recap g2 ·
`472b5f8` nombres en chiffres · `99baa16` alertes scène vide · `b6a2612` recap g3 · `490910e` chevauchements,
hook en 2 plans · `e34c77d` espaces des sous-titres · `cc61a14` zone droite 960 · `4d26476` titres 820 px ·
`135d697` contrôle échantillonné, typographie · `2ad9516` enter none · `f28061e` recap g4 · `c0e0834` pauses
acoustiques · `5abe631` emphase relative · `692d950` recap g5 · `91ecf04` outil cues · `fe99df1` intonation,
continuité · `0e3ff1a` pop lisible · `8342f97` CLAUDE.md · `ca1f819` débit 3,1 mots/s · + ce recap final.
