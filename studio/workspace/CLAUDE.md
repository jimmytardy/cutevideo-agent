# Claude Studio — production d'un Short vertical 9:16

Ce dossier est le **run dir** d'une vidéo. Tout ce que tu produis reste ici, en chemins relatifs.
Seul le **scénariste** a la recherche web (WebSearch / WebFetch), pour vérifier ses faits ; les autres rôles et le
producteur ne l'utilisent pas. Les médias, la voix et le rendu passent **uniquement** par
`python -m studio.tools <commande>` (sortie JSON ; `{"error": ...}` si échec → lis le message et corrige).
**Bash n'autorise que `python -m studio.tools …`** (une commande par appel, sans `&&`, `|` ni redirection) :
pour lire, écrire ou lister des fichiers utilise Read, Write, Edit et Glob.

## Ce qui rend un Short explicatif viral (règles issues de vidéos à +100 k vues)
1. **Hook = le fait le plus surprenant, dès la 1re phrase** (≤ 2 s, ≤ 15 mots) : un paradoxe ou deux choses sans
   rapport apparent (« Le vélo a été inventé à cause d'un volcan »), une affirmation contre-intuitive chiffrée.
   Jamais « Bonjour », « Dans cette vidéo », ni une question vague (« Saviez-vous… ? »).
2. **Phrase 2 = objection anticipée puis « Sauf que… »** : on nomme ce que le spectateur croit, on le contredit.
3. **Récit concret** : dates, lieux, personnes, chiffres ; chaque chiffre est **mis à l'échelle du quotidien**
   (« depuis Paris, c'est comme entendre une explosion à Moscou »).
4. **Relances** : une micro-relance toutes les 5-8 s (retournement, chiffre, question) et une relance explicite
   au milieu (« Mais attendez, le plus fou… », « Le pire, c'est que… »). Une **question au spectateur** juste
   avant la révélation clé (« À votre avis ? »).
5. **Une seule idée**, comprise par un ado de 14 ans ; zéro jargon non expliqué ; faits sûrs uniquement.
6. **Fin en boucle** : le dernier beat est inachevé et **se complète par la 1re phrase** (« Alors la prochaine fois
   que vous [geste quotidien], dites-vous que… » + hook) ; la dernière image rappelle la première. Pas de résumé,
   pas de « abonnez-vous » en fin.
7. **Débit** : conseil de la chaîne `brief.json.words_per_second` (3,1 mots/s par défaut ; 40 s à 3,1 ≈ 125 mots ;
   références virales 3,1-3,6). C'est un **repère** pour écrire et dire le texte, jamais un motif de refus à lui seul.
   Durée cible : `brief.json.target_duration_s` — viser ±10 %, tolérer ±15 % (au-delà, le signaler), bloquant au-delà de ±20 %.

## Direction visuelle : selon `brief.json.visual_style` (style de la chaîne, imposé)
- `animation` (défaut) : `scenario.visual_mode` au choix — `animation` pour **concepts, mécanismes, histoires,
  chiffres**, `mixed` quand de vraies images apportent vraiment (lieu réel, objet réel, photo historique), `footage` rare.
- `mixed` : `visual_mode` = `mixed`. **Vraies photos/vidéos** des banques libres pour tout ce qui existe : lieux,
  animaux, objets, personnes, faits historiques ; **animations** pour les chiffres, comparaisons, cartes et mécanismes.
  Viser au moins la moitié des plans en images réelles.
- `realistic` : `visual_mode` = `footage` (ou `mixed`) : images réelles sur presque tous les plans, animations
  seulement pour les données (chiffre, carte, comparaison) ; `ai-image` en dernier recours, dans son plafond.
- `motion3d` : `visual_mode` = `animation` (ou `mixed`) ; **2 à 4 plans clés en 3D** (accroche, chiffre choc,
  révélation : beats dont le `visual_intent` commence par « 3D : »), les autres avec le kit 2D, même charte.
  Kit, modèles, budget et méthode : `docs/motion3d.md`.
- `auto` : **tu choisis le style selon le sujet** — concept, mécanisme, chiffres → animation ; lieux, animaux,
  personnes, histoire → mixed ou footage ; produit, technologie, appli, record spectaculaire → 3D sur les plans clés
  si `brief.json.motion3d` est vrai. Le scénariste justifie ce choix dans `visual_mode` et les `visual_intent`.
- Si `brief.json.animations` = `off`, on est en `footage` ; si `templates`, seulement les modèles.
  `validate --kind scenario` refuse un `visual_mode` incompatible avec le style de la chaîne.
- **Aucune image vide à une coupe** : à t = 0 de chaque plan, le mot-clé (affiché d'office) et l'objet principal
  sont déjà là (`at: 0`, `enter: "none"`, puis `idle` ou caméra pour le mouvement) ; les suivants arrivent ensuite.
- **Une idée visuelle littérale par phrase**, et **un nouvel élément à l'écran toutes les ~2 s** (la scène se
  construit : apparition, flèche, chiffre, zoom) — jamais d'image figée plus de 3 s.
- **Mot-clé titre** en capitales en haut de chaque plan (1-3 mots, `on_screen_text`) + petites étiquettes.
- **Une charte par vidéo** : un thème (`scenario.theme`) et une couleur d'accent (`scenario.accent`) utilisés
  partout ; un objet-héros récurrent ; un enjeu visible (jauge) si le récit a une tension.
- **Zones** (1080×1920) : contenu utile y **170-1180**, x 60-960 ; sous-titres centrés à y ≈ 1290 ; tout ce qui est
  sous y 1400 et la colonne x > 960 est masqué par l'interface TikTok / Shorts.
- **Remplir l'écran** (vu sur un téléphone, le petit disparaît) : objet principal 450-700 px de large, éléments
  secondaires ≥ 180 px, étiquettes ≥ 44 px, deux objets côte à côte occupent toute la largeur utile ; préférer
  un zoom caméra sur la zone active plutôt que des éléments minuscules.
- Texte ≥ 48 px, fort contraste. Les animations n'ont pas de son : les bruitages se posent dans la timeline (`sfx`).

## Kit d'animation `anim/lib/studio.js` (à utiliser pour toutes les animations scriptées)
```html
<!doctype html><html><head><meta charset="utf-8"></head><body>
<script src="lib/studio.js"></script>
<script>
const s = Studio.scene({theme: "night", accent: "#FFB938"});   // night | space | paper | blueprint | lab
s.title("TAMBORA", {at: 0.1, sub: "la plus puissante éruption"});      // mot-clé en haut (y 330)
s.icon("volcano", {x: 540, y: 800, size: 520, at: 0.3, enter: "pop", idle: "float"});
s.tag("Indonésie · 1815", {x: 540, y: 1120, at: 0.9});                 // étiquette encadrée (fill: "accent" = pleine)
s.counter({x: 540, y: 560, from: 0, to: 2600, suffix: " km", at: 1.2}); // chiffre qui défile (+ label)
s.arrow({from: [250, 1000], to: [430, 860], at: 1.4, bend: -0.3});     // flèche tracée (dashed: true)
s.shake({at: 0.6}); s.flash({at: 2}); s.camera({at: 1.8, dur: 1, zoom: 1.2, x: 540, y: 800});
</script></body></html>
```
Éléments (tous : `at`, `dur`, `enter` pop|fade|up|down|left|right|grow|drop|none, `out` + `exit`, `idle`
float|pulse|spin|wiggle, `x`, `y`, `scale`, `rotate`, `bleed: true` pour un fond qui déborde exprès) : `title`, `text` (multi-lignes `\n`, `size`, `color`
ink|accent|accent2|muted), `tag`, `icon`, `counter`, `arrow`, `travel(icon, {from, to})` (objet qui suit un
trajet), `bar` (jauge horizontale `value` 0-1), `columns([{label, value, valueText}])`, `units(icon, n, {cols,
lit})` (tableau d'unités : 25 crânes = 25 morts), `gauge({label, from, to})` (jauge semi-circulaire, enjeu
permanent ; descends alors le titre à `y: 430`), `circle`, `rect`, `map({center: [lon, lat], mapScale,
highlight: {"France": "accent"}, points: [{lon, lat, label}], route: [[lon, lat], …]})` (inclure avant studio.js :
`lib/d3.min.js`, `lib/topojson-client.min.js`, `lib/world-110m.js`), `custom((g, el, theme) => update)` pour du
SVG libre. **Icônes** (`lib/icons/<nom>.svg`, ~350 : **liste complète en un seul Read de
`anim/lib/icons/INDEX.txt`**, pas de Glob ; une icône inconnue fait échouer le rendu) : earth, moon, sun, volcano, rocket,
atom, dna, brain, heart, skull, person, scientist, king, soldier, money, chart_up, clock, factory,
radioactive, fire, drop, wave, snowflake, tree, house, car, ship, plane, bike, fish, whale, bacteria, virus,
thinking, shocked, mind_blown, warning, check, cross, question, bomb, explosion, lightning, magnifier, hand,
ruler, scissors, mirror, cake, dice, balance, chain, thought, speech…
Polices : Poppins (déjà chargée). `window.renderFrame` est posé par la scène : rien d'autre à faire.

## Droits des médias
- Seuls les médias obtenus via `search-media` + `download`, `ai-image`, `music`, `animate-template` ou `animate` sont
  autorisés (licences tracées dans `media/credits.json`). Les icônes du kit sont libres (Apache 2.0).
- `ai-image` coûte de l'argent et est plafonné (le plafond compte les générations facturées ; relancer un prompt
  identique est repris du cache, gratuit) : dernier recours — mais « rien ne convient » inclut **une
  icône ou un média qui désigne autre chose** que le propos du plan (une main pour une pince, un flocon pour
  « l'eau bout »). Un contresens à l'écran coûte plus cher que l'image. Modèle et prompt : `docs/ai-images.md`.
- Jamais de logo de marque, de visage de célébrité identifiable ni de texte incrusté illisible.

## Animations (selon `brief.json.animations`)
- `off` : aucune animation. `templates` : seulement `animate-template`. `scripts` : modèles **et** scripts jetables.
- Une animation devient `media/anim_<name>.mp4` (sans son) → clip vidéo normal dans `timeline.json`
  (`motion: "static"`, `video_offset: 0`). **Toujours lire sa planche** `review/anim_<name>/sheet.png` (bande
  rouge = sous-titres, trait rouge = interface droite). Si la sortie contient `zone_warnings`, corrige et relance.
- Durée ≤ 12 s par animation (une animation par plan ou par beat, 2-6 s typiquement).

**Modèles** (`animate-template --template <t> --params '<json>' --duration 3 --name 04_x`) — options communes
`theme`, `accent` :
- `title` `{"text": "La Lune *s'éloigne*", "subtitle": "…"}` · `counter` `{"to": 384400, "suffix": " km", "label": "…"}`
- `bars` `{"title", "unit", "items": [{"label", "value"}]}` · `list` `{"title", "items": ["…"], "numbered": true}`
- `compare` `{"title", "sub", "left": {"label", "value", "icon", "caption"}, "right": {…}, "verdict": "820× moins"}`
- `steps` `{"title", "items": [{"icon": "moon", "text": "La Lune tire l'eau"}, …]}` (2-4 étapes, mécanisme)
- `map` `{"title", "sub", "center": [lon, lat], "mapScale": 220, "highlight": {"Indonesia": "accent"}, "points": [{"lon", "lat", "label"}], "route": [[lon, lat], …]}`
- `before_after` `{"title", "before": {"label", "icon", "caption"}, "after": {…}}`
- `paradox` `{"text": "LE VÉLO", "sub": "inventé à cause d'un volcan", "left_icon": "bike", "right_icon": "volcano"}` (hook)

**Scripts jetables** (`scripts`) : `anim/<NN>_<nom>.html` (avec le kit) ou `.py`, puis
`animate --script anim/05_orbite.html --duration 4 --name 05_orbite`. Bac à sable **sans réseau** : seuls les
fichiers de `anim/` sont accessibles. Python (numpy, matplotlib, Pillow) : lis `OUT_DIR`, `WIDTH`, `HEIGHT`, `FPS`,
`DURATION` et écris `OUT_DIR/frame_00000.png`… En cas d'erreur, l'outil renvoie le message : corrige et relance.

## Fichiers (contrats validés par `python -m studio.tools validate --kind <kind> --path <fichier>`)

`brief.json` (fourni, lecture seule) : `theme`, `niche`, `angle`, `language`, `target_duration_s`, `voice`,
`tts_engine`, `max_scenario_iterations` / `min_scenario_score` (boucle scénario, défaut 5 / 90), `max_iterations` /
`min_score` (boucle vidéo, défaut 5 / 80), `editorial_tone`, `creative_brief` (charte éditoriale de la chaîne : ton,
style narratif, interdits — à respecter), `content_plan`, `animations` (off | templates | scripts),
`visual_style` (animation | mixed | realistic | motion3d | auto : direction visuelle imposée par la chaîne),
`motion3d` (vrai : plans 3D autorisés, voir `docs/motion3d.md`).

`scenario.json` (scénariste) :
```json
{"title": "…", "hook": "première phrase exacte",
 "beats": [{"text": "phrase(s) dite(s)", "visual_intent": "ce qu'on doit voir", "on_screen_text": "MOT-CLÉ"}],
 "cta": "…", "mood": "mysterieux", "music_mood": "mysterieux",
 "visual_mode": "animation", "theme": "night", "accent": "#FFB938",
 "sources": [{"claim": "le fait vérifié", "url": "https://…", "checked": true}]}
```
`sources` : faits vérifiés sur le web par le scénariste (chiffres, dates, records, faits surprenants).
`music_mood` ∈ energique, calme, dramatique, mysterieux, inspirant, humoristique, tension, revelateur, ou "".

`scenario_critique_<N>.json` (critique-scenario, boucle scénario avant la voix) :
```json
{"iteration": 1, "score": 84, "decision": "iterate",
 "scores": {"hook": 17, "structure": 13, "valeur_verite": 15, "oralite": 13, "duree": 9, "chute_boucle": 13, "brief": 4},
 "summary": "…", "strengths": ["…"], "issues": ["…"],
 "unverified_claims": ["« 1 mètre d'envergure » : à vérifier"],
 "changes": ["beat 4 : …"]}
```
`scenario_v<N>.json` : copie du scénario noté par `scenario_critique_<N>.json` (le producteur restaure la meilleure).

`subtitles.txt`, `narration.txt`, `voice.wav`, `words.json`, `voice.json` (voix) — `voice.json` : `{"duration_s", "engine", "voice"}`.
`voice_cache/` : une synthèse par ligne de `narration.txt` ; `tts` réutilise toute ligne inchangée (`lines_reused`).

`timeline.json` (monteur) :
```json
{"voice": "voice.wav", "words": "words.json", "music": "media/music/x.mp3", "music_volume": 0.08, "subtitles": true,
 "subtitle_keywords": ["Tambora", "volcan"], "subtitle_position": "high",
 "clips": [{"media": "media/anim_01_hook.mp4", "start": 0.0, "end": 2.4, "motion": "static", "sfx": "impact"},
           {"media": "media/02_lave.mp4", "start": 2.4, "end": 5.1, "motion": "static", "video_offset": 3.0, "sfx": "whoosh", "text": "", "text_position": "top"}]}
```
Clips contigus de 0 à la durée de `voice.wav` (±0,5 s). `motion` ∈ zoom, pan_left, pan_right, static (images).
`video_offset` = seconde de départ dans la source. `text` = overlay court sur les plans **non animés** (l'animation
porte déjà son mot-clé). `sfx` ∈ "", whoosh (changement de plan), pop (apparition), click, ding (révélation),
riser (montée, finit au début du clip), impact (chiffre choc) — **sur 30-60 % des coupes, jamais deux identiques
d'affilée**. `music_volume` 0.08 ≈ musique 17 dB sous la voix (0.06-0.12). Sous-titres : mot prononcé surligné,
`subtitle_keywords` + nombres en couleur, centrés à y ≈ 1290 (`high`).

`renders/v<N>.mp4` (monteur) ; `thumbnail.json` (miniaturiste) :
`{"vertical": "thumbnails/final_9x16.png", "horizontal": "thumbnails/final_16x9.png", "text": "…", "background": "media/…"}`
(une seule fois, après la boucle, sur la vidéo finale). `publish.json` (miniaturiste, au même moment) :
`{"title": "titre ≤ 100 car.", "description": "2-3 phrases (YouTube)", "hashtags": ["#shorts", "…"],
  "tiktok_caption": "accroche ≤ 150 car.", "instagram_caption": "1-2 phrases + question"}` — hashtags ajoutés
automatiquement aux légendes, crédits médias ajoutés à la description YouTube.

`critique_<N>.json` (critique) :
```json
{"iteration": 1, "video": "renders/v1.mp4", "score": 72, "decision": "iterate",
 "scores": {"hook": 14, "retention": 10, "valeur": 12, "visuels": 14, "voix_son": 10, "sous_titres": 4, "chute_partage": 8},
 "analysis": {"source": "claude", "path": "review/v1/analysis/analysis.json", "flags": ["…"]},
 "summary": "…", "strengths": ["…"], "issues": ["…"],
 "changes": [{"role": "monteur", "instruction": "plan 4 (11,2-14,0 s) : …"},
             {"role": "voix", "lines": [6], "instruction": "« ingénieurs » avalé : ralentir la ligne"}]}
```
`role` ∈ voix, monteur : le scénario est déjà validé par la boucle scénario (`scenariste` est refusé) ; `voix`
exige `lines` (numéros de ligne de `narration.txt`, 1 = première). La miniature n'est pas critiquée.

`result.json` (orchestrateur, en dernier) : `{"status": "approved|max_iterations|failed", "iterations": N, "final_video": "renders/vK.mp4", "notes": "…"}`.

## Outils
| Commande | Usage |
|---|---|
| `search-media --query "volcano eruption" [--type image\|video] [--sources pexels,pixabay,unsplash,coverr,wikimedia,nasa,europeana,internet_archive,gallica]` | requêtes **en anglais**, 2-4 mots concrets ; ids `cN` |
| `preview --ids c1,c4,c7` | planche contact PNG (≤ 12) → **Read** avant de choisir |
| `download --id c4 --name 03_lave` | → `media/03_lave.<ext>` + crédits |
| `ai-image --prompt "…" --name 05_carte [--model flux_2_dev] [--aspect 16:9]` | image IA 9:16 (dernier recours ; un prompt déjà généré est repris du cache, gratuitement et hors plafond → `reused: true` ; modèles autorisés et écriture du prompt : `docs/ai-images.md`) |
| `music --mood dramatique` | musique libre → `media/music/…` |
| `tts --text-file narration.txt [--mood …] [--rate +8%] [--pitch -2Hz] [--max-pause 0.4]` | → `voice.wav` (Azure → Gemini → edge ; une synthèse par ligne, lignes inchangées reprises de `voice_cache/` ; silences > 0,4 s raccourcis ; préfixe de ligne `[rate=-4% pitch=+12Hz mood=dramatique style=whispering]` = réglage de cette ligne seule, voir le rôle voix) |
| `transcribe --text-file subtitles.txt` | `voice.wav` → `words.json` (timings Whisper, orthographe du script) |
| `cues --start 26.68 --end 29.9` | mots du plan avec `at` relatif au début du plan → valeurs `at` exactes pour le kit |
| `render --out renders/v1.mp4` | rend `timeline.json` (plusieurs minutes : normal ; les plans inchangés depuis le rendu précédent sont repris sans ré-encodage : `clips_reused`) |
| `frames --video renders/v1.mp4 [--every 2]` | frames + `review/v1/sheet.png` + loudness |
| `analyze --video renders/v1.mp4 [--words words.json] [--timeline timeline.json]` | analyse multimodale : avis Gemini si dispo, sinon planches hook/chronologie/coupes, débit, pauses, loudness, rapport voix/fond, intonation, spectrogramme + alertes |
| `thumbnail --background media/x.jpg --text "MOT\|CHOC" --out thumbnails/final_9x16.png [--aspect 16:9] [--position top\|center\|bottom] [--color yellow]` | miniature |
| `animate-template --template <modèle> --params '{…}' --duration 3 --name 04_x [--preview]` | animation prête → `media/anim_04_x.mp4` (modèles 3D `phone3d`, `number3d` : `docs/motion3d.md`) |
| `animate --script anim/05_x.html\|.py --duration 4 --name 05_x [--3d] [--preview]` | rend un script jetable (bac à sable) ; `--3d` : scène `studio3d.js` (si `brief.json.motion3d`) ; `--preview` : planche de 6 images sans vidéo |
| `probe --path … [--loudness]` / `validate --kind … --path …` | contrôle |
