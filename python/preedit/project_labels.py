"""Gabarito de cada gravacao a partir das sequencias do projeto: o que ficou e onde teve zoom.

O que saiu nao e guardado: e o que fica dentro do `span` sem estar em `kept`.
"""

from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from premiere_project import ClipEdit, SequenceEdit

from preedit.types import Range, RecordingLabels, Zoom

# Escala pelo menos 5% acima da normal da trilha conta como zoom.
ZOOM_MIN_RATIO = 1.05
# Clipe acelerado/desacelerado nao diz quanto da gravacao ficou: e ignorado. A folga minima cobre o
# quadro a mais que o Premiere grava em clipe curto (os zooms de corte tem 0,2-1,4 s).
SPEED_TOLERANCE = 0.02
FRAME_TOLERANCE_SEC = 0.05
MERGE_GAP = 0.05
# No video final, fonte com pelo menos 10% do trecho na trilha principal e a gravacao (b-roll e meme ficam de fora).
MAIN_SOURCE_SHARE = 0.1


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
    return timeline > 0 and abs(source - timeline) <= max(FRAME_TOLERANCE_SEC, SPEED_TOLERANCE * timeline)


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
    return collect_labels(sequences)[0]


# Gabarito por gravacao e o que ficou de fora (com o motivo). So ensina a gravacao da trilha principal
# (b-roll e capturas em outras trilhas nao sao a edicao do usuario) e so ocorrencias com corte: a gravacao
# inteira jogada numa sequencia ensinaria "mantem tudo" e, unida a edicao de verdade, apagaria os cortes.
def collect_labels(sequences: list[SequenceEdit]) -> tuple[list[RecordingLabels], list[dict]]:
    occurrences: dict[tuple[str, str], list[tuple[str, list[Range], set[Zoom]]]] = defaultdict(list)
    main_sources: set[str] = set()
    other_sources: set[str] = set()
    for sequence in sequences:
        clips = [clip for clip in sequence.clips if _speed_ok(clip)]
        if not clips:
            continue
        fmt = "short" if sequence.vertical else "longo"
        track = zoom_track(clips)
        on_main = {clip.source for clip in clips if clip.track == track}
        main_sources |= on_main
        other_sources |= {clip.source for clip in clips} - on_main
        for source in on_main:
            ranges = merge_ranges([Range(clip.source_in, clip.source_out) for clip in clips if clip.source == source])
            track_clips = [clip for clip in clips if clip.track == track and clip.source == source]
            baseline = baseline_scale(track_clips)
            zooms = {
                Zoom(round(clip.source_in, 2), round(clip.source_out, 2), round(_ratio(clip, baseline), 3))
                for clip in track_clips
                if _ratio(clip, baseline) >= ZOOM_MIN_RATIO
            }
            occurrences[(source, fmt)].append((sequence.name, ranges, zooms))

    labels: list[RecordingLabels] = []
    ignored = [{"recording": source, "reason": "fora da trilha principal (b-roll)"} for source in sorted(other_sources - main_sources)]
    for (source, fmt), items in sorted(occurrences.items()):
        with_cuts = [item for item in items if len(item[1]) > 1]
        if not with_cuts:
            ignored.append({"recording": source, "reason": "sem cortes (gravacao inteira na sequencia)"})
            continue
        labels.append(
            RecordingLabels(
                recording=source,
                format=fmt,
                kept=merge_ranges([piece for _, ranges, _ in with_cuts for piece in ranges]),
                zooms=sorted({zoom for _, _, zooms in with_cuts for zoom in zooms}, key=lambda zoom: zoom.start),
                preedited="_preedit" in Path(source).stem.lower(),
                sequences=sorted({name for name, _, _ in with_cuts}),
            )
        )
    return labels, ignored


# Escala normal pelo tempo: num Short curto cheio de zoom de corte (clipes de 0,2-1,4 s, as vezes partidos
# em dois) os clipes com zoom podem ser maioria em numero, mas o tempo na escala normal e bem maior.
def _time_baseline(clips: list[ClipEdit]) -> float:
    seconds: Counter[float] = Counter()
    for clip in clips:
        if clip.scale:
            seconds[round(clip.scale, 1)] += clip.end - clip.start
    return float(seconds.most_common(1)[0][0]) if seconds else 100.0


# Gabarito do trecho que a sequencia exportou (mp4 final, sem o bruto): os zooms em segundos do mp4.
# Sem zoom nao ensina nada (so faria o modelo achar que quase nunca tem zoom).
def final_labels(sequence: SequenceEdit, video: str, start: float = 0.0, end: float | None = None) -> RecordingLabels | None:
    end = sequence.duration if end is None else end
    length = end - start
    # Clipes que tocam o trecho, cortados nele e ja no tempo do mp4.
    clips = [
        replace(clip, start=max(clip.start, start) - start, end=min(clip.end, end) - start)
        for clip in sequence.clips
        if min(clip.end, end) > max(clip.start, start)
    ]
    if not clips or length <= 0:
        return None
    track = zoom_track(clips)
    on_track = [clip for clip in clips if clip.track == track]
    seconds: dict[str, float] = defaultdict(float)
    for clip in on_track:
        seconds[clip.source] += clip.end - clip.start
    zooms: list[Zoom] = []
    for source, total in seconds.items():
        if total < MAIN_SOURCE_SHARE * length:
            continue
        source_clips = [clip for clip in on_track if clip.source == source]
        baseline = _time_baseline(source_clips)
        zooms += [
            Zoom(round(clip.start, 2), round(clip.end, 2), round(_ratio(clip, baseline), 3))
            for clip in source_clips
            if _ratio(clip, baseline) >= ZOOM_MIN_RATIO
        ]
    if not zooms:
        return None
    return RecordingLabels(
        recording=video,
        format="short" if sequence.vertical else "longo",
        kept=[Range(0.0, round(length, 3))],
        zooms=sorted(zooms, key=lambda zoom: zoom.start),
        sequences=[sequence.name],
        final=True,
    )
