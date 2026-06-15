"""Tests research models."""

from agent.core.research_models import ResearchBrief, ResearchSource, TimelineEntry


def test_research_brief_from_dict() -> None:
    data = {
        "subject_entity": "Paradisier de Raggiana",
        "key_facts": ["Espèce endémique de Papouasie-Nouvelle-Guinée"],
        "timeline": [{"year": "1935", "event": "Description scientifique"}],
        "sources": [{"title": "Wikipedia", "url": "https://fr.wikipedia.org", "snippet": "..."}],
        "visual_anchors": ["plumage orange"],
        "common_misconceptions": ["Confondu avec le paon"],
        "narrative_angles": ["Portrait de l'oiseau danseur"],
        "confidence": 0.85,
        "niche_risk": "high",
    }
    brief = ResearchBrief.from_dict(data)
    assert brief is not None
    assert brief.subject_entity == "Paradisier de Raggiana"
    assert len(brief.key_facts) == 1
    assert brief.timeline[0].year == "1935"
    assert brief.sources[0].title == "Wikipedia"
    assert brief.niche_risk == "high"


def test_research_brief_roundtrip() -> None:
    brief = ResearchBrief(
        subject_entity="Test",
        key_facts=["fait 1"],
        timeline=[TimelineEntry(year="2000", event="événement")],
        sources=[ResearchSource(title="Source", url="http://x", snippet="s")],
        confidence=0.9,
    )
    restored = ResearchBrief.from_dict(brief.to_dict())
    assert restored is not None
    assert restored.subject_entity == "Test"
    assert restored.key_facts == ["fait 1"]
