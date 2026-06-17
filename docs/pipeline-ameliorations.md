# Analyse du pipeline de production vidéo & pistes d'amélioration

> Analyse honnête, ancrée sur le code existant et sur les bonnes pratiques de prompting IA / production studio.
> Objectif : rendre la vidéo finale la plus qualitative possible (ajout d'agents, amélioration de prompts,
> découpage de responsabilités, réordonnancement).

---

## 1. La chaîne actuelle, mappée sur les étapes d'un studio

Le pipeline réel est défini dans `agent/core/orchestrator.py:53` (`AGENT_ORDER`). Il est bien plus riche
que la doc CLAUDE.md. Voici sa superposition au workflow d'un vrai studio
(Développement → Pré-prod → Production → Post → Contrôle qualité → Distribution) :

| Étape studio | Tes agents | État |
|---|---|---|
| **Développement** (idée, recherche, traitement, script) | `content_planner` → `research` → `scenario` → `fact_checker` → `hook_optimizer` | ✅ Très solide |
| **Pré-production** (direction artistique, storyboard, shot list) | `art_director` → `beat_planner` → `diagram_specialist` | ⚠️ Bon mais storyboard *après* la voix |
| **Production** (tournage / B-roll) | `media_agent` (sourcing réel + génération IA) | ✅ Avec scoring de pertinence par beat |
| **Post** (montage, étalonnage, sound design, mix, sous-titres) | `montage_planner` → `editor` → `subtitle` | ⚠️ Pas d'étape son ni d'étalonnage unifié |
| **Contrôle qualité** (visionnage, notes) | `video_analyst` (vision Gemini) → `critic` (boucle ≤3) | ✅ Excellent (routage déterministe par déficit) |
| **Distribution** | `metadata` → `thumbnail` → `clipper` → `short_editor` → `distribution` | ✅ Complet |

### Ce qui est déjà très bien fait (à ne PAS casser)

- `prompt_builder.build_visual_prompt` (`agent/skills/media_sources/ai/prompt_builder.py:615`) mène **par le sujet**
  puis ajoute lumière/objectif par famille → exactement la bonne pratique FLUX (front-load du sujet).
- `prompt_synthesizer` (`agent/skills/media_sources/ai/prompt_synthesizer.py:30`) décrit la scène **en couches**
  (sujet → environnement → arrière-plan) → conforme à la reco officielle Black Forest Labs.
- `art_director` fige un `style_block` réutilisé partout → bonne réponse au patchwork de style.
- `relevance_scorer` note chaque image **par beat** (pas par segment) via vision Gemini
  (`agent/skills/media_sources/relevance_scorer.py:121`, `BEAT_INTENTION_TEMPLATE`).
- `critic` plafonne la note visuelle sans vision réelle (`agent/agents/critic_agent.py:283`)
  et recalcule le point de reprise sur la dimension la plus déficitaire (`_derive_start_from`, ligne 508).

**Conclusion : le squelette est bon. Ci-dessous des optimisations, pas une refonte.**

---

## 2. Problèmes concrets + solutions (classés par impact/effort)

### 🔴 P1 — Les prompts image gaspillent leur budget sur des tokens inutiles

**Constat** : `build_visual_prompt` (`agent/skills/media_sources/ai/prompt_builder.py:658-664`) ajoute à la fin
de CHAQUE prompt :
- `"Theme: {category}. Tone: {tone}"` → ex. `Theme: documentaire. Tone: inspirant`
- `"High quality, sharp focus, professional detail"`

**Pourquoi c'est un problème** : FLUX 2 (encodeur Mistral) **n'a pas besoin des tags de qualité** — il sort net
par défaut, et les guides disent explicitement de récupérer ces tokens pour décrire la scène.
`Theme/Tone` sont des concepts **abstraits non rendus** : FLUX ne sait pas peindre « inspirant », ça dilue
l'attention.

**Action** :
- Supprimer le tag qualité pour les photos (le garder éventuellement pour les diagrammes où « clean » aide).
- Supprimer la ligne `Theme:/Tone:` — le `style_block` (déjà concret : palette, lumière) la remplace.
- Réinjecter les ~10-15 mots libérés dans la description de scène (FLUX récompense 30-80 mots de scène réelle).

**Effort : 1 fonction. Impact : élevé et immédiat.**

---

### 🔴 P2 — Le prompt du `scenario_agent` fait 7 métiers à la fois (le vrai « prompt trop gros »)

**Constat** : `USER_PROMPT_LONG` (`agent/agents/scenario_agent.py:43-125`) demande en **un seul appel**
(cap 8192 tokens) : titre + description SEO + structure narrative + écriture de la narration (300+ mots/segment)
+ règles d'oralisation + `search_keywords` FR/EN + `source_hint` + `mood` + `delivery_style` (direction voix)
+ `strip_source_audio` + `needs_music` + `hook_type`.

C'est le maillon où la qualité plafonne : un LLM qui jongle entre « écrire une narration vivante » et « choisir
des noms de banques d'images » fait moins bien les deux. Un studio sépare le **traitement/séquencier** (structure)
de l'**écriture du script**.

**Action — découper en 2 passes** (amélioration la plus rentable) :
1. **`outline_agent`** (nouveau, appel court) : produit seulement l'architecture — titres de segments, arc
   tension→révélation→payoff, allocation des 3 faits surprenants du brief, hook, durées cibles, mood par segment.
   Validable/critiquable à bas coût avant d'engager l'écriture.
2. **`scenario_agent`** (recentré) : reçoit l'outline figé et n'écrit **que** `narration_text` + `delivery_style`
   segment par segment.

Bénéfice : appels focalisés, contrôle de l'outline avant de dépenser des tokens sur 8 narrations, régénération
d'une seule narration sans refaire toute la structure. Aligné sur la séparation studio « treatment → script ».

**Variante légère** (sans nouvel agent) : sortir au moins `search_keywords`/`source_hint` du prompt d'écriture
(les déduire après, à partir de la narration finale).

---

### 🟠 P3 — Aucune cohérence de sujet entre plans (patchwork sur les entités récurrentes)

**Constat** : le `style_block` harmonise l'**ambiance**, mais chaque beat est généré indépendamment. Si la vidéo
parle d'un personnage, d'un animal ou d'un lieu précis revenant sur 6 plans, chaque image le ré-invente →
visages/objets incohérents. C'est LE défaut classique des chaînes faceless IA.

**Action** : ajouter une **« bible de sujet »**. Au moment du `validation_brief` (déjà construit,
`agent/agents/scenario_agent.py:507`), identifier les entités récurrentes, générer **une image de référence par
entité**, puis pour les beats qui la montrent passer cette référence en `img2img`/reference à FLUX (ou réutiliser
le même `seed`). FLUX 2 supporte le conditionnement par image de référence. Impact fort sur le ressenti
« pro vs slideshow ».

---

### 🟠 P4 — Pas d'étape « son » alors que c'est une phase de post à part entière

**Constat** : `needs_music` est un simple booléen dans le scénario (`agent/agents/narrator_agent.py:26`). Aucun
agent ne pense la **musique comme un arc** (montée en tension, respiration à la conclusion), ni de SFX sur les
beats clés, ni de plan de ducking. En studio, le sound design est une étape majeure de la post.

**Action** : un `music_supervisor` léger entre `montage_planner` et `editor` qui, à partir des `mood` par
segment, choisit la/les pistes, planifie les transitions musicales (piste énergique sur le hook → bed calme sur
la conclusion) et marque d'éventuels SFX (whoosh sur transition, accent sur un beat « révélation »).
`agent/skills/audio/audio_mixer.py` existe déjà pour l'exécution ; il manque la **décision**.

---

### 🟡 P5 — Mélange footage réel + IA sans étalonnage final unifié

**Constat** : on mixe Pexels/Gallica/Wikimedia (réels) avec des images FLUX. Le `style_block` ne s'applique qu'à
la **génération** — le footage réel garde sa propre colorimétrie → ruptures de look. Un studio passe un
**étalonnage final** sur la timeline entière.

**Action** : pas besoin d'agent. Ajouter dans `agent/skills/video/filter_graph_builder.py` / `editor` un LUT/grade
léger appliqué à toute la timeline (courbe + balance dérivée du `style_block` : palette chaude → teinte ambrée).
Harmonise réel et IA. Faible effort, gain de cohérence visible.

---

### 🟡 P6 — Réglages de séquencement (petits, mais gratuits)

- **`art_director` peut tourner plus tôt et en parallèle** : il ne dépend que du thème/scénario, pas de la voix.
  Aujourd'hui coincé à `loop_start<=3` après le narrateur (`agent/core/orchestrator.py:413`). Le lancer juste
  après `scenario` (en parallèle de `narrator`) raccourcit le chemin critique sans changer le résultat.
- **`delivery_style` est généré dans le scénario mais seul le hook est ré-optimisé** (`hook_optimizer`). Si la
  voix sonne plate, le `critic` route vers `narrator_agent` (`voice_expressiveness < seuil`,
  `agent/agents/critic_agent.py:517`) mais on régénère la voix avec le **même** `delivery_style`. Faire passer ce
  retour par une mini-passe « direction voix » qui varie réellement pace/emotion/azure_style par segment avant de
  re-synthétiser.

---

## 3. Récapitulatif priorisé

| # | Action | Effort | Impact | Type |
|---|---|---|---|---|
| P1 | Retirer tags qualité + `Theme/Tone` des prompts FLUX | Très faible | 🔥 Élevé | Prompt |
| P2 | Scinder `scenario` en `outline` + écriture | Moyen | 🔥 Élevé | Nouvel agent / split |
| P3 | Bible de sujet (référence/seed pour entités récurrentes) | Moyen-élevé | 🔥 Élevé | Cohérence |
| P4 | `music_supervisor` (arc musical + SFX) | Moyen | Moyen-élevé | Nouvel agent |
| P5 | Étalonnage LUT final sur la timeline | Faible | Moyen | Post |
| P6 | `art_director` en parallèle + direction voix sur retour critic | Faible | Faible-moyen | Reorder |

**Si tu ne fais que deux choses** : P1 (gratuit, gain immédiat sur chaque image) et P2 (débloque le plafond de
qualité narrative). P3 est le suivant pour passer de « bon slideshow » à « vraie prod ».

---

## 4. Sources

Prompting image (FLUX) :
- Black Forest Labs — Prompting Guide FLUX.2 : https://docs.bfl.ml/guides/prompting_guide_flux2
- Apatero — FLUX 2 official guide : https://www.apatero.com/blog/flux-2-official-prompting-guide-black-forest-labs-2025
- Segmind — FLUX prompting guide : https://blog.segmind.com/flux-prompting-guide-image-creation/
- fal.ai — FLUX 2 prompt guide : https://fal.ai/learn/devs/flux-2-prompt-guide

Production vidéo (studio) :
- Ziflow — Video production workflow : https://www.ziflow.com/blog/video-production-workflow
- Adobe — Video production guide : https://www.adobe.com/creativecloud/video/discover/video-production.html
- SimonSays — Post-production workflow : https://www.simonsaysai.com/blog/video-post-production-workflow
- Soundstripe — 3 stages of production : https://www.soundstripe.com/blogs/three-stages-of-video-production
- Boords — Storyboard a documentary : https://boords.com/how-to-storyboard/documentary

---

## 5. Systèmes existants comparables — quoi en retenir

Recherche effectuée pour identifier des outils/systèmes agentiques fiables et réputés, et en tirer des
inspirations concrètes. On distingue 3 catégories : produits grand public, projets open-source directement
comparables, et recherche académique multi-agents (la plus proche de ton architecture).

### 5.1 Produits grand public (le « benchmark » de qualité perçue)

Ils ne sont pas agentiques au sens où tu l'es (peu de boucle critique interne), mais ils fixent la barre de
qualité et montrent ce que le marché attend.

| Outil | Positionnement | À en retenir pour ton pipeline |
|---|---|---|
| **InVideo AI** | Script→vidéo, intègre **Sora 2 + VEO 3.1** dans un seul abonnement | Tendance lourde : remplacer/compléter le stock par de la **vidéo générative** (clips animés), pas juste des images fixes. Ton `media_agent` est image-centré → c'est un axe d'évolution. |
| **Pictory** | Article/blog/script → vidéo, repurposing | Workflows « edit video using text » et « highlights » → l'édition pilotée par le texte. |
| **HeyGen / Synthesia** | Avatars présentateurs, 140+ langues | Voix/présentateur de très haute qualité. Confirme P4 (le son/voix est un différenciateur). |
| **ElevenLabs** | TTS / clonage voix, « gold standard » 2025-2026 | Tes voix passent par edge-tts/Azure/Gemini. ElevenLabs reste la référence d'expressivité → option premium pour le `narrator_agent`. |
| **Runway Gen-3 / Kling** | Clips génératifs, **Kling meilleur sur la cohérence des clips longs** | Renforce P3 (cohérence) : la cohérence inter-plans est LE critère de qualité reconnu du secteur. |

**Leçon générale du secteur** : « le succès tient à l'efficacité du pipeline et à la vitesse idée→vidéo de
qualité ». Ta force, c'est justement la boucle qualité — à pousser plutôt qu'à diluer.

### 5.2 Open-source directement comparables (même nature que ton projet)

- **ShortGPT** (open-source) : script → sourcing footage → voix → montage. Architecture en **étapes
  séquentielles** comme la tienne, mais **sans agent critique ni boucle d'itération**. → Ton `critic` +
  `video_analyst` est un avantage différenciant réel sur ShortGPT.
- **MoneyPrinterTurbo** (MIT, très populaire sur GitHub Trending) : sujet/mot-clé → script → search terms →
  clips stock → TTS → sous-titres → musique de fond → MP4. **Notable : il a une étape « musique de fond »
  native** alors que toi non (cf. P4) — confirme que le sound design comme étape dédiée est attendu.
  En revanche, pas de scoring de pertinence par plan : ton `relevance_scorer` par beat est plus avancé.

**Verdict** : ton système est **déjà plus mature** que ces deux références sur la qualité (recherche factuelle,
scoring média par beat, double QC vision+critic, boucle d'itération). Les seules choses qu'ils font et pas toi :
musique native (MoneyPrinterTurbo) et clips génératifs (les produits payants).

### 5.3 Recherche académique multi-agents (l'inspiration la plus pertinente)

Ces papiers 2024-2026 décrivent des pipelines multi-agents pour la vidéo qui **valident et raffinent ton
découpage par rôles**. À lire en priorité car ils répondent exactement à ta question « ajout d'agent / division
de responsabilité ».

- **AniMaker — Multi-Agent Animated Storytelling** (arXiv 2506.10540) : 4 agents = **Director** (crée le
  storyboard) → **Photography** (génère les clips) → **Reviewer** (évalue chaque clip, context-aware) →
  **Post-production** (assemble + voix-off). C'est *exactement* ton `art_director`/`beat_planner` →
  `media_agent` → `relevance_scorer`/`critic` → `editor`. **Inspiration concrète** : leur Reviewer évalue
  **clip par clip avec sélection MCTS** (génère plusieurs candidats, garde le meilleur). Tu pourrais générer
  N images par beat et garder la mieux notée par le `relevance_scorer` (tu as déjà le scoring, il manque le
  « best-of-N »).
- **Co-Director — Agentic Generative Video Storytelling** (arXiv 2604.24842) : un LLM orchestre le processus
  génératif multi-étapes — valide ton approche `orchestrator`.
- **Anim-Director** (SIGGRAPH Asia 2024) : un LMM joue le **réalisateur autonome** orchestrant toute la chaîne.
- **« The Script is All You Need »** (arXiv 2601.17737) : combine **métriques objectives + scoring automatique
  par un CriticAgent + évaluation humaine**. → Confirme ton `critic`, et suggère d'ajouter des **métriques
  objectives** (durée par plan, variété des `visual_type`, ratio statique) en plus du jugement LLM. Tu as déjà
  certaines de ces métriques (`max_static_shot_s`, scoring média) — les agréger en un score objectif qui
  alimente le critic fiabiliserait la note.
- **« Dissecting an Autonomous AI Filmmaking Pipeline »** (Medium, Josh English) : décrit un trio
  **AI Director of Photography (synthèse de prompt) + Critic Agent + Optimizer Agent**. → L'**Optimizer Agent**
  est ce qui te manque : aujourd'hui ton `critic` détecte et route, mais ne **réécrit pas** le prompt fautif ;
  un optimizer dédié qui prend le feedback critic + l'image ratée et régénère un meilleur prompt image fermerait
  la boucle (au lieu de relancer l'agent en amont à l'identique).

### 5.4 Inspirations concrètes à reprendre (synthèse)

| Source | Idée à reprendre | Se rattache à |
|---|---|---|
| AniMaker (Reviewer + MCTS) | **Best-of-N par beat** : générer plusieurs candidats image, garder le mieux noté | Étend ton `relevance_scorer` |
| « The Script is All You Need » | **Métriques objectives** agrégées en score, en plus du jugement LLM | Fiabilise ton `critic` |
| Filmmaking pipeline (Medium) | **Optimizer Agent** qui réécrit le prompt image fautif au lieu de tout relancer | Nouveau, comble P1/P3 |
| MoneyPrinterTurbo | **Musique comme étape native** | Confirme P4 (`music_supervisor`) |
| InVideo / Runway / Kling | **Clips génératifs + cohérence inter-plans** | Confirme P3, ouvre un axe vidéo générative |
| ElevenLabs / HeyGen | **Voix premium** comme différenciateur | Confirme P4 / option `narrator` premium |

**Conclusion honnête** : tu n'as pas à copier un outil — ton architecture est déjà au niveau (voire au-dessus)
des projets open-source comparables et structurée comme les pipelines académiques de référence. Les 3 ajouts les
plus validés par l'état de l'art sont : (1) **best-of-N par beat**, (2) un **Optimizer Agent** qui ferme la
boucle de raffinement des prompts, (3) le **sound design comme étape dédiée**.

### 5.5 Sources (section 5)

Produits & open-source :
- HeyGen — Best AI video generator faceless YouTube 2026 : https://www.heygen.com/blog/best-ai-video-generator-faceless-youtube
- The Data Scientist — AI Video Generators 2026 buyer's guide : https://thedatascientist.com/ai-video-generators-in-2026-a-hands-on-buyers-guide/
- virvid.ai — Faceless YouTube automation stack 2026 : https://virvid.ai/blog/ai-faceless-youtube-automation-stack-2026
- Cybernews — 16 best AI video generation tools 2026 : https://cybernews.com/ai-tools/best-ai-video-generators/
- Synthesia — 18 best AI video generators 2026 : https://www.synthesia.io/post/best-ai-video-generators
- ShortGPT (AI Agent Store) : https://aiagentstore.ai/ai-agent/shortgpt
- MoneyPrinterTurbo (deep dive) : https://agentpedia.codes/blog/moneyprinterturbo-ai-short-video-generator-guide

Recherche académique :
- AniMaker — Multi-Agent Animated Storytelling : https://arxiv.org/pdf/2506.10540
- Co-Director — Agentic Generative Video Storytelling : https://arxiv.org/html/2604.24842v1
- The Script is All You Need : https://arxiv.org/pdf/2601.17737
- Anim-Director (SIGGRAPH Asia 2024) : https://dl.acm.org/doi/10.1145/3680528.3687688
- Dissecting an Autonomous AI Filmmaking Pipeline (Medium) : https://medium.com/@jengas/dissecting-an-autonomous-ai-filmmaking-pipeline-0192b7a69636
