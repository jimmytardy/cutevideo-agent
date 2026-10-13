# Claude Studio — production d'un Short vertical 9:16

Ce dossier est le **run dir** d'une vidéo. Tout ce que tu produis reste ici, en chemins relatifs.
Tu n'as pas accès à Internet directement : les médias, la voix et le rendu passent **uniquement** par
`python -m studio.tools <commande>` (sortie JSON ; `{"error": ...}` si échec → lis le message et corrige).
**Bash n'autorise que `python -m studio.tools …`** (une commande par appel, sans `&&`, `|` ni redirection) :
pour lire, écrire ou lister des fichiers utilise Read, Write, Edit et Glob.

## Règles éditoriales d'un Short
- Durée cible : celle de `brief.json` (`target_duration_s`), tolérance ±15 %.
- Langue : `brief.json.language` (français par défaut), ton parlé, phrases courtes, zéro jargon non expliqué.
- **Hook < 2 s** : la première phrase crée une tension, une promesse ou un paradoxe. Pas de « Bonjour », pas de « Dans cette vidéo ».
- Un changement de plan toutes les **2 à 4 s**. Chaque plan illustre ce qui est dit *à ce moment-là*.
- Faits : uniquement des faits dont tu es sûr ; pas de chiffres inventés. Dans le doute, formule prudemment.
- Fin : chute ou relance (question, révélation, CTA court), pas de résumé.

## Droits des médias
- Seuls les médias obtenus via `search-media` + `download`, `ai-image` ou `music` sont autorisés : leurs licences
  sont vérifiées et tracées dans `media/credits.json` (crédits ajoutés automatiquement à la description).
- `ai-image` coûte de l'argent et est plafonné : dernier recours quand aucune banque n'a de visuel pertinent.
- Jamais de logo de marque, de visage de célébrité identifiable ni de texte incrusté illisible dans un visuel.

## Fichiers (contrats validés par `python -m studio.tools validate --kind <kind> --path <fichier>`)

`brief.json` (fourni, lecture seule) : `theme`, `niche`, `angle`, `language`, `target_duration_s`, `voice`,
`tts_engine`, `max_iterations`, `min_score`, `editorial_tone`, `content_plan`.

`scenario.json` (scénariste) :
```json
{"title": "…", "hook": "première phrase exacte",
 "beats": [{"text": "phrase(s) dite(s)", "visual_intent": "ce qu'on doit voir", "on_screen_text": "texte court optionnel"}],
 "cta": "…", "mood": "dramatique", "music_mood": "dramatique",
 "publish": {"title": "titre YouTube ≤ 100 car.", "description": "2-3 phrases", "hashtags": ["#shorts", "…"]}}
```
`music_mood` ∈ energique, calme, dramatique, mysterieux, inspirant, humoristique, tension, revelateur, ou "" (sans musique).

`subtitles.txt`, `narration.txt`, `voice.wav`, `words.json`, `voice.json` (voix) — `voice.json` : `{"duration_s", "engine", "voice"}`.

`timeline.json` (monteur) :
```json
{"voice": "voice.wav", "words": "words.json", "music": "media/music/x.mp3", "music_volume": 0.08, "subtitles": true,
 "clips": [{"media": "media/01_hook.jpg", "start": 0.0, "end": 2.4, "motion": "zoom", "text": "", "text_position": "top"},
           {"media": "media/02_lave.mp4", "start": 2.4, "end": 5.1, "motion": "static", "video_offset": 3.0}]}
```
Clips contigus de 0 à la durée de `voice.wav` (±0,5 s). `motion` ∈ zoom, pan_left, pan_right, static (images ; ignoré pour les vidéos).
`video_offset` = seconde de départ dans la vidéo source. `text` = overlay court (≤ 6 mots), les sous-titres karaoké sont ajoutés automatiquement en bas.

`renders/v<N>.mp4` (monteur, itération N) ; `thumbnail.json` (miniaturiste) :
`{"vertical": "thumbnails/v<N>_9x16.png", "horizontal": "thumbnails/v<N>_16x9.png", "text": "…", "background": "media/…"}`.

`critique_<N>.json` (critique) :
```json
{"iteration": 1, "video": "renders/v1.mp4", "score": 72, "decision": "iterate",
 "summary": "…", "strengths": ["…"], "issues": ["…"],
 "changes": [{"role": "monteur", "instruction": "remplacer le plan 3 (12-15 s) par …"}]}
```
`role` ∈ scenariste, voix, monteur, miniaturiste.

`result.json` (orchestrateur, en dernier) : `{"status": "approved|max_iterations|failed", "iterations": N, "final_video": "renders/vK.mp4", "notes": "…"}`.

## Outils
| Commande | Usage |
|---|---|
| `search-media --query "volcano eruption" [--type image\|video] [--sources pexels,pixabay,unsplash,coverr,wikimedia,nasa,europeana,internet_archive,gallica]` | requêtes **en anglais**, 2-4 mots concrets ; renvoie des ids `cN` |
| `preview --ids c1,c4,c7` | planche contact PNG (≤ 12) → **regarde-la avec Read** avant de choisir |
| `download --id c4 --name 03_lave` | → `media/03_lave.<ext>` + crédits |
| `ai-image --prompt "…" --name 05_carte` | image IA 9:16 (dernier recours) |
| `music --mood dramatique` | musique libre → `media/music/…` |
| `tts --text-file narration.txt [--mood …] [--rate +5%] [--style …]` | → `voice.wav` (repli automatique Azure → Gemini → edge) |
| `transcribe --text-file subtitles.txt` | `voice.wav` → `words.json` (timestamps Whisper, orthographe du script) + transcript entendu |
| `render --out renders/v1.mp4` | rend `timeline.json` (plusieurs minutes : normal) |
| `frames --video renders/v1.mp4 [--every 2]` | frames + `review/v1/sheet.png` + loudness |
| `thumbnail --background media/x.jpg --text "MOT|CHOC" --out thumbnails/v1_9x16.png [--aspect 16:9] [--position top\|center\|bottom] [--color yellow]` | miniature |
| `probe --path … [--loudness]` / `validate --kind … --path …` | contrôle |
