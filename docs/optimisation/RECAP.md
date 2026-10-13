# Recap — session autonome d'optimisation (2026-10-13 → 2026-10-14)

> Tenu à jour par la session au fil des jalons. Brief : `docs/optimisation/BRIEF.md`.
> Reprendre : `tmux attach -t cutevideo-optim` (si encore ouverte) ou `cd /home/ubuntu/cutevideo && claude --resume`.

## État
En cours (20:40). Jalon 1 fait : outil `analyze`, analyse des 5 références (`REFERENCES.md`), voix/mixage/
sous-titres refaits, charte d'animation + 5 modèles, prompts recalibrés. Génération 1 (Lune, 40 s) en cours.

## Générations
| # | Sujet | Version | Score | Analyse | Durée | Rendu | Mémoire min | Chemin |
|---|---|---|---|---|---|---|---|---|
| baseline | Pourquoi la Lune s'éloigne de la Terre | v1 → v2 | 79 → 85 (approuvée, ancienne grille) | critique Claude (frames) | 30,9 s | ~6 min | 1,13 Go | `~/.cache/cutevideo/optim/baseline_lune/renders/v2.mp4` |
| g1 | Pourquoi la Lune s'éloigne de la Terre (nouvelle chaîne) | v1 → v2 | 81 → **86** (approuvée, grille virale) | `analyze` claude | 42,5 s | 42 min au total (rendu 2 min) | 1,9 Go dispo | `~/.cache/cutevideo/optim/runs/g1_lune/renders/v2.mp4` |

Mesures `analyze` de la baseline v2 : 2,38 mots/s, 13 silences de 0,4-0,9 s (un après chaque phrase), musique
quasi inaudible (fond -49 dBFS, voix/fond +33 dB), -16,2 LUFS, plan le plus long 9 s, sous-titres sous la ligne
d'interface TikTok, karaoké qui colore toute la ligne d'emblée.

Mesures `analyze` (mêmes outils pour tous) :

| mesure | baseline v2 | g1 v2 | réf. Pise (1,4 M vues) |
|---|---|---|---|
| mots/s | 2,38 | 2,97 | 3,44 |
| pause max | 0,98 s | 0,60 s | 0,86 s |
| silences francs | 12 | 0 | 0 |
| loudness | -16,2 LUFS | -15,1 (→ -14,4 avec le recalage ajouté ensuite) | -13,1 |
| voix / fond | +33 dB (musique inaudible) | +17,7 dB | +14,4 dB |
| alertes `analyze` | 13 | 2 | 1 |

g1 en clair : 11 plans 100 % animés avec le kit (thème space, accent cyan), mot-clé en haut de chaque plan,
hook « La Lune s'éloigne de nous à la vitesse où poussent vos ongles ! », « Aucun rapport ? Sauf que… »,
« Mais attendez… », « À votre avis, qui ? — Nous ! », fin « Alors la prochaine fois que vous vous coupez les
ongles, dites-vous que… » qui reboucle sur la 1re image. Critique v1 (81) très précise grâce aux planches :
voile gris des flashs, scènes trop petites, étiquette sur les sous-titres, prosodie « Au… temps » ; v2 corrige.
Défauts restants : éléments encore petits sur certains plans, étiquettes secondaires < 48 px.

## Changements (quoi, pourquoi, effet mesuré)
1. **`python -m studio.tools analyze`** (`studio/analyze.py`) — Gemini d'abord, repli Claude automatique :
   planches hook (0-3 s tous les 0,25 s), chronologie, avant/après chaque coupe détectée (repères des zones
   TikTok), transcription Whisper (débit, pauses), loudness, rapport voix/fond, hauteur et variation de la voix
   (librosa pyin), spectrogramme annoté (`audio.png`), alertes chiffrées. ~1 min 20 et 1,2 Go pour 31 s.
   Intégré à la critique (`critique_N.json` : `analysis` + `scores` par critère).
2. **Références** → `docs/optimisation/REFERENCES.md` : hook = chute paradoxale, objection « Sauf que… »,
   relances « Mais attendez », question au spectateur, fin en boucle « Alors la prochaine fois que… dites-vous
   que… », full animation avec un élément toutes les ~2 s, mot-clé titre par plan, jauge d'enjeu, tableaux
   d'unités. Mesures : 3,0-3,6 mots/s, voix/fond +14-16 dB, -13 LUFS.
3. **Voix** : edge-tts ignorait `--rate` (corrigé, + `--pitch`) ; voix par défaut edge → **Rémy Multilingual**
   (mesures sur un même texte : pauses 0,3-0,5 s contre 0,9 s pour Denise, variation 5,3 demi-tons contre 5,2,
   durée -18 %) ; silences > 0,4 s raccourcis automatiquement (`studio/voicefx.py`, `tts --max-pause`).
4. **Mixage** (`studio/audiomix.py`) : musique calée en loudness 17 dB sous la voix (au lieu d'un volume brut),
   ducking doux, fondus, **bruitages synthétisés localement** (whoosh, pop, click, ding, riser, impact — aucun
   problème de droits) via `clip.sfx`, normalisation finale -14 LUFS / limiteur.
5. **Sous-titres** (`studio/subtitles.py`) : un événement par mot → seul le mot prononcé est surligné (+12 %),
   mots-clés (`timeline.subtitle_keywords`) et nombres en vert, Poppins ExtraBold, centrés à y = 1290
   (au-dessus de la légende TikTok), fondu d'apparition.
6. **Charte d'animation** `studio/workspace/anim/lib/studio.js` : scène SVG déterministe (thèmes night, space,
   paper, blueprint, lab), titres-mots-clés, ~200 icônes Noto Emoji (Apache 2.0), étiquettes, compteurs,
   flèches tracées, trajets, barres, colonnes, tableaux d'unités, jauge, carte du monde Natural Earth
   (d3 + topojson), caméra, secousse, flash, polices Poppins (OFL). ~10 images/s de rendu dans bwrap.
7. **Modèles** : `compare`, `steps`, `map`, `before_after`, `paradox` (en plus de title, counter, bars, list).
8. **Prompts** : scénariste (angle, structure virale, fin en boucle, 2,9 mots/s, mot-clé par beat, thème),
   voix (`--rate +6%`, ponctuation expressive), monteur (full animation par défaut, un événement toutes les
   ~2 s, sfx, mots-clés), critique (grille virale 100 pts sur `analyze`), miniaturiste (fond tiré d'animation).
9. **`ai-image`** : la clé FAL du `.env` n'était jamais transmise (`generate_image` force `user_resolved_keys`) —
   corrigé ; la clé elle-même est refusée (401). Message d'erreur qui oriente vers le kit d'animation.

10. Après g1 : flash du kit teinté (mode screen, 0,35) au lieu d'un voile blanc ; `analyze --timeline` (coupes
    exactes, la détection à l'image ratait les coupes entre animations au même fond) ; règles « image 1 pleine à
    t = 0 » et « remplir l'écran » ; recalage loudness après limiteur (-15,1 → -14,4 LUFS) ; icônes passées à 356
    avec `INDEX.txt` (le monteur perdait du temps en Glob) et erreur explicite sur icône inconnue ; miniatures et
    textes incrustés en Poppins ; `thumbnail` borne `@t` à la durée de la vidéo (erreur obscure avant).
11. Modèles title / counter / bars / list refaits sur le kit (même charte que les scripts).

## Choix rejetés
- **Pollinations.ai** comme repli IA gratuit : filigrane imposé, 576×1024, rendu médiocre.
- Moteurs TTS locaux (Piper, Kokoro, XTTS) : français moins naturel que les voix Multilingual d'edge (Piper,
  Kokoro) ou trop lourds pour 2 cœurs / 7,5 Go partagés (XTTS, F5).

## Obstacles & contournements
- **Gemini** : `GOOGLE_GEMINI_API_KEY` (format `AQ.…`) refusée partout — API AI Studio, Vertex express mode, SDK
  `google-genai` (401 `ACCESS_TOKEN_TYPE_UNSUPPORTED` / « API key not valid ») → `analyze` bascule sur la voie
  Claude (matériaux perceptibles par Read), qui sert aussi à noter les références.
- **FAL** (images IA) : 401 « invalid key credentials » → full animation par défaut, images de banques.
- **Azure Speech** : 401 → edge-tts Rémy Multilingual.
- **Noto Emoji** : arborescence GitHub déplacée (`svg/` → `2D/svg/`), trouvée via l'API GitHub.

## Actions nécessaires de l'utilisateur
- Clés **Azure Speech**, **Gemini** (une vraie clé AI Studio `AIza…`) et **FAL** à refaire (toutes en 401).
- Docker : `CLAUDE_CODE_OAUTH_TOKEN` absent de `.env` (Claude non connecté dans les conteneurs).
- Ancien conteneur `cutevideo-worker` (image ghcr de 3 mois) toujours actif sur la même file Redis.
- Disque : 4 Go libres seulement sur `/`.

## Prochaines étapes
(à compléter)

## Commits
- `8374c41` Charte d'animation studio.js : icônes, polices, carte du monde et 5 nouveaux modèles
- `a446424` Analyse multimodale, voix, mixage et sous-titres viraux, prompts recalibrés sur les références
