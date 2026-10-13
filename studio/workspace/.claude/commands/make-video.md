---
description: Produit un Short 9:16 de bout en bout à partir de brief.json (scénariste → voix → monteur → miniaturiste → critique, boucle d'itération)
---

Tu es le **producteur** : tu orchestres 5 sous-agents via l'outil Agent et tu ne fais pas leur travail à leur place.
Lis d'abord `CLAUDE.md` et `brief.json`. Le run dir courant contient tout.

## Itération 1
1. **scenariste** → `scenario.json`. Passe-lui le brief (thème, niche, angle, durée cible, ton, content_plan).
2. **voix** → `narration.txt`, `voice.wav`, `words.json`, `voice.json`.
3. **monteur** → médias, `timeline.json`, `renders/v1.mp4`.
4. **miniaturiste** → `thumbnails/v1_9x16.png`, `thumbnails/v1_16x9.png`, `thumbnail.json`.
5. **critique** → `critique_1.json` (indique-lui le numéro d'itération et la vidéo `renders/v1.mp4`).

Lance-les **dans cet ordre, un par un** (chaque étape dépend de la précédente). Dans chaque prompt de sous-agent,
indique explicitement le numéro d'itération N et les fichiers attendus.

## Boucle
Après `critique_N.json` :
- `decision == "approve"` **ou** `score >= brief.min_score` → terminé.
- sinon, si N < `brief.max_iterations` : itération N+1. Relance **seulement** les rôles cités dans `changes`,
  en leur transmettant mot pour mot leurs instructions, dans l'ordre du pipeline, avec les cascades :
  - scénariste modifié → voix et monteur obligatoirement relancés (nouveau texte, nouveaux timings) ;
  - voix modifiée → monteur relancé (re-caler la timeline sur la nouvelle durée) ;
  - monteur relancé → nouveau rendu `renders/v<N+1>.mp4` ;
  - la miniature n'est refaite que si `miniaturiste` est cité (sinon `thumbnail.json` reste valable).
  Puis critique sur `renders/v<N+1>.mp4` → `critique_<N+1>.json`.
- sinon (plafond atteint) → terminé avec `max_iterations`.

## Fin
Choisis la meilleure version (score le plus haut ; à égalité la plus récente) et écris `result.json` :
`{"status": "approved" | "max_iterations" | "failed", "iterations": N, "final_video": "renders/vK.mp4", "notes": "…"}`
puis valide-le : `python -m studio.tools validate --kind result --path result.json`.

Si une étape échoue deux fois de suite pour la même raison, écris `result.json` avec `status: "failed"` et une
explication dans `notes`, puis arrête-toi. Termine par un résumé de 3 lignes (titre, score final, fichier).
