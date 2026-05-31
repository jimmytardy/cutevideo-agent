from __future__ import annotations

from agent.skills.comments.heuristics import classify_comment


def test_classify_spam_url() -> None:
    r = classify_comment("c1", "Gagnez 1000€ sur https://spam.example")
    assert r.status == "spam"
    assert r.needs_llm is False


def test_classify_thanks() -> None:
    r = classify_comment("c2", "Merci pour cette vidéo, super travail !")
    assert r.needs_reply is True
    assert r.reply_text is not None
    assert r.needs_llm is False


def test_classify_question_needs_llm() -> None:
    r = classify_comment("c3", "Pourquoi ce personnage a-t-il fait ce choix en 1789 ?")
    assert r.needs_llm is True
    assert r.is_constructive is True
