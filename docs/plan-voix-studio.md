# Plan — Voix IA « rendu studio »

> **État : implémenté (5 piliers).** Voir « État d'implémentation » en fin de document.


Objectif : passer d'une voix TTS brute à une narration qui respecte le réflexe gagnant —
**(1) script réécrit pour l'oral → (2) vitesse/intonation ajustées → (3) traitement audio léger
(EQ, compression, de-esser)** — tout en restant compatible avec les règles de monétisation YouTube
(contenu original, valeur ajoutée, pas de production purement automatisée « à la chaîne »).

Ce plan s'appuie sur l'architecture existante. Aucune réécriture lourde : on se branche sur des
points d'intégration déjà présents.

---

## État actuel (ce qui existe déjà)

| Brique | Fichier | Ce qu'elle fait aujourd'hui |
|--------|---------|------------------------------|
| Génération du script | `agent/agents/scenario_agent.py` | Produit `narration_text` + `delivery_style` (`azure_style`, `pace`, `emotion`, `emphasis_words`) par segment |
| Construction prosodie | `agent/skills/audio/ssml_builder.py` | Map `delivery_style`/`mood`/`tone` → `rate`/`pitch`/`style` Azure + pauses SSML + emphasis |
| Synthèse TTS | `agent/skills/audio/tts.py` (`generate_tts`) | Route vers azure / gemini / edge-tts |
| Normalisation audio | `agent/skills/audio/tts.py` (`normalize_wav`) | **Seul** traitement : `loudnorm=I=-16:TP=-1.5:LRA=11`, 48 kHz mono |
| Mix voix + musique | `agent/skills/audio/audio_mixer.py` | Ducking sidechain, volumes par contexte |
| Config voix par chaîne | `agent/core/channel_config.py` | `tts_engine/voice/style/rate/pitch/insert_pauses`, `gemini_tts` |
| Config globale | `data/agent_config.json` → `tts`, `audio_mix`, `whisper` | Défauts |

**Point clé** : les trois moteurs (azure → `azure_tts.py`, edge → `_generate_edge_tts`,
gemini → `gemini_tts.py`) appellent **tous** `normalize_wav()`. C'est le **chokepoint unique**
où brancher la chaîne de mastering studio — une seule modification couvre les trois moteurs.

**Manque aujourd'hui** : aucune EQ, aucune compression, aucun de-esser. Le seul traitement est
le `loudnorm`. La réécriture « oral » est implicite dans le prompt scénario mais non explicitée.

---

## Pilier 1 — Réécrire le script pour l'oral

Objectif : phrases courtes, ponctuation qui crée des pauses naturelles, pas de tournures
« écrites » imprononçables (sigles, chiffres bruts, incises longues).

### Option A (recommandée) — Renforcer le prompt de `ScenarioAgent`
Le scénario produit déjà `narration_text`. On ajoute des **contraintes oral** explicites dans le
prompt (`agent/agents/scenario_agent.py`, autour des lignes 68–178) :
- phrases ≤ 20 mots, une idée par phrase ;
- ponctuation forte (`.`, `!`, `?`) pour rythmer les pauses (déjà exploitée par `_insert_pauses`) ;
- nombres/dates/sigles écrits en toutes lettres pour la prononciation FR
  (« 1789 » → « dix-sept cent quatre-vingt-neuf », « km/h » → « kilomètres heure ») ;
- interdiction des parenthèses/incises longues ;
- `emphasis_words` ciblés sur les mots porteurs (déjà supporté par `_apply_emphasis`).

### Option B — Passe dédiée « oralisation » (skill `agent/skills/audio/oralize.py`)
Petite fonction qui post-traite `narration_text` avant TTS :
- normalise nombres/dates/unités → lettres (lib `num2words` FR, déjà dans l'écosystème Python) ;
- découpe les phrases trop longues sur les conjonctions ;
- nettoie caractères non prononçables (`*`, `#`, markdown résiduel).
Appelée dans `NarratorAgent._generate_segment_audio` juste avant `generate_tts`
(`agent/agents/narrator_agent.py:160`).

> **Reco** : faire **A d'abord** (gain immédiat, zéro coût runtime) puis **B** pour la
> normalisation déterministe des nombres/sigles que le LLM rate parfois.

**Monétisation** : c'est exactement le « vrai script travaillé » exigé par le Programme Partenaire.
À documenter comme valeur ajoutée éditoriale.

---

## Pilier 2 — Ajuster vitesse et intonation

L'infrastructure existe déjà (`ssml_builder.py`). On l'enrichit plutôt que de la refaire.

1. **Exploiter `delivery_style` par segment** — déjà mappé (`PACE_TO_RATE`, `EMOTION_TO_PITCH`,
   `MOOD_TO_AZURE`). Vérifier que `ScenarioAgent` varie bien le style segment par segment
   (consigne déjà présente lignes 105–110). À surveiller via le critic.
2. **Pauses fines** — `_insert_pauses` (ssml_builder.py:155) gère déjà ponctuation forte + chiffres.
   Étendre : pause courte sur `,` et `;` (ex. `<break time='150ms'/>`) pour un débit plus respirant,
   derrière un flag config `tts_comma_pauses` (défaut `false` pour ne pas régresser).
3. **Bornes de sécurité rate/pitch** — clamp des valeurs pour éviter les voix « accélérées » qui
   sonnent robotiques (rate dans `[-15%, +15%]`). À ajouter dans `_resolve_prosody`.
4. **Gemini** — pas de SSML : l'intonation passe par le prompt de style
   (`mood`/`editorial_tone`/`tts_style` déjà transmis à `synthesize_gemini_tts`). Documenter les
   styles qui marchent le mieux.

Aucun nouveau fichier requis : modifications localisées dans `ssml_builder.py` + config.

---

## Pilier 3 — Traitement audio léger (EQ, compression, de-esser) → rendu studio

C'est le **gros manque** et le plus fort levier qualité. On insère une chaîne FFmpeg de mastering
**au chokepoint unique** `normalize_wav()` (`agent/skills/audio/tts.py:52`).

### Chaîne proposée (ordre studio classique, avant le loudnorm final)
```
highpass=f=80            # coupe les basses parasites / pop
equalizer=f=200:t=q:w=1:g=-2     # désembourbe le bas-médium (effet « boîte »)
equalizer=f=3000:t=q:w=2:g=2     # présence/intelligibilité
deesser                  # atténue les sifflantes (s, ch) — filtre natif ffmpeg
acompressor=threshold=-18dB:ratio=3:attack=15:release=120:makeup=2   # dynamique homogène
loudnorm=I=-16:TP=-1.5:LRA=11    # normalisation broadcast (déjà présente, reste en dernier)
```

### Implémentation
- Nouveau module `agent/skills/audio/mastering.py` qui construit la chaîne `-af` à partir d'une
  config, avec un **preset par défaut `voice-studio`** et la possibilité de désactiver (`off`).
- `normalize_wav()` lit ce preset et concatène les filtres avant `loudnorm`. Comme les 3 moteurs
  passent par cette fonction, **azure / edge / gemini en bénéficient d'un coup**.
- Garde-fou : si `deesser` n'est pas dispo dans la build FFmpeg, fallback gracieux (try/probe une
  fois au démarrage, log + skip) pour ne pas casser la pipeline.

### Config (`data/agent_config.json` → nouveau bloc `audio_mastering`)
```json
"audio_mastering": {
  "enabled": true,
  "preset": "voice-studio",
  "highpass_hz": 80,
  "deesser": true,
  "compressor": { "threshold_db": -18, "ratio": 3, "attack_ms": 15, "release_ms": 120, "makeup_db": 2 },
  "eq": [ { "f": 200, "g": -2, "w": 1 }, { "f": 3000, "g": 2, "w": 2 } ]
}
```
Exposé par chaîne via `ChannelRuntimeConfig` (`agent/core/channel_config.py`) — même schéma de
layering que `audio_mix` : un champ `AudioMasteringConfig(BaseModel)` + résolution dans
`resolve_channel_config()`.

> Bénéfice : « léger » et réversible. Tous les réglages restent éditoriaux et par chaîne, ce qui
> évite l'effet « usine » uniforme — cohérent avec l'exigence de monétisation.

---

## Ordre de mise en œuvre (incrémental, testable à chaque étape)

| # | Étape | Fichiers | Effort | Impact |
|---|-------|----------|--------|--------|
| 1 | **Chaîne mastering** dans `normalize_wav` + config | `tts.py`, nouveau `mastering.py`, `agent_config.json`, `channel_config.py` | M | ⭐⭐⭐ (le plus audible) |
| 2 | **Renfort prompt oral** | `scenario_agent.py` | S | ⭐⭐ |
| 3 | **Pauses fines + clamp rate/pitch** | `ssml_builder.py` (+ flag config) | S | ⭐⭐ |
| 4 | **Skill `oralize`** (nombres/sigles → lettres) | nouveau `oralize.py`, `narrator_agent.py` | M | ⭐⭐ |
| 5 | **Préréglages de styles Gemini** documentés | `gemini_tts.py`, doc | S | ⭐ |

Faire **#1 en premier** : un seul point d'insertion, effet immédiat sur les 3 moteurs, totalement
réversible via `enabled:false`.

---

## Tests & validation

- **Unitaires** (`tests/`, pytest-asyncio, pas de mock DB) :
  - `mastering.py` : la chaîne `-af` générée correspond au preset (assertion sur la chaîne de
    filtres, pas besoin d'audio réel) ;
  - `oralize.py` : « 1789 » → lettres, phrases longues découpées, markdown nettoyé ;
  - `ssml_builder` : clamp rate/pitch, pauses virgule derrière le flag.
- **Validation perceptive** : générer un même segment dans `before/after`, comparer
  (LUFS via `ffmpeg loudnorm` print, et écoute). Conserver 3–4 échantillons de référence dans
  `tmp/` ou un dossier QA.
- **Non-régression** : `enabled:false` doit reproduire exactement le `loudnorm` actuel.

---

## Risques & garde-fous

- **Build FFmpeg sans `deesser`** → probe au démarrage, fallback skip + log.
- **Sur-traitement** (voix « pompée ») → presets légers + tout par chaîne ; documenter des valeurs
  conservatrices par défaut.
- **Latence** → la chaîne ajoute ~quelques 100 ms par segment ; négligeable vs synthèse + whisper.
- **Monétisation** → garder la traçabilité « script oralisé + montage travaillé » comme preuve de
  valeur ajoutée ; éviter un rendu uniforme sur toutes les chaînes (d'où config par chaîne).

---

## État d'implémentation

| Pilier | Statut | Fichiers livrés |
|--------|--------|-----------------|
| 3 — Mastering studio (EQ/comp/de-esser) | ✅ | `agent/skills/audio/mastering.py` (nouveau), `tts.py::normalize_wav` (chaîne `-af` mastering+loudnorm), `azure_tts.py`/`gemini_tts.py`/`_generate_edge_tts` (param `mastering`), `data/agent_config.json::audio_mastering`, `channel_config.py::AudioMasteringConfig` + `_resolve_audio_mastering` |
| 2 — Vitesse / intonation | ✅ | `ssml_builder.py` : `_clamp_rate`/`_clamp_pitch` (bornes ±15 % / ±8 Hz), pauses virgule (`comma_pauses`) ; flag `tts_comma_pauses` (config + ChannelRuntimeConfig) |
| 1 — Script pour l'oral (prompt) | ✅ | `scenario_agent.py` : blocs « ÉCRITURE POUR L'ORAL » (long + short) |
| 4 — Oralisation déterministe | ✅ | `agent/skills/audio/oralize.py` (nouveau, `num2words` optionnel), appelé dans `narrator_agent.py` ; flag `tts_oralize` ; dépendance `requirements.txt` |
| 5 — Presets styles Gemini | ✅ | `gemini_tts.py::build_gemini_tts_prompt` : base « rendu studio » (débit posé, pauses naturelles) + docstring |

**Points d'intégration clés**
- `normalize_wav` reste le chokepoint unique : azure / edge / gemini bénéficient tous du mastering.
- `NarratorAgent._generate_segment_audio` orchestre : `oralize_text` → `generate_tts(comma_pauses, mastering=cfg.audio_mastering.model_dump())`.
- Tout est piloté par chaîne via `ChannelRuntimeConfig` (layering défauts globaux → `Channel.config`).

**Garde-fous livrés**
- Mastering `enabled:false` ⇒ retour exact au comportement loudnorm d'origine (testé).
- `deesser` indisponible dans la build ffmpeg ⇒ probe caché + skip gracieux (`ffmpeg_has_filter`).
- `num2words` absent ⇒ chiffres conservés sans erreur.

**Tests** : `tests/test_mastering.py`, `tests/test_oralize.py`, extensions de `tests/test_tts_ssml.py`
(clamp rate/pitch, pauses virgule). Suite complète : 346 passed, 1 skipped.

**Activer l'option pauses-virgule** (off par défaut) : `tts.comma_pauses: true` dans la config chaîne.
