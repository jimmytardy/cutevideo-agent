# Images IA (`ai-image`) : choisir le modèle et écrire le prompt

`ai-image` est payant et plafonné (`max_ai_images` du brief) : à utiliser **en dernier recours**, quand ni une
banque (`search-media`) ni une animation du kit ne conviennent. Le prompt part **tel quel** au modèle : rien n'est
ajouté derrière toi.

Le plafond compte les **générations facturées**, pas les images présentes dans la vidéo. Une image déjà produite
dans cette création est gardée en cache : relancer **exactement le même prompt**, avec le même modèle et le même
format, la reprend sans rien payer et sans entamer le plafond — la sortie porte alors `"reused": true`. Deux
conséquences pratiques :

- Tu peux relancer un plan à l'identique entre deux itérations sans te pénaliser.
- Reformuler un prompt pour « réessayer » coûte une génération. Si l'image convenait, reprends-la mot pour mot ;
  ne change le prompt que si tu veux vraiment une autre image.

## « Ne convient pas » veut dire : ne veut pas dire la bonne chose

Un média ou une icône ne convient pas seulement quand il manque : il ne convient pas non plus quand il **désigne
autre chose** que le propos du plan. Le kit n'a que ~350 icônes, donc la plus proche est souvent fausse. Cas réels
relevés en production :

| Le plan dit | Choix par défaut | Ce que le spectateur lit |
|---|---|---|
| une pince de crevette | icône `hand` | une main humaine |
| « pour appeler le serveur » | icône de cuisinier | un cuisinier, pas un serveur |
| « l'eau bout à froid » | icône `snowflake` | du gel — **l'inverse du propos** |

Quand le plan **désigne un objet, un rôle ou une action précis** et que ni les banques ni le kit ne le disent
juste, une image IA à quelques centimes vaut mieux qu'un contresens à l'écran : c'est le lecteur qui paie l'à-peu-près.

Cela **n'augmente pas le plafond** et ne s'applique pas aux ambiances, fonds ou textures, où une icône ou une image
de banque approchante convient très bien. Vise la justesse, pas le volume : une image juste vaut mieux que trois
images décoratives.

## Modèles
`--model` n'accepte que les modèles autorisés pour la chaîne : le plan de la chaîne (le défaut) et ceux qui
coûtent moins cher, pour lesquels le propriétaire a la clé. Sans `--model`, c'est le modèle de la chaîne. Une
erreur indique les modèles disponibles.

| Modèle | Prix ≈ / image | Quand |
|---|---|---|
| `flux_schnell` | 0,003 € | brouillon, fond abstrait ou texture ; détails faibles |
| `imagen3_fast` | 0,018 € | photo réaliste simple (Google, compte de service GCP) |
| `flux_2_dev` | 0,024 € | bon rapport qualité/prix pour la plupart des plans |
| `imagen3` | 0,037 € | scène photo réaliste avec personnes ou décor complexe |
| `flux_pro` | 0,042 € | rendu soigné, composition précise, illustration ; bon choix pour le photoréalisme à prix moyen (prix donné pour un 1080×1920) |
| `flux_ultra` | 0,07 € | photoréalisme brut (textures, peau, matières) : fond de miniature héro |

Prends le modèle le moins cher qui suffit pour ce plan. Si un modèle échoue (clé refusée, prompt bloqué), réessaie
une fois avec un autre modèle de la liste, sinon passe à une banque ou une animation.

## Écrire le prompt (en anglais)
Les modèles pondèrent davantage le **début** du prompt. Ordre conseillé :

1. **Sujet concret** : qui/quoi, action, lieu (« an emperor penguin sliding on its belly across blue ice »).
2. **Cadrage** : plan large / moyen / gros plan, angle (« low angle close-up », « aerial view »), cadrage
   vertical 9:16 avec le sujet au centre-haut (les sous-titres occupent le tiers bas).
3. **Lumière et objectif** : décris-les plutôt que d'empiler des mots-clés de qualité.
4. **Palette et ambiance** : cohérente avec les plans voisins du montage.
5. **Contraintes** : « No text, no watermark, no logo, no caption. No collage. »

Évite les tags de qualité vides (« 8k, masterpiece, high quality ») et les notions abstraites qui ne se dessinent
pas (« theme: … », « tone: … ») : chaque mot doit décrire quelque chose de visible.

### Lumière et objectif selon le sujet
| Sujet | À ajouter |
|---|---|
| Sport | telephoto 200mm, fast shutter freezing motion, stadium floodlights, vivid saturated colors, dynamic angle |
| Enquête, faits divers | 35mm lens, low-key chiaroscuro lighting, desaturated muted palette, shallow depth of field, tense mood |
| Espace, science | ultra-detailed, deep contrast, cool blue and teal tones, crisp clarity, dramatic rim light |
| Art, histoire | soft directional museum lighting, warm amber tones, fine surface texture, archival authentic look |
| Nature | natural daylight, golden hour warmth, high dynamic range, rich greens and earth tones, shallow depth of field |
| Documentaire, actualité | 35mm lens, natural available light, neutral realistic color grade, candid moment, cinematic framing |
| Humour | bright high-key lighting, bold vivid colors, playful exaggerated composition |
| Tech, finance, produit | clean studio lighting, soft shadows, modern minimal palette, crisp product detail |
| Par défaut | cinematic lighting, balanced composition, natural color grade, shallow depth of field |

### Schémas, cartes, infographies
Une image IA ne sait pas écrire correctement : pour un chiffre, une carte, une comparaison ou une frise, utilise
**une animation du kit**. Si tu génères malgré tout un schéma, termine par « No text, no labels, no numbers, no
letters anywhere. Icons, arrows and shapes only. No caption boxes, no title banner, no text placeholders. » et
ajoute le texte au montage (`text` du clip) ou dans la miniature (`thumbnail --text`).

### À éviter dans l'image
Visages de célébrités identifiables, logos ou marques, texte incrusté, mains en gros plan (souvent déformées),
collages ou cadres. Décris ce que tu veux voir plutôt que ce que tu ne veux pas : Flux ignore presque les
négations.

## Exemples
- Plan : `ai-image --name 04_glacier --prompt "A deep blue crevasse splitting a glacier, seen from inside the ice
  looking up at a thin strip of sky, vertical framing, natural daylight filtering through the ice, cool blue and
  teal tones, high dynamic range. No text, no watermark, no logo."`
- Fond de miniature : `ai-image --name thumb_bg --model flux_ultra --aspect 16:9 --prompt "Close-up of a
  shocked medieval knight lifting his visor, dramatic rim light, warm amber tones, shallow depth of field, empty
  dark space on the right side. No text, no watermark, no logo."`
