# Motion design 3D (`brief.json.motion3d` = true)

Réservé aux chaînes en style `motion3d` ou `auto` dont l'abonnement autorise la 3D. Sinon `animate --3d` et les
modèles 3D sont refusés : reste sur le kit 2D.

## Quand utiliser la 3D
- **Plans clés seulement** : l'accroche, le chiffre choc, la révélation, une démo d'appli. 2 à 4 plans par vidéo, les
  autres avec le kit 2D (`studio.js`), **même `theme` et même `accent`** pour que la vidéo reste une seule charte.
- **Budget** : 7 s maximum par plan 3D, 20 s de 3D par vidéo (l'outil refuse au-delà ; refaire un plan sous le même
  `--name` le remplace). Un plan 3D coûte ~3,5 s de rendu par image : 5 s de plan ≈ 9 min de rendu, contre
  quelques secondes en 2D.
- La 3D sert un propos : un objet qui a du volume (téléphone, produit, pièce, bâtiment), un chiffre qu'on veut
  monumental, une profondeur (avant / arrière-plan). Un schéma, une carte, une liste restent en 2D.

## Méthode (obligatoire : un rendu complet coûte cher)
1. Écris la scène (modèle 3D ou script `anim/<NN>_<nom>.html`).
2. **Aperçu** : `animate-template … --preview` ou `animate --3d --script … --preview` → 6 images en planche
   `review/anim_<nom>/preview.png` en ~1 min, plus `estimated_render_min`. **Read sur l'aperçu**, corrige
   cadrage, tailles, `zone_warnings`.
3. **Un seul rendu complet** (sans `--preview`) quand l'aperçu est bon. Appelle Bash avec un `timeout` de
   1800000 ms pour ce rendu.
4. En révision, ne refais un plan 3D que si la critique le cite : sinon garde `media/anim_<nom>.mp4`.

Si l'outil répond « rendu trop lent », allège dans cet ordre : `quality: 0.8` (le titre SVG reste net), `dof: 0`,
`floor: "matte"`, puis raccourcis le plan.

## Modèles 3D (`animate-template`, options communes `theme`, `accent`, `floor`)
- `phone3d` `{"title", "sub", "screen": {"kind": "ring", "header": "Objectif", "value": 0.84, "items": [{"text": "Marche", "value": "32 min"}]}, "caption": "30 min de marche"}`
  — téléphone dont l'écran s'anime, orbite lente, anneau lumineux. `kind` : `ring` (anneau de progression, `value`
  0-1, `text` optionnel), `counter` (`to`, `suffix`), `list` (`items` [{text, value}]), `bars` (`items` [nombres]).
- `number3d` `{"title", "sub", "to": 384400, "suffix": " km", "label": "la distance Terre-Lune"}` — chiffre extrudé
  qui compte ; avec `"before": {"value": 14, "label": "avant"}, "after_label": "après", "delta": "+64 %"` :
  comparaison avant → après.

## Kit `lib/studio3d.js` (scripts `animate --3d`)
```html
<!doctype html><html><head><meta charset="utf-8"></head><body>
<script src="lib/three.bundle.min.js"></script>
<script src="lib/fonts/poppins3d.typeface.js"></script>   <!-- seulement pour number() -->
<script src="lib/studio.js"></script>
<script src="lib/studio3d.js"></script>
<script>
const s = Studio3D.scene({theme: "night", accent: "#FF5A1F", floor: "gloss", dof: 1, bloom: 0.3});
const ui = Studio.scene({theme: "night", accent: "#FF5A1F", transparent: true});   // titres 2D nets par-dessus
ui.title("12 000 PAS", {sub: "objectif du jour"});
const tel = s.phone({enter: "none", idle: "float", screen: (c, t, k) => {
  k.bg(c); k.text(c, "Objectif", 0.08, 0.1, {size: 0.075});
  k.ring(c, 0.5, 0.36, 0.3, Math.min(1, t / 2) * 0.84, "84 %");
}});
s.ring({r: 1.15});
s.card({title: "Cette semaine", value: "70 000", sub: "pas", x: 1.1, y: 1.4, z: 0.6, ry: -0.35, at: 1.2, enter: "slide"});
s.orbit({at: 0, dur: 4, from: -24, to: 16});
</script></body></html>
```
- **Monde en mètres** : sol en y = 0, sujet en x = 0 ; caméra par défaut à 9,5 m visant (0, 0.8, 0), point visé à
  y ≈ 790 px (sous le titre). Largeur utile ≈ ±1 m au premier plan ; un objet de ~1,6 m de haut remplit la zone.
- `Studio3D.scene` : `theme`, `accent`, `env` (`studio`, `night`, `sunset`), `floor` (`gloss` reflet doux, `mirror`
  reflet net, `grid`, `matte`, `none`), `dof` (profondeur de champ, 1 = normale), `bloom` (halo, 0.3), `quality`
  (0.4-1), `camera` ({pos, target, fov} de départ), `exposure`, `vignette`.
- Objets (options communes `at`, `dur`, `enter` none|pop|rise|drop|spin|slide|flip|fade, `out` + `exit`
  fade|pop|sink, `idle` float|spin|sway|pulse, `x`, `y`, `z`, `rx`, `ry`, `rz` en radians, `scale`, `bleed`) :
  `phone({screen: (ctx, t, k) => …, w})` (écran redessiné à chaque image ; `k` = outils : `bg`, `text`, `ring`,
  `rows`, `bars`, `button`, coordonnées 0-1 de l'écran), `card({title, value, sub, w, h, face})`,
  `number({to, from, prefix, suffix, decimals, size, maxW, color, text})` (chiffre extrudé, `maxW` en mètres),
  `box({label, sub, w, h, d, color})`, `ring({r, tube, draw})`, `glowLine([[x, y, z], …], {draw})`,
  `iconPlate(nom, {size})` (icône du kit sur une pastille), `columns([{label, value, valueText}])` (colonnes qui
  montent), `label(texte, {size, color})` (texte face caméra), `particles({count})`, `custom((T, s) => objet3D, {update})`.
- Mouvement : `s.track(objet, [{t: 0, x: 0, ry: 0}, {t: 2, x: 0.8, ry: 0.6}])` (images clés, temps absolu).
- Caméra : `s.orbit({at, dur, from, to, radius, height, toRadius, target})` (angles en degrés),
  `s.push({at, dur, from, to, target})` (s'approche), `s.camera({at, dur, pos, target, fov})`, `s.shake({at})`.
  Toujours un mouvement de caméra lent et continu : c'est lui qui donne le « cinéma ».
- Matières : `s.gloss(couleur)`, `s.metal(couleur)`, `s.glow(couleur, intensité)` pour `custom`.
- `zone_warnings` : boîtes 3D projetées à l'écran, mêmes zones que le kit 2D (y 170-1180, x 60-960).

## Direction artistique (niveau « motion design de marque »)
- Fond sombre et sol brillant, **une seule couleur d'accent** (anneaux, chiffres, interface) ; tout le reste neutre.
- Le sujet est **déjà cadré à t = 0** (`enter: "none"`), la caméra bouge dès la première image ; les éléments
  secondaires arrivent ensuite (`at` calés sur les mots via `cues`).
- Peu d'objets, gros, lisibles sur téléphone : 1 sujet + 1 ou 2 éléments de contexte. Le texte important va dans le
  calque 2D (`Studio.scene({transparent: true})`) : titre, étiquette, chiffre clé si besoin.
- Profondeur : un élément au premier plan ou à l'arrière-plan (`z`), légèrement flou, donne l'échelle.
- Halo discret : seuls l'accent et les lumières brillent ; pas de scène délavée.
