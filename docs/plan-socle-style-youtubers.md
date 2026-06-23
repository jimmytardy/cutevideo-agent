# Socle "style grands YouTubers" — pistes P1, P3, P4, P5

## Context

L'utilisateur a analysé TheGreatReview, EGO et Trash et en a tiré 5 principes universels.
Verdict d'audit : **le pipeline touche déjà le cœur des 5 principes** (timeline de beats ancrée
sur la narration, hot-path `filter_graph_builder`, décisions créatives `montage_decisions`,
SFX synthétisés `sound_design`, étalonnage léger `color_grade_from_style_block`, sous-titres
karaoke ASS). Il manque le **niveau supérieur** de chaque principe. L'objectif est de combler
ces écarts pour que ces principes deviennent le **socle explicite** des agents, en **long format
(16:9) ET shorts (9:16)**, en **qualité max** (encodes plus longs acceptés).

Parallaxe / 2.5D (P2) est **hors scope de cette première couche** (différée — voir Extensions).

Principe → état actuel → écart à combler :

| # | Principe | Déjà là | À ajouter |
|---|----------|---------|-----------|
| P1 | Le son dicte l'image | whoosh/accent synced cuts+reveals, ducking sidechain, musique par mood | palette SFX (pop sur texte, impact basse sur chiffre), coupure/silence musique sur révélation, bed d'ambiance synthétisé |
| P3 | Texte graphique dynamique | drawtext fade/slide/pulse, karaoke shorts | pop-bounce, typewriter, mask reveal, surlignage des mots/chiffres clés, glow néon |
| P4 | Rythme & ruptures | 17 transitions xfade + defaults mood, beats, punch_zoom | glitch / flash blanc / déchirure d'impact, cadence 3-6s long format, punch-in renforcé sur révélation |
| P5 | Textures & étalonnage | colorbalance+eq par style | grain pellicule, light leaks, VHS/CRT, LUT 3D par thème, correction par source |

---

## Approche générale

Tout passe par les **points d'extension existants** ; aucune nouvelle architecture. Tous les
encodes lourds continuent de passer par `run_ffmpeg()` + `thread_args()` + `filter_thread_args()`
(garde-fous CPU intacts), et tout fan-out par `bounded_gather()`.

Nouveaux réglages par principe dans `data/agent_config.json` (+ override par chaîne via
`Channel.config`, résolus par `resolve_channel_config()`), pour que chaque chaîne puisse doser
l'intensité du style. Aliases tolérants comme `STYLE_ALIASES` côté SSML.

---

## P1 — Son réactif (`agent/skills/audio/sound_design.py`, `audio_mixer.py`, `editor_agent.py`)

1. **Élargir la palette SFX.** `SfxCue.kind` ne connaît que `whoosh`/`accent`. Ajouter :
   - `pop` — apparition de texte (sine courte ~0.2s + click filtré).
   - `impact` — révélation de chiffre/stat (sub-bass `sine=frequency=55` + boom court).
   - `riser` — montée avant rupture de chapitre (sweep `anoisesrc` + highpass croissant).
   Étendre `_synth_input()` (recettes lavfi par kind), `_shape_filter()` (enveloppe par kind),
   et les constantes de gain/durée. Les recettes restent **synthétisées** (cohérent avec la
   note mémoire « SFX synthétisés, pas d'assets »), le manifest CC0 reste un fallback opt-in.
2. **Lier les SFX aux events visuels.** Aujourd'hui `build_sfx_cues` se base sur les segments et
   `build_beat_cut_cues` sur les cuts. Ajouter `build_overlay_cues(plan)` qui lit le
   `montage_plan` (beats avec `overlay_mode`/`on_screen_text`) pour placer un `pop` à
   l'apparition de chaque overlay texte, et un `impact` sur `visual_type == "statistic_highlight"`.
   Réutiliser `collect_clip_cut_times` (montage_plan.py) comme modèle. Brancher dans
   `editor_agent._apply_sound_design()` via `merge_sfx_cues()`.
3. **Coupure/silence musique sur révélation.** Distinct du ducking sidechain permanent : ajouter
   dans `audio_mixer.py` une **automation de volume** (`volume=...:enable='between(t,a,b)'` ou
   enveloppe `volume` expr) qui plonge la musique à ~0 pendant ~250-400ms à chaque timestamp de
   révélation, puis remonte. Piloté par les mêmes cues `accent`/`impact`. Câblé depuis
   `editor_agent._mix_music_by_mood()`.
4. **Bed d'ambiance synthétisé (foley léger).** Optionnel par thème : room-tone / vent / foule
   synthétisés (`anoisesrc` filtré + reverb légère) mixés très bas (~-30dB) sous les segments
   sans audio source. Nouveau helper dans `sound_design.py`, activé par flag config
   `sound_design.ambient_bed.enabled`.

Config : nouveau bloc `sound_design.sfx_palette` (gains/durées par kind) + `music_reveal_cut`
+ `ambient_bed` dans `data/agent_config.json`.

---

## P3 — Texte animé (nouveau `agent/skills/video/animated_text.py` + `filter_graph_builder.py`)

Décision clé : **`drawtext` ne peut pas animer l'échelle** (fontsize statique) ⇒ pop-bounce /
typewriter / glow ne sont pas faisables proprement en drawtext. On route le texte on-screen
**riche** par **ASS (libass)**, en réutilisant l'infra déjà présente dans
`viral_subtitles.py` (`build_karaoke_ass`/`burn_ass_subtitles`).

1. **Nouveau renderer `animated_text.py`** : génère un fichier ASS d'overlays on-screen à
   l'échelle de la timeline (positions/timing des beats avec `on_screen_text`), avec styles
   d'animation choisis par `montage_decisions` :
   - `pop_bounce` — `\t` scale 0→120→100% (ease) + `\fad`.
   - `typewriter` — révélation progressive (events Dialogue échelonnés ou `\k` masqué).
   - `mask_reveal` — `\clip` animé via `\t`.
   - `highlight` — couleur fluo / `\3c` encadré sur les mots/chiffres clés (détection regex
     nombres + mots en MAJ, comme `viral_subtitles._build_karaoke_text`).
   - `neon_glow` — `\blur` + `\3c` lumineux sur fond sombre.
2. **Application** : burn ASS une seule fois à l'assemblage (pass dédié, comme les sous-titres),
   plutôt que par segment. `drawtext` reste le **fallback** si ASS indisponible (le chemin
   `overlay_mode == "drawtext"` de `filter_graph_builder` est conservé).
3. **Sélection du style** : `montage_decisions.resolve_overlay_mode()` renvoie déjà `drawtext`/
   `svg_overlay`/`none` ; ajouter une fonction `resolve_text_animation(visual_type, hook_type)`
   qui mappe vers un des styles ci-dessus (ex. `statistic_highlight` → `pop_bounce`+`highlight`,
   `quote_card` → `typewriter`).

Config : bloc `text_overlays.animation` (style par visual_type, couleurs highlight, intensité glow).

---

## P4 — Ruptures & rythme (`montage_decisions.py`, `filter_graph_builder.py`, `beat_timeline.py`, config)

1. **Transitions d'impact.** Le flash blanc existe déjà (`fadewhite`/`fadeblack` dans le catalog).
   Ajouter :
   - `glitch` — traité **hors xfade** : sur ~5-8 frames au cut, décalage chromatique
     (`rgbashift`) + `noise` + saut vertical. Géré comme cas spécial dans
     `build_segment_filter_complex` (branche à part de la chaîne xfade).
   - `flash_impact` — fadewhite court + `riser` SFX (P1) sur changement de chapitre.
   - déchirure : mapper sur les `wipe*`/`slice*` déjà au catalog.
   `resolve_transition()` apprend à émettre ces types sur ruptures de chapitre / hooks.
2. **Cadence 3-6s en long format.** Aujourd'hui implicite (beats). Ajouter dans `beat_timeline`/
   `pacing_director` une règle `max_visual_hold_s` (config) : si un beat dépasse la fenêtre,
   forcer un changement visuel (nouveau plan, ou alternance Ken Burns / punch_zoom) pour casser
   la staticité. Knob `pacing.max_visual_hold_s` (long: ~5s, short: déjà ~2.5s via `beat_slot_s`).
3. **Punch-in renforcé sur révélation.** `punch_zoom` existe (`_build_motion_vf`, +8%). Le forcer
   sur les beats `statistic_highlight`/hook révélation via `resolve_motion_style` (motion_hint).
4. **Match cuts** : différé (nécessite analyse de contenu fiable) — noté en Extensions, pas dans
   cette couche.

Config : `transitions.impact` (glitch/flash params) + `pacing.max_visual_hold_s`.

---

## P5 — Textures & étalonnage (`filter_graph_builder.py`, config)

Tout s'ajoute dans `build_segment_filter_complex`, **dans le même pass libx264** que le `grade`
existant (efficace — pas de pass supplémentaire), juste après l'étape `grade` sur `out_label`.

1. **LUT 3D par thème.** Étendre `color_grade_from_style_block` → si un `.cube` est configuré pour
   le thème, ajouter `lut3d=file=...` à la chaîne de grade (plus puissant que colorbalance/eq,
   qui restent le fallback). LUTs stockés dans `data/luts/`.
2. **Overlays de texture** (nouveau `build_texture_vf`, intensité par config) :
   - grain pellicule — `noise=alls=<intensité>:allf=t+u`.
   - vignette — `vignette`.
   - light leak — overlay d'un dégradé animé (`geq`/`gradients` blend `screen`) périodique.
   - VHS/CRT — `rgbashift` + scanlines (`geq`) + légère désat, en preset opt-in.
3. **Correction par source.** Tag déjà disponible via `visual_type`/`asset_type` ; appliquer un
   pré-grade léger aux plans `archival_footage` (désat + grain renforcé) avant la chaîne commune,
   pour unifier 4K / archive / jeu.

Config : `video.texture` (grain/vignette/leak/vhs intensités, on/off par thème) +
`video.grade.lut_by_theme`.

---

## Fichiers à modifier (récapitulatif)

- `agent/skills/audio/sound_design.py` — palette SFX, cues overlay/reveal, bed d'ambiance.
- `agent/skills/audio/audio_mixer.py` — coupure musique sur révélation.
- `agent/skills/video/animated_text.py` — **nouveau**, renderer ASS animé (réutilise `viral_subtitles`).
- `agent/skills/video/filter_graph_builder.py` — glitch transition, textures, LUT, hook texte ASS.
- `agent/skills/video/montage_decisions.py` — `resolve_text_animation`, transitions d'impact, punch sur reveal.
- `agent/skills/video/beat_timeline.py` / `pacing_director.py` — `max_visual_hold_s`.
- `agent/agents/editor_agent.py` — câbler nouveaux cues, mix reveal, overlay ASS, texture/LUT.
- `data/agent_config.json` — nouveaux blocs config (+ schéma `ChannelRuntimeConfig` si typé).
- `graphify update .` après l'ajout de `animated_text.py`.

Implémentation par tranches indépendantes et testables : **P5 (textures/grade)** puis **P1 (SFX)**
sont les plus isolés (filtres/cues additifs) → bons premiers incréments. **P3 (texte ASS)** et
**P4 (cadence/glitch)** touchent davantage la timeline.

---

## Dimensionnement VPS (qualité max)

Le calcul lourd est **100% CPU** (pas de GPU requis) car génération d'images (Flux/Imagen) et
TTS (edge/Azure) sont des **API externes**. Les deux postes CPU locaux :
- **ffmpeg `-filter_complex`** (editor : Ken Burns + xfade + grain + LUT + glitch + ASS) — dominant.
- **faster-whisper `large-v3`** sur CPU (transcription post-TTS pour les beats/sous-titres).

Garde-fous en place : `run_ffmpeg()` sémaphore = **1 ffmpeg à la fois**, `max_concurrent_pipelines=1`.
Donc on dimensionne pour **une vidéo à la fois**, en réglant `FFMPEG_THREADS` / `WHISPER_CPU_THREADS`.

| Profil | vCPU | RAM | Pour quoi | Réglages |
|--------|------|-----|-----------|----------|
| Minimum viable | 4 | 8 Go | 1 chaîne, qualité max, lent (whisper large-v3 ~ x1-2 temps réel, encodes longs) | `FFMPEG_THREADS=4`, `FFMPEG_PRESET=medium` |
| **Recommandé** | **8** | **16 Go** | 1 chaîne confortable en qualité max, marge pour grain/LUT/glitch + whisper | `FFMPEG_THREADS=6`, `WHISPER_CPU_THREADS=8`, `FFMPEG_PRESET=medium` |
| Multi-chaînes / débit | 16 | 32 Go | plusieurs pipelines (monter `max_concurrent_pipelines`) ou rendu rapide | `FFMPEG_THREADS=8`, sémaphore éventuellement >1 |

Notes :
- **RAM** : `large-v3` ≈ 3 Go, libx264 1080p + filter_complex chargé ≈ 1-2 Go ; Postgres+Redis+API
  Next ≈ 2-3 Go. 16 Go laisse une marge saine ; 8 Go tient si on ne fait rien d'autre en parallèle.
- **Disque** : prévoir 30-50 Go SSD (assets médias téléchargés + rendus intermédiaires ; nettoyage
  S3 quotidien à 03:00 déjà en place).
- **GPU** : inutile sauf si un jour Whisper local accéléré ou génération d'images **locale** (Flux
  self-hosted) — alors viser une carte ≥ 12 Go VRAM. Non requis pour ce socle.
- Repère qualité max sur **8 vCPU** : compter ~2-4× la durée de la vidéo pour le rendu complet
  d'une vidéo longue (la couche P5 grain/LUT/glitch ajoute ~15-30% au temps d'encode).

---

## Vérification

1. `pytest` — ajouter des tests unitaires par tranche :
   - `sound_design` : nouveaux kinds présents dans `_synth_input`/`_shape_filter`, cues overlay
     placés aux bons timestamps (`build_overlay_cues`).
   - `animated_text` : ASS bien formé pour chaque style, highlight détecté sur chiffres.
   - `filter_graph_builder` : la chaîne contient `lut3d`/`noise`/`rgbashift` quand activé,
     l'ordre des filtres (grade → texture) est correct, fallback drawtext intact.
   - `montage_decisions` : `resolve_text_animation` et transitions d'impact sur reveal.
2. Rendu bout-en-bout : lancer un `Project` via l'orchestrateur (ou trigger agent
   `EditorAgent`) sur un scénario court avec un beat `statistic_highlight` + un hook révélation,
   et vérifier sur le rendu : pop+impact audio synchronisés, texte animé, flash/glitch sur
   rupture, grain/LUT visibles. **ffmpeg doit être installé** (absent du shell dev d'après la
   note mémoire — installer sur le VPS / l'env de test).
3. Surveiller la charge : confirmer qu'un seul ffmpeg tourne (`run_ffmpeg` sémaphore) et que
   `FFMPEG_THREADS`/filter-threads sont respectés sous `-filter_complex` (sinon saturation CPU).
4. `graphify update .` puis `graphify query` pour vérifier que `animated_text.py` est bien relié.

---

## Extensions différées (hors première couche)

- **P2 — Parallaxe / 2.5D** : séparation sujet/fond (depth-map ou masque) + animation multi-calques.
  Coûteux ; à activer opt-in par beat une fois le socle stable.
- **Match cuts** (P4) : transitions géométriques/mouvement entre plans — nécessite analyse de
  contenu fiable.
- **Assets SFX/musique CC0** réels en complément des synthèses (manifest déjà prévu).
