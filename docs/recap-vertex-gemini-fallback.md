# Récapitulatif : Vertex AI en repli de Gemini (voix et analyse vidéo de Claude Studio)

## 1. Résultat

**Fait.** La voix Gemini et la revue vidéo d'`analyze` passent par Vertex AI quand la clé Gemini est absente ou refusée. L'ordre est clé Gemini → Vertex → repli existant. Le fonctionnement est vérifié en réel avec le compte GCP de tardyjim26@gmail.com, puis déployé.

## 2. Fichiers modifiés

- `agent/core/vertex.py` (nouveau) : client Vertex partagé.
  - `vertex_credentials()` : extrait de `_build_vertex_credentials`.
  - `vertex_project_id()`.
  - `vertex_genai_client(credentials_json, location, *, project_id=None)` : le projet est lu dans le JSON et la région vaut sinon `settings.gcp_location`.
  - `gemini_key_refused(exc)` : vrai pour une `google.genai.errors.ClientError` 400/401/403/429.
- `agent/core/llm_resolver.py` :
  - `_build_vertex_credentials` est supprimé et `_call_gemini_text` utilise `vertex_genai_client` avec le projet et la région de `GcpCredentials`.
  - L'import `json`, devenu inutile, est retiré.
  - Le comportement des agents ne change pas.
- `agent/core/api_keys.py` : nouveau champ `UserKeys.gcp_location`, rempli par `resolve_user_keys` depuis `metadata.location` de la clé `gcp`.
- `studio/user_keys.py` : nouvelle variable `GCP_LOCATION = "STUDIO_GCP_LOCATION"`, ajoutée à `STUDIO_SECRET_VARS` (donc à `INHERITED_SECRET_VARS`) et à `studio_env()`.
- `agent/skills/audio/gemini_tts.py` :
  - Nouvelle dataclass `VertexTarget(credentials_json, location, model)`.
  - Nouvelle fonction `vertex_tts_target()`, qui lit `tts.gemini.vertex_model` / `vertex_location` dans `data/agent_config.json`. La région du compte ne sert qu'à défaut.
  - Nouvelle constante `DEFAULT_VERTEX_TTS_MODEL = "gemini-2.5-flash-tts"`.
  - `synthesize_gemini_tts` accepte `api_key: str | None`, `vertex: VertexTarget | None` et `transient_retries`.
- `agent/skills/audio/tts.py` :
  - `resolve_engine` reçoit `gcp_credentials_json` : Gemini est disponible avec une clé Gemini **ou** un compte GCP.
  - `generate_tts` reçoit `gcp_credentials_json` / `gcp_location`. Il essaie la clé Gemini, puis Vertex si elle est absente ou refusée, et renvoie alors le moteur `"gemini-vertex"`.
  - Quand Vertex est disponible, l'appel avec la clé n'est fait qu'une fois, sans relances transitoires : un quota épuisé ne coûte pas 15 s par segment.
- `studio/tools.py` (`_synthesize`) : passe `user_key(GCP_CREDENTIALS_JSON)` et `user_key(GCP_LOCATION)`. La chaîne des moteurs ne change pas.
- `studio/analyze.py` :
  - `_gemini_review` renvoie `(avis, source)` : clé Gemini, puis Vertex en cas d'absence ou de refus, avec le modèle `STUDIO_GEMINI_MODEL`.
  - Le message d'erreur devient « aucune clé Gemini ni compte Google Cloud… ».
  - Dans `_gemini_section`, `source` vaut `gemini`, `gemini-vertex` ou `claude`.
  - La docstring du module est mise à jour.
- `studio/contracts.py` : le commentaire de `Critique.analysis` mentionne `gemini-vertex`.
- `data/agent_config.json` : ajout de `tts.gemini.vertex_model: "gemini-2.5-flash-tts"`.
- `dashboard/lib/apiKeyProviders.ts` :
  - Le fournisseur `gcp` s'appelle « Google Cloud (Vertex AI) ».
  - Sa description et le titre du tutoriel sont mis à jour.
  - Les étapes « activer l'API Vertex AI » et « rôle Vertex AI User » existaient déjà.
- `CLAUDE.md` : repli Vertex dans les puces `tts` / `analyze`, et ajout de `STUDIO_GCP_LOCATION`.
- Tests :
  - `tests/test_gemini_vertex_fallback.py` (nouveau, 9 tests) :
    - voix via Vertex sans clé (`vertexai=True`, projet du JSON, région) ;
    - modèle et région lus dans la config ;
    - outil `tts` : 429 sur la clé → `engine: "gemini-vertex"` ;
    - erreur de clé sans GCP → erreur propagée ;
    - sans clé ni compte → azure puis edge ;
    - revue `analyze` : Vertex sans clé, Vertex après un refus, clé valide conservée, repli Claude sans rien.
  - `tests/test_studio_launcher.py` : `STUDIO_GCP_CREDENTIALS_JSON` / `STUDIO_GCP_LOCATION` sont posées par `build_env` et `STUDIO_GCP_LOCATION` est retirée de l'environnement hérité.
  - `tests/test_studio_animate.py` : le bac à sable bwrap ne voit pas `STUDIO_GCP_CREDENTIALS_JSON`.
  - `tests/test_llm_resolver.py` : non-régression de `_call_gemini_text` via Vertex, qui utilise le client partagé avec le projet et la région de la clé.

## 3. Tests, lint et vérification réelle

- `pytest -q -p no:cacheprovider --ignore=tests/test_studio_live.py` : **311 passed, 5 skipped** (209,6 s).
  - Les 5 tests ignorés sont ceux de `tests/test_studio_pipeline_db.py`, faute d'infra de test jetable.
  - Le test bwrap du bac à sable a bien tourné.
- `uvx ruff check .` : All checks passed.
- `npm --prefix dashboard run typecheck` : OK, sans erreur.
- `npm --prefix dashboard run lint` : No ESLint warnings or errors.
- Vérification réelle dans `cutevideo-worker-dev-1`, avec le compte GCP de tardyjim26@gmail.com et sans clé Gemini :
  - Aucune région n'est enregistrée avec la clé `gcp` (`metadata.location` absente) : c'est donc `settings.gcp_location` = `europe-west1` qui s'applique.
  - TTS : `synthesize_gemini_tts(…, vertex=VertexTarget(…, "europe-west1", "gemini-2.5-flash-tts"))` réussit du **premier coup** (3,97 s d'audio). Les essais `global` / `us-central1` n'ont pas été nécessaires.
  - **Retenu** : modèle `gemini-2.5-flash-tts`, région `europe-west1`. La valeur par défaut `vertex_location` n'est pas posée dans la config : on suit la région du compte, sinon `europe-west1`.
  - Revue `analyze` (`_gemini_section("gemini", …)` sur un MP4 de 2 s généré par ffmpeg) : `source: gemini-vertex`, avec un JSON structuré conforme à la grille (scores, hook, rythme, corrections…).
  - Rien n'a échoué.

## 4. Déploiement

**Fait.**
- Le dashboard a été reconstruit avec la commande prescrite (`BUILD-OK`).
- `docker restart cutevideo` a été lancé, et `curl http://127.0.0.1:3333/` renvoie **200**.
- Le worker recharge seul le code Python, et `.env` n'a pas été modifié.
- `graphify update .` a été lancé : 3879 nœuds, 190 communautés.

## 5. Reste à faire / écarts avec le plan

- Rien n'a été commité, comme demandé. Le dépôt contient aussi des modifications non commitées d'une autre session (abonnement Claude, validation des clés…) : elles n'ont pas été touchées, mais plusieurs fichiers sont partagés (`CLAUDE.md`, `agent/core/api_keys.py`, `agent/core/llm_resolver.py`, `studio/user_keys.py`, `dashboard/lib/apiKeyProviders.ts`).
- Écarts mineurs :
  - `tts.gemini.vertex_location` n'est pas fixé dans `data/agent_config.json`, puisque `europe-west1` sert le modèle. La clé reste lue si on veut la forcer, par exemple si un utilisateur enregistre une région qui ne sert pas le TTS.
  - Ajout d'un paramètre `transient_retries` à `synthesize_gemini_tts`, pour ne pas attendre les relances 429 quand Vertex est disponible.
  - `gemini_key_refused()` est placé dans `agent/core/vertex.py`, pour être partagé par la voix et l'analyse.
- Une décision reste à prendre par l'utilisateur : le compte GCP n'a pas de région enregistrée. On peut en saisir une dans Compte → Clés API, champ « Région Vertex AI », si l'on veut autre chose que `europe-west1`.
- `graphify label` est suggéré par graphify pour renommer les communautés. C'est optionnel et payant en LLM.
