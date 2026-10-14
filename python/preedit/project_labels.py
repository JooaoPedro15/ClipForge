"""Gabarito de cada gravacao a partir das sequencias do projeto: o que ficou e onde teve zoom.

O que saiu nao e guardado: e o que fica dentro do `span` sem estar em `kept`.
"""

from collections import Counter, defaultdict
from pathlib import Path

from premiere_project import ClipEdit, SequenceEdit

from preedit.types import Range, RecordingLabels, Zoom

# Escala pelo menos 5% acima da normal da trilha conta como zoom.
ZOOM_MIN_RATIO = 1.05
# Clipe acelerado/desacelerado nao diz quanto da gravacao ficou: e ignorado.
SPEED_TOLERANCE = 0.02
MERGE_GAP = 0.05


def merge_ranges(ranges: list[Range], gap: float = MERGE_GAP) -> list[Range]:
    merged: list[Range] = []
    for item in sorted(ranges, key=lambda current: current.start):
        if merged and item.start <= merged[-1].end + gap:
            merged[-1] = Range(merged[-1].start, max(merged[-1].end, item.end))
        else:
            merged.append(item)
    return merged


def _speed_ok(clip: ClipEdit) -> bool:
    timeline = clip.end - clip.start
    source = clip.source_out - clip.source_in
    return timeline > 0 and abs(source / timeline - 1.0) <= SPEED_TOLERANCE


def baseline_scale(clips: list[ClipEdit]) -> float:
    scales = Counter(round(clip.scale, 1) for clip in clips if clip.scale)
    return float(scales.most_common(1)[0][0]) if scales else 100.0


def _ratio(clip: ClipEdit, baseline: float) -> float:
    return (clip.scale or baseline) / baseline if baseline else 1.0


def _zoom_count(clips: list[ClipEdit]) -> int:
    baseline = baseline_scale(clips)
    return sum(1 for clip in clips if _ratio(clip, baseline) >= ZOOM_MIN_RATIO)


# Trilha do zoom: entre as trilhas com pelo menos metade dos clipes da maior, a com mais zooms
# (no Short a mesma gravacao vem em duas trilhas e so a de baixo tem zoom). Empate: mais clipes, depois V1.
def zoom_track(clips: list[ClipEdit]) -> int:
    by_track: dict[int, list[ClipEdit]] = defaultdict(list)
    for clip in clips:
        by_track[clip.track].append(clip)
    largest = max(len(items) for items in by_track.values())
    eligible = {track: items for track, items in by_track.items() if len(items) >= largest / 2}
    return max(eligible, key=lambda track: (_zoom_count(eligible[track]), len(eligible[track]), -track))


def labels_from_sequences(sequences: list[SequenceEdit]) -> list[RecordingLabels]:
    kept: dict[tuple[str, str], list[Range]] = defaultdict(list)
    zooms: dict[tuple[str, str], set[Zoom]] = defaultdict(set)
    names: dict[tuple[str, str], set[str]] = defaultdict(set)
    for sequence in sequences:
        clips = [clip for clip in sequence.clips if _speed_ok(clip)]
        if not clips:
            continue
        fmt = "short" if sequence.vertical else "longo"
        for clip in clips:
            key = (clip.source, fmt)
            kept[key].append(Range(clip.source_in, clip.source_out))
            names[key].add(sequence.name)
        track = zoom_track(clips)
        track_clips = [clip for clip in clips if clip.track == track]
        baseline = baseline_scale(track_clips)
        for clip in track_clips:
            ratio = _ratio(clip, baseline)
            if ratio >= ZOOM_MIN_RATIO:
                zooms[(clip.source, fmt)].add(Zoom(round(clip.source_in, 2), round(clip.source_out, 2), round(ratio, 3)))

    labels = [
        RecordingLabels(
            recording=source,
            format=fmt,
            kept=merge_ranges(ranges),
            zooms=sorted(zooms[(source, fmt)], key=lambda zoom: zoom.start),
            preedited="_preedit" in Path(source).stem.lower(),
            sequences=sorted(names[(source, fmt)]),
        )
        for (source, fmt), ranges in kept.items()
    ]
    return sorted(labels, key=lambda item: (item.recording, item.format))
