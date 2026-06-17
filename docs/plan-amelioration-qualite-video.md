# Plan d'amélioration de la qualité de la vidéo finale

> Audit du pipeline multi-agents (lecture du code + des prompts) + bonnes pratiques
> de génération image/vidéo. Objectif : améliorer la qualité perçue de la vidéo finale
> (pertinence visuelle, cohérence esthétique, rythme, accroche, métadonnées).

---

## 1. Rappel de l'enchaînement réel des agents

Source : `agent/core/orchestrator.py` (`AGENT_ORDER`, `_run_main_loop`).

### Pipeline de création (vidéo longue)

```
research_agent          → faits vérifiés (Gemini + Google Search)
scenario_agent          → structure narrative, segments, narration, delivery_style, keywords
   ├─ fact_checker_agent (boucle, max 3) → corrige les faits faux
   └─ hook_optimizer_agent              → réécrit le segment 1 (hook)
narrator_agent          → TTS par segment + timestamps Whisper
beat_planner_agent      → découpe la narration en visual_beats (post-TTS) + enrichit chaque beat (LLM)
diagram_specialist_agent→ enrichit les beats de type schéma/infographie
media_agent             → 1 média par beat : recherche stock → fallback IA (Flux/Imagen)
montage_planner_agent   → effective_beats, durées, transitions, motion, overlays texte
editor_agent            → assemblage FFmpeg
subtitle_agent          → sous-titres
video_analyst_agent     → (si clé Gemini) analyse vision de la vidéo finale
critic_agent            → note /100, décide approve / iterate + point de reprise
   └─ boucle jusqu'à max_critic_iterations (5) ou score >= min_critic_score (90)
clipper_agent / short_editor_agent → dérivation shorts
```

### Points clés de génération d'image (les plus importants pour la qualité)

- **Chemin "beat" (principal, bon)** — `agent/skills/media/segment_beats_media.py:155-184` :
  `synthesize_flux_subject()` (Gemini traduit le brief FR → sujet EN, **plafonné à 200 car.**)
  puis `build_visual_prompt(beat.visual_type, subject_en, …)` avec `use_prompt_as_is=True`.
  Respecte le `visual_type` (template dédié) et le `negative_prompt` (schémas seulement).

- **Chemin "segment" (fallback, faible)** — `agent/agents/media_agent.py:927-958` et `1000-1029` :
  ```python
  ai_prompt = f"{ctx.theme} — {segment['title']} — {subject_entity} — {keywords[:3]}"
  ```
  Pas de `visual_type`, `use_prompt_as_is=False` → enveloppé par `build_documentary_prompt`
  (toujours le template « Documentary photorealistic photograph »). **Salade de mots-clés**,
  exactement ce que les guides Flux déconseillent.

- **Template final Flux** — `agent/skills/media_sources/ai/prompt_builder.py:587-612` :
  ```
  {template visual_type}. {orientation}. Theme: {cat}. Tone: {tone}. High quality. {text_rule}. No collage.
  ```
  Le sujet est **au milieu** du prompt, pas au début ; aucune indication de
  lumière/objectif/composition/palette/atmosphère au-delà de « natural lighting, high detail ».

---

## 2. Bonnes pratiques (recherche)

**Prompts d'image (Flux / Flux.2)**
- Flux gère **mieux les prompts longs et descriptifs** que la plupart des modèles : décrire
  comme on l'expliquerait à un humain, pas en mots-clés.
- **Structurer** : sujet → action → environnement → lumière → style/technique. **Layering
  premier plan → arrière-plan** pour la profondeur.
- **Mettre l'info la plus importante EN PREMIER** (Flux pondère le début du prompt).
- Pour le photoréalisme : préciser **appareil/objectif/ouverture/type de plan**, couleurs,
  textures, émotion, ambiance lumineuse.
- Flux.2 : prompts **JSON structurés**, contrôle couleur (hex), typographie propre/infographies,
  multi-référence (cohérence).

**Cohérence visuelle (vidéo IA multi-plans)**
- La dérive de style entre plans est le problème n°1 : il faut un **ancrage de style partagé**
  (référence image, LoRA, ou au minimum un *style block* identique répété mot pour mot).
- « Discipline de prompt » : mener par l'identité du sujet, **phrasé identique** d'un plan à
  l'autre (« shoulder-length dark brown », pas « brunette »).

Sources :
- [FLUX Prompting Guide — Segmind](https://blog.segmind.com/flux-prompting-guide-image-creation/)
- [FLUX.1 Prompt Guide — getimg.ai](https://getimg.ai/blog/flux-1-prompt-guide-pro-tips-and-common-mistakes-to-avoid)
- [Master FLUX.2 — Atlabs](https://www.atlabs.ai/blog/flux-2-prompting-guide)
- [Creating images with Flux — Nebius](https://nebius.com/blog/posts/creating-images-with-flux-prompt-guide)
- [Character consistency in AI video — Artlist](https://artlist.io/blog/consistent-character-ai/)
- [Maintain character consistency — Vidu](https://www.vidu.com/blog/how-to-maintain-character-consistency-in-ai-videos)

---

## 3. Diagnostic : écarts du pipeline vs bonnes pratiques

| # | Problème | Localisation | Impact |
|---|----------|--------------|--------|
| D1 | Sujet IA **plafonné à 200 car.**, prompt final pauvre (pas de lumière/objectif/compo/palette), sujet pas en tête | `prompt_synthesizer.py:27-45`, `prompt_builder.py:587-612` | Images génériques |
| D2 | Aucune **cohérence esthétique** entre beats (chaque image générée isolément) ; brand kit non injecté | tout le chemin média | Vidéo « patchwork » |
| D3 | **Fallback segment** = salade de mots-clés, sans `visual_type` ni `use_prompt_as_is` | `media_agent.py:927,1000` | Pires images quand le fallback s'active |
| D4 | **Critic aveugle aux images** sans clé Gemini : note `visual_quality` au jugé sur le résumé texte | `critic_agent.py:56-63` | Boucle qualité non fiable |
| D5 | `scenario_agent` = **méga-prompt** (titre+SEO+desc+segments+narration+voix+keywords+sources+research+feedback) | `scenario_agent.py:38-181` | Attention diluée, sorties moyennes |
| D6 | `critic_agent` mélange **6 dimensions de notation + arbre de routage + règles d'approbation** | `critic_agent.py:23-116` | Notation et routage bruités |
| D7 | **Negative prompt** uniquement sur les schémas ; rien sur les photos (blurry, deformed, watermark…) | `flux_negative_prompt.py:12-15` | Artefacts non filtrés |
| D8 | Pas d'**agent miniature (thumbnail)** ni d'agent métadonnées dédié (CTR YouTube) | absent | Perte de clics |
| D9 | Flux.2 (`flux_2_dev`) déjà configuré mais `default_plan = flux_pro` (v1.1) | `data/agent_config.json` | Adhérence prompt < potentiel |

---

## 4. Recommandations

Classées par **impact / effort**. ★ = priorité haute.

### A. Amélioration des prompts (gain rapide, fort impact)

**A1 ★ — Enrichir le prompt image (D1).**
Repenser `build_visual_prompt` (`prompt_builder.py:587`) selon Flux :
- **Sujet en premier**, puis style/technique en suffixe.
- Ajouter un *bloc cinématographie* paramétrable par `visual_type` :
  objectif/plan (« 35mm wide », « macro », « aerial drone »), lumière (« golden hour »,
  « soft studio »), profondeur de champ, palette, ambiance.
- Lever le plafond 200 car. de `synthesize_flux_subject` (`prompt_synthesizer.py:42`) à
  ~400-600 car. et demander à Gemini une **description en couches** (premier plan → fond),
  pas un résumé.
- Format : `"{subject}. {scene/layering}. {lighting}. {lens/shot}. {palette/mood}. {orientation}. {quality}. {text_rule}. No collage."`

**A2 ★ — Réparer le fallback segment (D3).**
Faire passer `media_agent.py:927` et `:1000` par le **même chemin que les beats** :
`synthesize_flux_subject(beat.prompt|narration)` + `build_visual_prompt(visual_type, …, use_prompt_as_is=True)`.
Au minimum, transmettre le `visual_type` du premier beat du segment et utiliser `beat.prompt`
au lieu de `theme — title — keywords`.

**A3 — Negative prompt généralisé (D7).**
Étendre `flux_negative_prompt_for_visual_type` : pour les photos, ajouter
`"blurry, low quality, deformed, extra fingers, watermark, text, oversaturated, jpeg artifacts"`
(rester léger : Flux dépend peu des négatifs).

**A4 — Passer les schémas/infographies à Flux.2 (D9).**
Router `is_diagram_visual_type` vers `flux_2_dev` (meilleure typographie/structure) tout en
gardant le rendu texte en overlay. Garder `flux_pro`/`ultra` pour le photoréalisme.

### B. Cohérence esthétique — **nouvel agent** (fort impact, effort moyen)

**B1 ★ — `art_director_agent` (style bible par vidéo) (D2).**
Nouvel agent placé **après `scenario_agent`, avant `beat_planner_agent`**. Produit un
*style block* unique pour toute la vidéo, dérivé du `creative_brief` / brand kit
(`channel_brand.py`) : palette, registre lumineux, type de rendu (photoréaliste / illustré),
objectif dominant, époque/grain.
- Injecté **mot pour mot** (phrasé identique) dans chaque `beat.prompt` (via beat_planner et
  le fallback média) → réduit la dérive de style.
- Stocké dans `Scenario.config` ou `Project.config` pour réutilisation (shorts dérivés).
- Effort : 1 agent court + 1 champ de contexte propagé. Faible risque.

### C. Boucle qualité — fiabiliser le critique (fort impact)

**C1 ★ — Vision images dans le critique (D4).**
Aujourd'hui la qualité visuelle dépend de `video_analyst_agent` (clé Gemini optionnelle).
Ajouter une **passe vision sur les images sélectionnées** (batch des `MediaAsset.local_path`)
avant le critique, ou rendre l'analyse Gemini quasi-obligatoire pour la note `visual_quality`.
Si pas de vision disponible, **plafonner** la note `visual_quality` (ne pas inventer un 18/20).

**C2 — Découper le critique (D6).**
Séparer `critic_agent` en deux responsabilités :
- **Scoring** (note les 6 dimensions, pur jugement) ;
- **Routing** (décide `start_from` / `requested_changes`).
Le routing est déjà en partie codé en dur (`_apply_routing_overrides`) → déplacer toute la
logique de reprise hors du prompt LLM, ne laisser au LLM que la notation + commentaires.
Prompt plus court = notes plus stables.

### D. Décomposition des prompts trop gros (effort moyen)

**D1 ★ — Sortir titre/description/SEO de `scenario_agent` (D5).**
Créer un **`metadata_agent`** (ou étendre un agent existant) qui produit titre YouTube,
description SEO, tags, chapitres — **après** validation du scénario (donc sur contenu figé).
`scenario_agent` se concentre alors sur structure + narration + delivery_style + keywords.
Bénéfice : chaque prompt fait une seule chose → meilleure qualité + métadonnées optimisées CTR.

**D2 — Externaliser les blocs « règles » répétés.**
Les règles voix/delivery_style et visual_beats sont dupliquées entre long/short
(`scenario_agent.py`) ; déjà partiellement factorisé (`visual_beats_prompt.py`). Continuer à
extraire pour alléger le prompt principal et faciliter la maintenance.

### E. Nouveaux agents à fort ROI YouTube

**E1 ★ — `thumbnail_agent` (D8).**
Aucun agent ne génère de miniature. C'est le **premier levier de CTR** sur YouTube.
Générer 1-3 concepts de miniature (visage/émotion, gros texte court, contraste fort) via
Flux.2 (bon en typographie) à partir du hook + titre, puis sélection par vision.

**E2 — `metadata_agent`** (cf. D1) — titre/desc/tags/chapitres/SEO.

**E3 (optionnel) — `b_roll_motion_agent`.**
Pour les beats clés, convertir l'image en court clip animé (image-to-video, déjà amorcé via
Runway dans `media_agent`) afin de réduire l'effet diaporama. Mesurer le coût.

---

## 5. Synthèse priorisée (ordre de mise en œuvre conseillé)

1. **A1 + A2** — prompts image riches + réparer le fallback segment *(impact immédiat, faible effort)*.
2. **B1** — `art_director_agent` / style bible *(cohérence esthétique, le plus visible)*.
3. **C1** — vision images dans le critique *(rend la boucle qualité réelle)*.
4. **D1 / E2** — sortir les métadonnées de `scenario_agent` + `metadata_agent`.
5. **E1** — `thumbnail_agent` *(CTR)*.
6. **A3, A4, C2, D2, E3** — raffinements.

---

## 6. Notes d'implémentation

- Tout nouvel agent étend `BaseAgent` (`agent/core/base_agent.py`) : `start_run/end_run/fail_run`,
  injection du learning context, modèle résolu via `data/agent_config.json → llm.agent_models`.
- L'insérer dans `AGENT_ORDER` **et** `_run_main_loop` / `_STEP_TO_LOOP_IDX`
  (`orchestrator.py:53,277`) + gérer la reprise (`pipeline_restart.py`).
- Le style block (B1) doit aussi être propagé aux **shorts dérivés**
  (`_run_native_shorts_pipeline`) pour rester cohérent.
- Après modif de code : `graphify update .` (cf. CLAUDE.md). Tests : `pytest`.
- Budgets IA : `ai_image_budget.py` / `runway_budget.py` — vérifier les plafonds avant
  d'augmenter le recours à Flux.2 ou à l'image-to-video.

---

## 7. Statut de réalisation

| Item | Statut | Fichiers principaux |
|------|--------|---------------------|
| A1 — prompts image enrichis (sujet en tête + cinématographie) + cap 200→480 | ✅ Fait | `prompt_builder.py`, `prompt_synthesizer.py` |
| A2 — fallback segment via synthèse + visual_type | ✅ Fait | `media_agent.py`, `segment_beats_media.py` |
| A3 — negative prompt photo généralisé | ✅ Fait | `flux_negative_prompt.py` |
| A4 — schémas routés vers Flux.2 (phase payante) | ✅ Fait | `media_agent.py` |
| B1 — `art_director_agent` (style block injecté partout) | ✅ Fait | `art_director_agent.py`, `orchestrator.py`, `base.py`, providers |
| C1 — vision/scoring média dans le critique + plafond sans vision | ✅ Fait | `critic_agent.py` |
| C2 — routage du critique recalculé en code (prompt allégé) | ✅ Fait | `critic_agent.py` |
| D1/E2 — `metadata_agent` (titre/desc SEO/tags/chapitres) | ✅ Fait | `metadata_agent.py`, `orchestrator.py`, `distribution_agent.py` |
| E1 — `thumbnail_agent` (concepts miniature Flux.2) | ✅ Fait | `thumbnail_agent.py`, `orchestrator.py` |
| D2 — externalisation bloc règles (mood) | ✅ Fait (partiel) | `scenario_agent.py` |

**Tests** : 329 passés (`pytest`). Nouveaux tests : `test_art_director_agent.py`,
`test_metadata_agent.py` ; `test_prompt_synthesizer.py` mis à jour.

**À faire (hors périmètre de cette session)**
- Régénérer le graphe : `graphify update .` (CLI absent du shell courant).
- E3 (`b_roll_motion_agent`) : non implémenté (optionnel, coût à mesurer).
- Sélection-par-vision des miniatures : `thumbnail_agent` génère 2 concepts et
  marque le premier comme primaire ; le classement Gemini reste à brancher.
- Brancher la miniature primaire sur l'upload YouTube (`set_thumbnail`).
- D2 : seul le bloc `mood` est externalisé ; les blocs voix/delivery_style restent
  inline (refactor à faible valeur, risque de régression sur un prompt très testé).
- Migration éventuelle pour exposer `youtube_metadata` / `thumbnail` hors de `Project.config`.
