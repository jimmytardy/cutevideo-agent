from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SPAM_PATTERNS = [
    re.compile(r"https?://", re.I),
    re.compile(r"\b(crypto|bitcoin|casino|gratuit|click here|gagnez)\b", re.I),
]
THANKS_PATTERNS = re.compile(
    r"\b(merci|thanks|thank you|super|génial|excellent|bravo|top|incroyable)\b",
    re.I,
)
REPLY_TEMPLATE = "Merci beaucoup pour ton message, ça fait plaisir !"


@dataclass
class CommentHeuristicResult:
    platform_comment_id: str
    needs_reply: bool
    reply_text: str | None
    status: str
    is_constructive: bool
    constructive_note: str | None
    needs_llm: bool


def classify_comment(platform_comment_id: str, text: str) -> CommentHeuristicResult:
    """Classification locale sans LLM."""
    cleaned = (text or "").strip()
    lower = cleaned.lower()

    if len(cleaned) < 2:
        return CommentHeuristicResult(
            platform_comment_id=platform_comment_id,
            needs_reply=False,
            reply_text=None,
            status="ignored",
            is_constructive=False,
            constructive_note=None,
            needs_llm=False,
        )

    for pat in SPAM_PATTERNS:
        if pat.search(cleaned):
            return CommentHeuristicResult(
                platform_comment_id=platform_comment_id,
                needs_reply=False,
                reply_text=None,
                status="spam",
                is_constructive=False,
                constructive_note=None,
                needs_llm=False,
            )

    if THANKS_PATTERNS.search(lower) and len(cleaned) < 120:
        return CommentHeuristicResult(
            platform_comment_id=platform_comment_id,
            needs_reply=True,
            reply_text=REPLY_TEMPLATE,
            status="replied",
            is_constructive=False,
            constructive_note=None,
            needs_llm=False,
        )

    if "?" in cleaned and len(cleaned) >= 15:
        return CommentHeuristicResult(
            platform_comment_id=platform_comment_id,
            needs_reply=False,
            reply_text=None,
            status="new",
            is_constructive=True,
            constructive_note=None,
            needs_llm=True,
        )

    if len(cleaned) >= 40:
        return CommentHeuristicResult(
            platform_comment_id=platform_comment_id,
            needs_reply=False,
            reply_text=None,
            status="ignored",
            is_constructive=True,
            constructive_note=cleaned[:200],
            needs_llm=False,
        )

    return CommentHeuristicResult(
        platform_comment_id=platform_comment_id,
        needs_reply=False,
        reply_text=None,
        status="ignored",
        is_constructive=False,
        constructive_note=None,
        needs_llm=False,
    )


def classify_comments(comments: list[dict[str, Any]]) -> list[CommentHeuristicResult]:
    return [
        classify_comment(
            str(c.get("platform_comment_id", "")),
            str(c.get("text", "")),
        )
        for c in comments
    ]


def results_to_analysis_payload(results: list[CommentHeuristicResult]) -> list[dict[str, Any]]:
    return [
        {
            "platform_comment_id": r.platform_comment_id,
            "needs_reply": r.needs_reply,
            "reply_text": r.reply_text,
            "status": r.status,
            "is_constructive": r.is_constructive,
            "constructive_note": r.constructive_note,
        }
        for r in results
    ]


def rule_based_comment_insights(results: list[CommentHeuristicResult]) -> dict[str, Any]:
    """Insights simples sans LLM pour merge learning context."""
    questions = [r for r in results if r.needs_llm]
    constructive = [r for r in results if r.is_constructive and r.constructive_note]

    new_insights: list[dict[str, Any]] = []
    if len(questions) >= 2:
        new_insights.append(
            {
                "text": f"{len(questions)} commentaires avec questions — prévoir FAQ ou clarification en vidéo.",
                "source": "comments",
                "confidence": 0.7,
                "evidence": f"question_count={len(questions)}",
            }
        )
    if constructive:
        new_insights.append(
            {
                "text": "Retours constructifs détectés dans les commentaires récents.",
                "source": "comments",
                "confidence": 0.6,
                "evidence": f"constructive_count={len(constructive)}",
            }
        )

    summary = (
        f"Traitement heuristique : {len(results)} commentaire(s), "
        f"{len(questions)} question(s) pour revue LLM."
        if questions
        else f"Traitement heuristique : {len(results)} commentaire(s) traités sans LLM."
    )
    return {
        "summary": summary[:300],
        "new_insights": new_insights[:2],
        "invalidate_insight_ids": [],
        "update_insights": [],
    }
