# Roadmap qualité vidéo — backlog actif

> Spec détaillée : plan Cursor `roadmap_qualité_vidéo_cd3fa3f0` (`.cursor/plans/`).
> **1 build = 1 session Agent**, diff < 15 fichiers, pytest avant merge.

## Déjà livré (ne pas refaire)

- Socle montage : SFX pop/impact/riser, ASS `animated_text.py`, LUT/grain/glitch, music reveal cut
- Plan qualité amont : prompts Flux, ArtDirector, critic vision, `metadata_agent`, `thumbnail_agent` (pipeline)
- Tests : `tests/test_socle_style_youtubers.py`

## Backlog (ordre)

> Statut vérifié dans le code le 2026-10-03.

| Build | Objectif | Statut |
|-------|----------|--------|
| **B1** | `long_montage_profile` + `load_sfx_config` + beat-cuts SFX long (`editor_agent`) | ✅ livré |
| **B2** | Flash inter-segment + pacing long + mood dans `montage_planner_agent` | ✅ livré |
| **B3** | `thumbnail_agent` → `publisher/executor.py` (`set_thumbnail`), pas `publisher/thumbnail.py` | ✅ livré (`tests/test_publisher_thumbnail.py`) |
| **B4** | `test_montage_audit`, SFX click/impact punch, ambient bed, critic SFX, graphify | ✅ livré |
| **B5** | opt-in : overrides `Channel.config` video_style, parallaxe/match cuts | 🟡 overrides livrés (`video_style_config.channel_style_overrides`) ; **parallaxe / match cuts restent à faire** |

## Gates

- **Vague 1** (après B2) : pytest + vidéo longue test — cuts audibles, flash chapitres, voix OK — *validation vidéo manuelle non tracée*
- **Vague 2** (après B4) : publication test avec miniature agent — *validation manuelle non tracée*

## Docs liés

- [`docs/plan-socle-style-youtubers.md`](plan-socle-style-youtubers.md) — spec montage (largement implémentée)
- [`docs/plan-amelioration-qualite-video.md`](plan-amelioration-qualite-video.md) — amont images/agents (§7 fait ; B3 livré ; reste parallaxe/match cuts de B5)
