# Analyse — Effets, appuis-texte & monotonie des vidéos longues

> Diagnostic du pipeline de montage (effets, incrustations texte, enchaînement des agents)
> et risque de vidéos monotones. Fondé sur le code actuel et la critique IA du projet
> « L'histoire de la tour Eiffel » (itération 1, score 42/100).

## 1. Pourquoi aucun effet / appui-texte n'apparaît

Les capacités **existent** dans l'éditeur (`agent/skills/video/filter_graph_builder.py`) :
mouvement Ken Burns, transitions xfade, et deux modes d'incrustation
(`drawtext` pour le texte, `svg_overlay` pour les diagrammes). Mais elles ne sont
**jamais alimentées** pour des plans-photo normaux, à cause de deux verrous :

**Verrou A — l'overlay texte est lié au `visual_type`, pas au texte.**
Dans `agent/skills/video/montage_decisions.py:86`, `resolve_overlay_mode()` ne renvoie
`"drawtext"` que si le `visual_type` est une carte-texte (`quote_card`,
`statistic_highlight`, `headline_overlay`, `text_card`, `lower_third`). Or le prompt du
beat_planner pousse explicitement vers des **photos réelles**
(« PERTINENCE AVANT VARIÉTÉ ») et décourage ces types. Résultat : `on_screen_text`
peut bien exister, il ne sera jamais brûlé sur une `documentary_photo`.

**Verrou B — `on_screen_text` n'est jamais rempli.**
Le template du beat_planner (`agent/core/beat_planner_prompt.py:34`) initialise
`on_screen_text: ""` et aucune règle ne demande de le peupler. Donc même le déclencheur
n'a pas de matière.

### Solution (appuis-texte type « vidéo histoire »)
1. **Découpler l'overlay du type** : dans `resolve_overlay_mode()`, renvoyer `"drawtext"`
   dès qu'`on_screen_text` est non vide, quel que soit le `visual_type`
   (passer le texte en argument). ~1 ligne de logique.
2. **Faire produire `on_screen_text` par le beat_planner** (ou l'ArtDirector) : texte
   court et percutant sur les beats-clés — une date (« 1889 »), un chiffre
   (« 18 038 pièces »), un nom, un mot du hook — avec une **cadence** (~1 beat sur 3,
   pas systématique, sinon ça sature).
3. **Animer l'incrustation** : `_build_drawtext_filter` existe déjà ; ajouter un fondu
   d'entrée / position basse type lower-third pour le côté « pro ».

## 2. Mouvement uniforme = 2ᵉ source de monotonie

`resolve_motion_style()` (`agent/skills/video/montage_decisions.py:67`) renvoie
**`zoom_in` pour quasiment toutes les photos** → tous les plans zooment dans le même sens,
effet hypnotique répétitif. Le `motion_hint` par beat existe mais n'est jamais peuplé.

### Solution
Alterner le mouvement (`zoom_in` / `zoom_out` / `pan_left` / `pan_right`) — soit en
alternance déterministe sur l'index du beat, soit via un `motion_hint` posé par
l'ArtDirector. Coût nul (Ken Burns est déjà là), gain de dynamisme immédiat.

## 3. L'enchaînement des agents est-il adapté aux vidéos longues ?

Oui, **la séquence est riche et bien pensée** (bien plus que ce que dit le CLAUDE.md) :

```
Research → Outline → Scenario → FactChecker → HookOptimizer
   → Narrator → ArtDirector → BeatPlanner → DiagramSpecialist
   → Media → MontagePlanner → Editor → Subtitle → Critic (boucle) → Revision
```

Le problème **n'est pas l'ordre** mais deux choses :
- **Les décisions créatives par beat sont templatées/uniformes** (mouvement constant,
  pas d'appui-texte) — c'est ce qui crée la monotonie, pas le séquencement.
- **Le Critic est global et grossier sur une longue timeline** : un seul score pour
  ~50 beats, max 3 itérations, et chaque `iterate` relance depuis le narrator (coûteux).
  Il détecte « c'est monotone » (cf. critique à 42) mais ne peut pas cibler quels beats
  corriger. Pour du long, un critic capable de pointer des **plages temporelles** serait
  plus efficace — chantier secondaire.

## 4. Verdict sur le risque de monotonie

Avec le système actuel, **oui, risque réel de vidéos plates** — c'est exactement ce que la
critique IA à 42 disait (visuel 4/20, rythme 6/20). Les causes cumulées :

| # | Cause | Statut |
|---|-------|--------|
| 1 | Plans trop longs (segments 22/56/68 s, cap beats fixe à 8) | **Partiellement réglé** — cap de beats dynamique implémenté (`dynamic_max_beats`) |
| 2 | Mouvement toujours identique (`zoom_in`) | **À corriger** — alternance Ken Burns |
| 3 | Aucun appui-texte | **À corriger** — verrous A + B |
| 4 | Voix monotone (DragonHD sans `express-as`) | Limite connue ; alias vocab `delivery_style` corrigé, mais styles inopérants sur voix DragonHD |

## 5. Priorités d'implémentation

Les deux gains les plus rentables et peu risqués :

1. **Alternance du mouvement Ken Burns** (le plus simple, gain immédiat) — modif dans
   `montage_decisions.py`.
2. **Appuis-texte sur photos** — découplage overlay (`resolve_overlay_mode`) + génération
   de `on_screen_text` par le beat_planner avec cadence.

Les deux sont des modifs ciblées dans `montage_decisions.py` + le prompt beat_planner,
testables unitairement.

---

### Annexe — Correctifs déjà appliqués (contexte)
- **Cap de beats dynamique** : `agent/skills/scenario/beat_timeline_split.py::dynamic_max_beats`
  branché dans `beat_planner_agent.py` — un segment de 68 s n'est plus tronqué à 8 plans.
- **Alignement vocabulaire `delivery_style`** : `ssml_builder.py` tolère désormais les
  déviations (`documentary` → `documentary-narration`, `medium` → `normal`) ; prompt
  ScenarioAgent durci sur `pace` (slow/normal/fast uniquement).
