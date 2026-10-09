"""Compara as fronteiras do app com as de uma sequencia montada pelo usuario (gabarito)."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from cortes.timebase import format_clock
from cortes.xmeml_template import TemplateError, read_rate


def reference_boundaries_from_root(root: ET.Element, start: float, end: float) -> list[float]:
    """Inicio no bruto de cada clipe do usuario, menos o primeiro. Pedacos de V1 grudados na linha
    do tempo sao o mesmo clipe (corte interno); um clipe novo comeca depois de um espaco."""
    sequence = root.find("sequence")
    if sequence is None:
        raise TemplateError("O gabarito nao tem sequencia.")
    rate = read_rate(sequence)
    v1 = sequence.find("media/video/track")
    if v1 is None:
        raise TemplateError("O gabarito nao tem trilha V1.")
    starts = []
    previous_end = None
    for item in sorted(v1.findall("clipitem"), key=lambda clip: int(clip.findtext("start", "0"))):
        if previous_end is None or int(item.findtext("start", "0")) != previous_end:
            starts.append(rate.to_seconds(int(item.findtext("in", "0"))))
        previous_end = int(item.findtext("end", "0"))
    return [round(t, 2) for t in starts[1:] if start < t < end]


def reference_boundaries(xml_path: str | Path, start: float, end: float) -> list[float]:
    return reference_boundaries_from_root(ET.parse(xml_path).getroot(), start, end)


def predicted_boundaries(clip_starts: list[float], start: float, end: float) -> list[float]:
    return [round(t, 2) for t in clip_starts[1:] if start < t < end]


@dataclass
class Report:
    reference: list[float]
    predicted: list[float]
    matches: list[tuple[float, float]]  # (gabarito, app)
    tolerance: float

    @property
    def precision(self) -> float:
        return len(self.matches) / len(self.predicted) if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return len(self.matches) / len(self.reference) if self.reference else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0

    @property
    def mean_error(self) -> float | None:
        if not self.matches:
            return None
        return round(sum(abs(app - ref) for ref, app in self.matches) / len(self.matches), 2)


def compare(predicted: list[float], reference: list[float], tolerance: float) -> Report:
    # Pareia do par mais proximo pro mais distante; cada fronteira entra em um par so.
    pairs = sorted((abs(p - r), r, p) for r in reference for p in predicted if abs(p - r) <= tolerance)
    used_reference: set[float] = set()
    used_predicted: set[float] = set()
    matches = []
    for _distance, ref, app in pairs:
        if ref in used_reference or app in used_predicted:
            continue
        used_reference.add(ref)
        used_predicted.add(app)
        matches.append((ref, app))
    return Report(reference, predicted, sorted(matches), tolerance)


def format_report(report: Report) -> str:
    mean = "-" if report.mean_error is None else f"{report.mean_error:.1f}s"
    lines = [
        f"Gabarito: {len(report.reference)} fronteiras | App: {len(report.predicted)} | "
        f"Acertos (+-{report.tolerance:g}s): {len(report.matches)}",
        f"Precisao {report.precision:.2f} | Revocacao {report.recall:.2f} | F1 {report.f1:.2f} | Erro medio {mean}",
    ]
    by_reference = dict(report.matches)
    for ref in report.reference:
        app = by_reference.get(ref)
        found = f"{format_clock(app)} ({app - ref:+.1f}s)" if app is not None else "sem corte perto"
        lines.append(f"  {format_clock(ref)} -> {found}")
    matched = {app for _ref, app in report.matches}
    extras = [app for app in report.predicted if app not in matched]
    if extras:
        lines.append("  Cortes do app sem par no gabarito: " + ", ".join(format_clock(app) for app in extras))
    return "\n".join(lines)
