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
| g5 | Le paradoxe des anniversaires (2e passage, correctifs 1-21) | v1 → v2 | 80 → 84 (plafond de 2 itérations, v2 retenue) | `analyze` claude | ~42 s | 49 min au total | 2,5 Go dispo | `~/.cache/cutevideo/optim/runs/g5_anniv/renders/v2.mp4` |
| g4 | Pourquoi la Lune s'éloigne de la Terre (2e passage, correctifs 1-16) | v1 → v2 | 80 → **85** (approuvée) | `analyze` claude | 42,1 s | 41 min au total | 2,8 Go dispo | `~/.cache/cutevideo/optim/runs/g4_lune/renders/v2.mp4` |
| g3 | Les 10 jours qui n'ont jamais existé (1582, histoire + chiffre) | v1 → v2 | 81 → **86** (approuvée) | `analyze` claude | 43,5 s | 43 min au total | 2,7 Go dispo | `~/.cache/cutevideo/optim/runs/g3_1582/renders/v2.mp4` |
| g2 | Le paradoxe des anniversaires (concept abstrait) | v1 → v2 | 77 → **85** (approuvée) | `analyze` claude | 41,8 s | 57 min au total | 2,8 Go dispo | `~/.cache/cutevideo/optim/runs/g2_anniv/renders/v2.mp4` |
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

g2 en clair : « Un match de foot sur deux cache deux personnes nées le même jour ! », 22 joueurs + l'arbitre,
« vous contre 22 » puis 253 duos, question, 50,7 %, Mondial 2014 (16 équipes sur 32), 99,9 % à 70, fin en boucle
« la prochaine fois que vous regardez un match, dites-vous que… ». v1 pénalisée par des défauts d'outillage
(contenu sous les sous-titres dans 8 plans, icône calendrier marquée « July », musique de 40 s à intro muette) →
corrigés dans l'outillage pendant l'itération 2 (voir changements 12-14). Mesures v1 → v2 : 2,92 → 2,96 mots/s,
-14,4 / -14,5 LUFS (recalage efficace), voix/fond 13,6 → 17,0 dB.

g3 en clair : thème « paper » + accent rouge, hook « Cette femme est morte le 4 octobre… et enterrée le
lendemain, le 15 ! » (Thérèse d'Avila, exact), Jules César et ses 11 minutes, « Mais attendez… », Grégoire XIII
« À votre avis… comment ? » (emphase vocale utilisée), carte (France décembre 1582, Angleterre 1752), fin en
boucle sur le calendrier. v1 : icônes trop petites et grands vides (encore) → ajout d'une alerte chiffrée
« scène vide » / « icône petite » dans le kit (changement 16).

g4 en clair : nouvel angle (fin des éclipses totales, journées de 22 h il y a 400 Ma), 14 plans (3,1 coupes/10 s
contre 0,9-1,6 en g1), objets nettement plus grands, -14,4 LUFS. Le 1er jet ne progresse pas en score (80 contre
81 pour g1) : la critique relève des défauts plus fins (zoom caméra qui sort le contenu, étiquette « up » qui
traverse les sous-titres, boucle visuelle moins exacte). **Les scores de la critique sont relatifs** (même modèle,
exigence qui suit la qualité) : les mesures `analyze` et la lecture des planches sont plus fiables pour comparer.
Le journal de g4 montre aussi que le monteur **recevait les `zone_warnings` mais en corrigeait peu**, et que les
titres du kit débordaient à x 1020 par construction (ajustés à 960 px centrés) → correctifs 18-20.

g5 : 1er jet 80 (contre 77 pour g2 sur le même sujet ; plus aucun défaut d'outillage relevé : ni sous-titres
sur le contenu, ni musique, ni icône). Les reproches portent sur la synchro fine (jauge 50,7 % en retard) et la
voix. Deux erreurs de mesure découvertes grâce à g5 : (a) la critique annonçait des silences de 0,8-1,4 s alors
que la voix n'en a aucun > 0,5 s — les pauses venaient des écarts Whisper → pauses désormais acoustiques ;
(b) l'emphase de ligne **remplaçait** le débit global (+30 % → -6 %) au lieu de s'y ajouter → corrigé (relative).

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

12. **Emphase vocale par ligne** : `narration.txt` accepte `[rate=-4% pitch=+12Hz] Nous !` (synthèse par ligne
    puis recollage) — edge-tts n'accepte pas de SSML ; la critique trouvait les révélations « plates ».
13. **Garde-fous de zone** : le kit renvoie `zone_warnings` (élément sous y 1205, au-delà de x 995…) à la fin de
    chaque `animate` ; planches d'animation avec la bande des sous-titres en rouge. Cause n° 1 du 77 de g2 v1.
14. **Musique** : silences de début/fin retirés avant mixage (intro muette pendant le hook), piste Freesound
    choisie plus longue que la voix + 6 s (fin de vidéo sans musique). Icône calendrier (texte « JUL ») retirée.
15. Sous-titres : ponctuation isolée rattachée au mot (« : » seul à l'écran) ; kit : mot-clé affiché dès la coupe
    (débuts de plan presque vides relevés par la critique dans g1 et g2).

16. **Alerte « scène vide »** : à la fin de chaque animation, le kit mesure la part de la zone utile couverte
    par les éléments (< 28 % → alerte) et signale les icônes isolées < 170 px. C'était le défaut n° 1 des
    critiques v1 de g1, g2 et g3 malgré la règle écrite « remplir l'écran ».
17. Voix : nombres en chiffres dans `subtitles.txt` (« 23 », « 50,7 % ») — l'alignement Whisper le gère.

18. Kit : titres, textes et compteurs ajustés à 820 px de large (débordaient jusqu'à x 1020) ; alerte « droite »
    dès x 970 (règle x ≤ 960) ; faux positif « icône 0 px » retiré ; alerte texte recouvert par une icône.
19. Contrôle des zones **échantillonné toutes les 0,5 s** pendant le rendu (et plus seulement à la dernière
    image) : les zooms caméra et entrées « up » sortaient le contenu en cours de route.
20. Monteur : chaque `zone_warnings` se corrige avant le plan suivant ; hook en 2 plans (1re coupe vers
    1,5-2,2 s, contre 3,4-4,1 s mesurés sur g1-g4 et 2,4 s dans les références).
21. Sous-titres : espace élargie entre mots (`\h`, les mots se collaient) et espace insécable avant ? ! : ;.

22. `analyze` : pauses mesurées à l'énergie (trames 20 dB sous la parole) dans chaque écart Whisper — exemple
    g5 v1 : 1,36 s annoncé, 0,32 s réel. Critique : interdiction de déduire un silence de `words.json`.
23. Emphase vocale relative au réglage global (`[rate=-4%]` = 4 points plus lent que le reste).

## Choix rejetés
- Capture d'écran CDP (`Page.captureScreenshot optimizeForSpeed`) pour accélérer le rendu des animations :
  0,143 s/image contre 0,172 (-17 %), gain trop faible pour toucher au moteur de rendu du bac à sable.
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
