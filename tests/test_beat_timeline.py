from __future__ import annotations

from agent.core.channel_config import VisualBeatsConfig
from agent.core.visual_beats import DiagramLabel, VisualBeat, effective_min_duration
from agent.skills.audio.whisper_utils import WordSegment
from agent.skills.video.beat_timeline import compute_beat_timeline


def _min_for_beat(beat: VisualBeat) -> float:
    return effective_min_duration(beat, is_short=False, config=VisualBeatsConfig())


def test_beat_timeline_whisper_anchors() -> None:
    beats = [
        VisualBeat(order=1, phrase_anchor="premier mot", visual_type="documentary_photo", prompt="a"),
        VisualBeat(
            order=2,
            phrase_anchor="deuxieme phrase",
            visual_type="infographic",
            prompt="b",
            diagram_labels=[DiagramLabel(text="B", role="element")],
            duration_hint_s=6.0,
        ),
    ]
    words = [
        WordSegment(word="premier", start=0.0, end=0.4),
        WordSegment(word="mot", start=0.4, end=0.8),
        WordSegment(word="deuxieme", start=2.0, end=2.5),
        WordSegment(word="phrase", start=2.5, end=3.0),
    ]
    timeline = compute_beat_timeline(
        beats,
        words,
        audio_duration=10.0,
        min_duration_for_beat=_min_for_beat,
        image_paths=["/tmp/a.jpg", "/tmp/b.jpg"],
    )
    assert len(timeline) == 2
    assert timeline[0].start_s == 0.0
    assert timeline[1].start_s >= timeline[0].end_s - 0.01
    assert timeline[1].end_s - timeline[1].start_s >= 6.0


def test_beat_timeline_proportional_fallback() -> None:
    beats = [
        VisualBeat(order=1, phrase_anchor="aaa", visual_type="documentary_photo", prompt="a"),
        VisualBeat(order=2, phrase_anchor="bbbbbbbb", visual_type="documentary_photo", prompt="b"),
    ]
    timeline = compute_beat_timeline(
        beats,
        [],
        audio_duration=10.0,
        min_duration_for_beat=_min_for_beat,
        image_paths=["a.jpg", "b.jpg"],
    )
    assert len(timeline) == 2
    assert timeline[-1].end_s == 10.0


def test_beat_timeline_carries_text_layout() -> None:
    from agent.core.visual_beats import TextOverlayPlacement

    beats = [
        VisualBeat(
            order=1,
            phrase_anchor="chloroplaste absorbe",
            visual_type="scientific_diagram",
            prompt="diagram",
            diagram_labels=[DiagramLabel(text="Chloroplaste", role="organe")],
            duration_hint_s=6.0,
        ),
    ]
    layout = [TextOverlayPlacement(text="Chloroplaste", x_norm=0.3, y_norm=0.4)]
    timeline = compute_beat_timeline(
        beats,
        [],
        audio_duration=8.0,
        min_duration_for_beat=_min_for_beat,
        image_paths=["a.jpg"],
        text_layouts=[layout],
    )
    assert len(timeline[0].text_layout) == 1
    assert timeline[0].text_layout[0].text == "Chloroplaste"
