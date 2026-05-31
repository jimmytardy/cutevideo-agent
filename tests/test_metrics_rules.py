from __future__ import annotations

from agent.skills.analytics.metrics_rules import analyze_metrics_with_pandas


def test_analyze_metrics_success_trend() -> None:
    history = [{"views": 100, "likes": 5, "comments": 1}]
    current = {"views": 150, "likes": 8, "comments": 2}
    result = analyze_metrics_with_pandas(current, history, title="Test", platform="youtube")
    assert result["performance_verdict"] == "success"
    assert len(result["new_insights"]) >= 1


def test_analyze_metrics_underperforming() -> None:
    history = [{"views": 200, "likes": 10, "comments": 3}]
    current = {"views": 150, "likes": 8, "comments": 2}
    result = analyze_metrics_with_pandas(current, history, title="Test", platform="youtube")
    assert result["performance_verdict"] == "underperforming"


def test_analyze_metrics_single_snapshot() -> None:
    result = analyze_metrics_with_pandas(
        {"views": 50, "likes": 2, "comments": 0},
        [],
        title="Nouveau",
        platform="youtube",
    )
    assert result["performance_verdict"] in ("mixed", "success", "underperforming")
    assert "summary" in result
