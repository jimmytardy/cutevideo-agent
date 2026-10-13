# Vidéos de référence — leviers de viralité → règles concrètes

Analyse du 2026-10-13 avec `python -m studio.tools analyze` (repli Claude : planches de frames, Whisper,
mesures audio ; Gemini indisponible, clé en 401). Vidéos téléchargées dans `~/.cache/cutevideo/references/`
(jamais dans le repo). On n'en copie **aucun contenu** : seulement des mécanismes.

| Vidéo | Vues | Durée | Coupes détectées | Débit | Pauses max | Loudness | Voix / fond | Voix |
|---|---|---|---|---|---|---|---|---|
| Alfred — vélo & volcan | 108 k | 118 s | 15 (+ apparitions toutes les ~2 s) | 3,14 mots/s | 0,8 s | -13,1 LUFS | +16,5 dB | grave (126 Hz), ±4,5 demi-tons |
| Alfred — tour de Pise | 1,4 M | 116 s | 22 | 3,44 mots/s | 0,86 s | -13,1 | +14,4 dB | 127 Hz, ±4,4 |
| Alfred — sous-marin / harengs | 128 k | 117 s | 14 | 3,56 mots/s | 0,88 s | -13,3 | +15,5 dB | 122 Hz, ±4,3 |
| Archibald — nucléaire moins dangereux | 723 k | 118 s | 5 (scène continue) | 3,0 mots/s | 1,86 s (effet) | -15,0 | +14,2 dB | 109 Hz, ±6,7 |
| Archibald — déchets dans un cube | 518 k | 118 s | — | — | — | — | — | — |

Notre baseline (« Lune », 85/100) en face : **2,38 mots/s**, pauses de **0,9 s après chaque phrase** (voix edge
Denise), musique quasi inaudible (fond à -49 dBFS, **+33 dB** sous la voix), -16,2 LUFS, sous-titres sous la
ligne d'interface TikTok, plans de banque d'images sombres et vides.

## Ce qui fait leur viralité (à reproduire systématiquement)

1. **La chute dès la 1re phrase, sous forme de paradoxe.** « Le vélo a été inventé à cause d'un volcan »,
   « La tour de Pise aurait déjà dû tomber. Pour la sauver, on a creusé sous le côté qui ne penche pas »,
   « Il existe une énergie 800 fois plus meurtrière que le nucléaire ». Deux choses sans rapport apparent, ou une
   affirmation contre-intuitive, chiffrée. → **Règle scénariste** : le hook (≤ 2 s, ≤ 15 mots) énonce le fait le
   plus surprenant de la vidéo ; jamais une question générale (« Saviez-vous… ? »).
2. **Phrase 2 = objection anticipée puis « Sauf que… ».** « Je sais, un volcan en Indonésie, un vélo en Allemagne,
   aucun rapport. Sauf qu'en avril 1815… », « Vous pensez sûrement… Sauf que… ». → **Règle** : beat 2 nomme ce que
   le spectateur croit, puis le contredit.
3. **Récit concret, daté, chiffré.** Dates (« Octobre 1981 »), lieux, personnages, chiffres ronds immédiatement
   mis à l'échelle (« Depuis Paris, c'est comme entendre une explosion à Moscou », « Imaginons une ville de
   150 000 habitants »). → **Règle** : chaque chiffre est traduit en comparaison du quotidien.
4. **Relances toutes les 15-25 % de la durée.** « Mais attendez, parce que le pire arrive… », « Et le vélo n'est
   même pas le plus fou », « Mon passage préféré », « Le pire, … ». → **Règle** : au moins une relance explicite
   au tiers et une aux deux tiers ; une micro-relance (question, chiffre, retournement) toutes les 5-8 s.
5. **Interaction.** « À votre avis ? … je brise le suspense », révélation différée « 19·· → 1934 ».
   → **Règle** : une question au spectateur juste avant le chiffre clé.
6. **Fin en boucle.** Les 3 vidéos Alfred finissent par « Alors la prochaine fois que vous [geste quotidien],
   dites-vous que… » : la phrase inachevée se termine… par la 1re phrase de la vidéo (revisionnage). Archibald
   finit sur un cliffhanger (« c'est le sujet de la prochaine vidéo, et vous allez voir que… »).
   → **Règle** : dernier beat = « Alors la prochaine fois que… » qui **reboucle grammaticalement sur le hook**,
   et la dernière image rappelle la première.
7. **Full animation, une idée visuelle par phrase.** Chaque phrase a son pictogramme littéral (soldat, canon dans
   une bulle de pensée, calendrier « 1815 », carte avec trajet pointillé et distance, jauge, règle « 3 m »).
   Un nouvel élément apparaît **toutes les ~2 s** même sans coupe (la scène se construit).
8. **Un mot-clé titre par plan**, en capitales en haut (« TAMBORA », « PROBLÈME », « 150 000 habitants ») +
   petite étiquette encadrée (« INDONÉSIE », « SUD : PLUS MOU »). Les vidéos n'ont **pas** de sous-titres
   karaoké : ce sont les mots-clés qui portent le texte.
9. **Enjeu visible en permanence** : jauge « CHUTE » en haut à gauche pendant toute la vidéo de Pise
   (boucle ouverte visuelle) ; objet-héros récurrent (la tour, le baron sur sa draisienne).
10. **Tableaux d'unités** : 25 crânes = 25 morts, « 1 mort tous les 33 ans » — le chiffre devient visible.
11. **Durée ~2 min** pour ces comptes ; nos Shorts visent 40-60 s : on garde la structure (hook paradoxal →
    objection → récit → relance → chute en boucle) en la compressant.

## Leur exécution (à surpasser)

- **Voix** : voix masculine grave correcte mais légèrement synthétique ; mixage voix/musique bon (+14-16 dB).
  → Nous : voix edge « Multilingual » (Rémy) plus expressive, débit 2,9-3,3 mots/s, pauses ≤ 0,4 s, musique
  calée à -17 dB sous la voix avec ducking doux, -14 LUFS, bruitages synthétiques sur les apparitions.
- **Finition visuelle** : pixel-art sombre, petits éléments, beaucoup de vide, textes minuscules (étiquettes
  ~30 px), bas d'écran inutilisé. → Nous : kit vectoriel `anim/lib/studio.js` (icônes Noto détaillées, Poppins,
  halo, vignettage, ombres), éléments plus grands, textes ≥ 48 px, caméra (zooms), secousses, flashs.
- **Accessibilité** : pas de sous-titres → nous gardons des sous-titres (mot actif surligné, mots-clés en couleur)
  placés **au-dessus** de l'interface TikTok (centre y ≈ 1290 px).

## Où ces règles sont appliquées
- `studio/workspace/.claude/agents/scenariste.md` (hook paradoxal, objection, relances, question, fin en boucle) ;
- `studio/workspace/.claude/agents/monteur.md` + `CLAUDE.md` (full animation par défaut avec le kit, un élément
  toutes les ~2 s, mot-clé titre, sfx, sous-titres) ;
- `studio/workspace/.claude/agents/critique.md` (grille virale, `analyze`) ; `studio/analyze.py` (`GRID`, alertes).
