from __future__ import annotations

from typing import Any

import pandas as pd

from agent.core.config import load_agent_config


def _analytics_thresholds() -> dict[str, float]:
    engagement = load_agent_config().get("engagement", {})
    analytics = engagement.get("analytics_thresholds", {})
    return {
        "views_success_pct": float(analytics.get("views_success_pct", 20.0)),
        "views_underperform_pct": float(analytics.get("views_underperform_pct", -10.0)),
    }


def analyze_metrics_with_pandas(
    current_metrics: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    title: str = "",
    platform: str = "",
) -> dict[str, Any]:
    """
    Analyse déterministe des métriques — sortie compatible merge_llm_context_update.
    """
    thresholds = _analytics_thresholds()
    success_pct = thresholds["views_success_pct"]
    under_pct = thresholds["views_underperform_pct"]

    views_now = int(current_metrics.get("views", 0) or 0)
    likes_now = int(current_metrics.get("likes", 0) or 0)
    comments_now = int(current_metrics.get("comments", 0) or 0)

    rows: list[dict[str, Any]] = []
    for h in history:
        rows.append(
            {
                "views": int(h.get("views", 0) or 0),
                "likes": int(h.get("likes", 0) or 0),
                "comments": int(h.get("comments", 0) or 0),
            }
        )
    rows.append({"views": views_now, "likes": likes_now, "comments": comments_now})

    verdict = "mixed"
    insights: list[dict[str, Any]] = []
    pct_change: float | None = None

    if len(rows) >= 2:
        df = pd.DataFrame(rows)
        first_views = int(df["views"].iloc[0])
        last_views = int(df["views"].iloc[-1])
        if first_views > 0:
            pct_change = ((last_views - first_views) / first_views) * 100.0
            if pct_change >= success_pct:
                verdict = "success"
            elif pct_change <= under_pct:
                verdict = "underperforming"
        elif last_views > 0:
            verdict = "success"
            pct_change = 100.0

        if pct_change is not None:
            insights.append(
                {
                    "text": (
                        f"Évolution des vues sur la fenêtre analysée : "
                        f"{pct_change:+.1f}% ({first_views} → {last_views})."
                    ),
                    "source": "analytics",
                    "confidence": 0.8 if abs(pct_change) >= 15 else 0.55,
                    "evidence": f"views_delta_pct={pct_change:.1f}",
                }
            )

        if len(df) >= 3:
            view_slope = float(df["views"].diff().mean())
            if view_slope > 0:
                insights.append(
                    {
                        "text": "Tendance positive sur les snapshots récents (vues en hausse).",
                        "source": "analytics",
                        "confidence": 0.65,
                        "evidence": f"mean_views_diff={view_slope:.1f}",
                    }
                )
    elif views_now > 0:
        verdict = "mixed"
        insights.append(
            {
                "text": f"Premier snapshot : {views_now} vues, {likes_now} likes.",
                "source": "analytics",
                "confidence": 0.5,
                "evidence": "single_snapshot",
            }
        )

    title_part = f"« {title} »" if title else "cette vidéo"
    platform_part = platform or "plateforme"
    if pct_change is not None:
        summary = (
            f"{title_part} ({platform_part}) : verdict {verdict}. "
            f"Vues {views_now}, variation {pct_change:+.1f}% sur la période."
        )
    else:
        summary = (
            f"{title_part} ({platform_part}) : verdict {verdict}. "
            f"Vues {views_now}, likes {likes_now}, commentaires {comments_now}."
        )

    return {
        "summary": summary[:400],
        "performance_verdict": verdict,
        "new_insights": insights[:2],
        "invalidate_insight_ids": [],
        "update_insights": [],
    }
