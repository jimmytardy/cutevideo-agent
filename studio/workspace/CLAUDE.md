# Claude Studio — production d'un Short vertical 9:16

Ce dossier est le **run dir** d'une vidéo. Tout ce que tu produis reste ici, en chemins relatifs.
Tu n'as pas accès à Internet directement : les médias, la voix et le rendu passent **uniquement** par
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
7. **Débit** : ~2,9 mots/s (40 s ≈ 115 mots). Durée cible : `brief.json.target_duration_s`, tolérance ±15 %.

## Direction visuelle : full animation par défaut
- `scenario.visual_mode` : `animation` (défaut, **concepts, mécanismes, histoires, chiffres**), `mixed` (animation +
  vraies images quand elles apportent vraiment : lieu réel, objet réel, photo historique), `footage` (rare).
  Si `brief.json.animations` = `off`, on est en `footage` ; si `templates`, seulement les modèles.
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
float|pulse|spin|wiggle, `x`, `y`, `scale`, `rotate`) : `title`, `text` (multi-lignes `\n`, `size`, `color`
ink|accent|accent2|muted), `tag`, `icon`, `counter`, `arrow`, `travel(icon, {from, to})` (objet qui suit un
trajet), `bar` (jauge horizontale `value` 0-1), `columns([{label, value, valueText}])`, `units(icon, n, {cols,
lit})` (tableau d'unités : 25 crânes = 25 morts), `gauge({label, from, to})` (jauge semi-circulaire, enjeu
permanent ; descends alors le titre à `y: 430`), `circle`, `rect`, `map({center: [lon, lat], mapScale,
highlight: {"France": "accent"}, points: [{lon, lat, label}], route: [[lon, lat], …]})` (inclure avant studio.js :
`lib/d3.min.js`, `lib/topojson-client.min.js`, `lib/world-110m.js`), `custom((g, el, theme) => update)` pour du
SVG libre. **Icônes** (`lib/icons/<nom>.svg`, ~350 : **liste complète en un seul Read de
`anim/lib/icons/INDEX.txt`**, pas de Glob ; une icône inconnue fait échouer le rendu) : earth, moon, sun, volcano, rocket,
atom, dna, brain, heart, skull, person, scientist, king, soldier, money, chart_up, clock, calendar, factory,
radioactive, fire, drop, wave, snowflake, tree, house, car, ship, plane, bike, fish, whale, bacteria, virus,
thinking, shocked, mind_blown, warning, check, cross, question, bomb, explosion, lightning, magnifier, hand,
ruler, scissors, mirror, cake, dice, balance, chain, thought, speech…
Polices : Poppins (déjà chargée). `window.renderFrame` est posé par la scène : rien d'autre à faire.

## Droits des médias
- Seuls les médias obtenus via `search-media` + `download`, `ai-image`, `music`, `animate-template` ou `animate` sont
  autorisés (licences tracées dans `media/credits.json`). Les icônes du kit sont libres (Apache 2.0).
- `ai-image` coûte de l'argent et est plafonné : dernier recours.
- Jamais de logo de marque, de visage de célébrité identifiable ni de texte incrusté illisible.

## Animations (selon `brief.json.animations`)
- `off` : aucune animation. `templates` : seulement `animate-template`. `scripts` : modèles **et** scripts jetables.
- Une animation devient `media/anim_<name>.mp4` (sans son) → clip vidéo normal dans `timeline.json`
  (`motion: "static"`, `video_offset: 0`). **Toujours lire sa planche** `review/anim_<name>/sheet.png`.
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
`tts_engine`, `max_iterations`, `min_score`, `editorial_tone`, `content_plan`, `animations` (off | templates | scripts).

`scenario.json` (scénariste) :
```json
{"title": "…", "hook": "première phrase exacte",
 "beats": [{"text": "phrase(s) dite(s)", "visual_intent": "ce qu'on doit voir", "on_screen_text": "MOT-CLÉ"}],
 "cta": "…", "mood": "mysterieux", "music_mood": "mysterieux",
 "visual_mode": "animation", "theme": "night", "accent": "#FFB938",
 "publish": {"title": "titre ≤ 100 car.", "description": "2-3 phrases", "hashtags": ["#shorts", "…"]}}
```
`music_mood` ∈ energique, calme, dramatique, mysterieux, inspirant, humoristique, tension, revelateur, ou "".

`subtitles.txt`, `narration.txt`, `voice.wav`, `words.json`, `voice.json` (voix) — `voice.json` : `{"duration_s", "engine", "voice"}`.

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
`{"vertical": "thumbnails/v<N>_9x16.png", "horizontal": "thumbnails/v<N>_16x9.png", "text": "…", "background": "media/…"}`.

`critique_<N>.json` (critique) :
```json
{"iteration": 1, "video": "renders/v1.mp4", "score": 72, "decision": "iterate",
 "scores": {"hook": 14, "retention": 10, "valeur": 12, "visuels": 14, "voix_son": 10, "sous_titres": 4, "chute_partage": 8},
 "analysis": {"source": "claude", "path": "review/v1/analysis/analysis.json", "flags": ["…"]},
 "summary": "…", "strengths": ["…"], "issues": ["…"],
 "changes": [{"role": "monteur", "instruction": "plan 4 (11,2-14,0 s) : …"}]}
```
`role` ∈ scenariste, voix, monteur, miniaturiste.

`result.json` (orchestrateur, en dernier) : `{"status": "approved|max_iterations|failed", "iterations": N, "final_video": "renders/vK.mp4", "notes": "…"}`.

## Outils
| Commande | Usage |
|---|---|
| `search-media --query "volcano eruption" [--type image\|video] [--sources pexels,pixabay,unsplash,coverr,wikimedia,nasa,europeana,internet_archive,gallica]` | requêtes **en anglais**, 2-4 mots concrets ; ids `cN` |
| `preview --ids c1,c4,c7` | planche contact PNG (≤ 12) → **Read** avant de choisir |
| `download --id c4 --name 03_lave` | → `media/03_lave.<ext>` + crédits |
| `ai-image --prompt "…" --name 05_carte` | image IA 9:16 (dernier recours) |
| `music --mood dramatique` | musique libre → `media/music/…` |
| `tts --text-file narration.txt [--mood …] [--rate +8%] [--pitch -2Hz] [--max-pause 0.4]` | → `voice.wav` (Azure → Gemini → edge ; silences > 0,4 s raccourcis) |
| `transcribe --text-file subtitles.txt` | `voice.wav` → `words.json` (timings Whisper, orthographe du script) |
| `render --out renders/v1.mp4` | rend `timeline.json` (plusieurs minutes : normal) |
| `frames --video renders/v1.mp4 [--every 2]` | frames + `review/v1/sheet.png` + loudness |
| `analyze --video renders/v1.mp4 [--words words.json] [--timeline timeline.json]` | analyse multimodale : avis Gemini si dispo, sinon planches hook/chronologie/coupes, débit, pauses, loudness, rapport voix/fond, intonation, spectrogramme + alertes |
| `thumbnail --background media/x.jpg --text "MOT\|CHOC" --out thumbnails/v1_9x16.png [--aspect 16:9] [--position top\|center\|bottom] [--color yellow]` | miniature |
| `animate-template --template <modèle> --params '{…}' --duration 3 --name 04_x` | animation prête → `media/anim_04_x.mp4` |
| `animate --script anim/05_x.html\|.py --duration 4 --name 05_x` | rend un script jetable (bac à sable) |
| `probe --path … [--loudness]` / `validate --kind … --path …` | contrôle |
