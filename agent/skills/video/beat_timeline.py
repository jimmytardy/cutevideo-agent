from __future__ import annotations



import re

import unicodedata

from collections.abc import Callable

from dataclasses import dataclass



from agent.core.visual_beats import TextOverlayPlacement, VisualBeat

from agent.skills.audio.whisper_utils import WordSegment





@dataclass(frozen=True)

class BeatTimelineEntry:

    beat: VisualBeat

    start_s: float

    end_s: float

    image_path: str

    on_screen_text: str

    text_layout: tuple[TextOverlayPlacement, ...] = ()





def compute_beat_timeline(

    beats: list[VisualBeat],

    words: list[WordSegment],

    audio_duration: float,

    *,

    min_duration_for_beat: Callable[[VisualBeat], float],

    image_paths: list[str],

    text_layouts: list[list[TextOverlayPlacement] | None] | None = None,

) -> list[BeatTimelineEntry]:

    if not beats:

        return []



    starts = _resolve_beat_starts(beats, words, audio_duration)

    timeline: list[BeatTimelineEntry] = []

    layouts = text_layouts or [None] * len(beats)



    cursor = 0.0

    for i, beat in enumerate(beats):

        min_d = min_duration_for_beat(beat)

        start = max(starts[i], cursor) if i > 0 else starts[i]

        natural_end = starts[i + 1] if i + 1 < len(starts) else audio_duration

        end = max(natural_end, start + min_d)

        end = min(end, audio_duration)

        if end <= start:

            end = min(start + max(min_d, 0.5), audio_duration)



        path = image_paths[i] if i < len(image_paths) else image_paths[-1]

        layout = layouts[i] if i < len(layouts) else None

        layout_tuple = tuple(layout) if layout else ()



        timeline.append(

            BeatTimelineEntry(

                beat=beat,

                start_s=start,

                end_s=end,

                image_path=path,

                on_screen_text=beat.on_screen_text,

                text_layout=layout_tuple,

            )

        )

        cursor = end



    return _extend_last_beat(timeline, audio_duration)





def _resolve_beat_starts(

    beats: list[VisualBeat],

    words: list[WordSegment],

    audio_duration: float,

) -> list[float]:

    if not words:

        return _proportional_starts(beats, audio_duration)



    starts: list[float] = []

    for beat in beats:

        ts = _find_anchor_timestamp(beat.phrase_anchor, words)

        starts.append(ts if ts is not None else 0.0)



    for i in range(1, len(starts)):

        if starts[i] <= starts[i - 1]:

            starts[i] = starts[i - 1] + 0.01



    if starts[0] > 0.5:

        starts[0] = 0.0



    return starts





def _find_anchor_timestamp(anchor: str, words: list[WordSegment]) -> float | None:

    norm_anchor = _normalize(anchor)

    anchor_words = norm_anchor.split()

    if not anchor_words:

        return None



    norm_tokens = [_normalize(w.word) for w in words]

    window = len(anchor_words)

    for i in range(len(norm_tokens) - window + 1):

        chunk = " ".join(norm_tokens[i : i + window])

        if chunk == norm_anchor or norm_anchor in chunk:

            return words[i].start

        if anchor_words[0] in norm_tokens[i]:

            return words[i].start

    return None





def _proportional_starts(beats: list[VisualBeat], audio_duration: float) -> list[float]:

    weights = [max(len(b.phrase_anchor), 10) for b in beats]

    total = sum(weights) or 1

    starts = [0.0]

    acc = 0.0

    for w in weights[:-1]:

        acc += w / total * audio_duration

        starts.append(acc)

    return starts





def _extend_last_beat(

    entries: list[BeatTimelineEntry],

    audio_duration: float,

) -> list[BeatTimelineEntry]:

    if not entries:

        return entries

    last = entries[-1]

    if last.end_s >= audio_duration - 0.01:

        return entries

    entries[-1] = BeatTimelineEntry(

        beat=last.beat,

        start_s=last.start_s,

        end_s=audio_duration,

        image_path=last.image_path,

        on_screen_text=last.on_screen_text,

        text_layout=last.text_layout,

    )

    return entries





def _normalize(text: str) -> str:

    text = unicodedata.normalize("NFKD", text.lower())

    text = "".join(c for c in text if not unicodedata.combining(c))

    text = re.sub(r"[^\w\s]", " ", text)

    return re.sub(r"\s+", " ", text).strip()





def word_segments_from_json(raw: list[dict] | None) -> list[WordSegment]:

    if not raw:

        return []

    out: list[WordSegment] = []

    for item in raw:

        if not isinstance(item, dict):

            continue

        word = str(item.get("word", "")).strip()

        if not word:

            continue

        out.append(

            WordSegment(

                word=word,

                start=float(item.get("start", 0)),

                end=float(item.get("end", 0)),

            )

        )

    return out


