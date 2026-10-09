"""Modulo Cortes pela linha de comando (o Electron chama do mesmo jeito).

Subcomandos:
  analyze   le o bruto, acha as cenas e grava <bruto>.cortes.json
  xml       grava o XML do Premiere a partir da analise (--analysis) ou de trechos (--source + --ranges)
  evaluate  compara os cortes com uma sequencia montada a mao (gabarito)
"""

import argparse
import sys
from pathlib import Path

import subtitle_service
from cortes import evaluation, store
from cortes.media import SourceMedia, probe_source
from cortes.pipeline import AnalyzeOptions, analyze
from cortes.segmenter import Durations
from cortes.timebase import parse_clock, parse_ranges
from cortes.xmeml_template import load_template
from cortes.xmeml_writer import ClipSpec, write_xml
from events import emit


def report_progress(stage: str, message: str, progress: int) -> None:
    emit("status", "processing", stage, message, progress=progress)


def report_warning(message: str) -> None:
    emit("warning", "processing", "warning", message)


def cmd_xml(args: argparse.Namespace) -> int:
    template = load_template(args.template)
    if args.analysis:
        analysis = store.load(args.analysis)
        source = SourceMedia(**analysis.source)
        chosen = store.select_clips(analysis.clips, args.clips, args.top)
        clips = [ClipSpec(clip.start, clip.end, clip.title, clip.score) for clip in chosen]
        default_out = Path(args.analysis).with_suffix(".xml")
    elif args.source and args.ranges:
        source = probe_source(args.source)
        clips = [ClipSpec(start, end) for start, end in parse_ranges(args.ranges)]
        default_out = Path(args.source).with_suffix(".cortes.xml")
    else:
        raise ValueError("Use --analysis <bruto.cortes.json>, ou --source <bruto> com --ranges <inicio-fim,...>.")
    out = Path(args.out) if args.out else default_out
    write_xml(template, source, clips, out, f"{Path(source.path).stem} - Cortes")
    emit("done", "completed", "done", f"XML com {len(clips)} clipe(s) gravado.", outputPath=str(out), clips=len(clips))
    return 0


def analyze_options(args: argparse.Namespace) -> AnalyzeOptions:
    return AnalyzeOptions(
        start=parse_clock(args.start) if args.start else 0.0,
        end=parse_clock(args.end) if args.end else None,
        film_track=args.film_track - 1,
        mic_track=args.mic_track - 1,
        judge_model=None if args.judge == "none" else args.judge,
        durations=Durations(args.min, args.target, args.max),
        whisper_model=args.whisper_model,
        device="cpu" if args.cpu else "cuda",
        compute_type="int8" if args.cpu else "float16",
    )


def cmd_analyze(args: argparse.Namespace) -> int:
    analysis = analyze(args.source, analyze_options(args), report_progress, report_warning)
    emit(
        "done",
        "completed",
        "done",
        f"Analise pronta: {len(analysis.clips)} clipes.",
        outputPath=str(store.analysis_path(args.source)),
        clips=len(analysis.clips),
        timings=analysis.timings,
    )
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    analysis = store.load(args.analysis)
    start = parse_clock(args.from_time) if args.from_time else analysis.options["start"]
    end = parse_clock(args.to_time) if args.to_time else analysis.options["end"]
    reference = evaluation.reference_boundaries(args.reference, start, end)
    predicted = evaluation.predicted_boundaries([clip.start for clip in analysis.clips], start, end)
    print(evaluation.format_report(evaluation.compare(predicted, reference, args.tolerance)), flush=True)
    return 0


def add_duration_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--min", type=float, default=Durations.min_sec, help="Duracao minima do clipe (s)")
    parser.add_argument("--target", type=float, default=Durations.target_sec, help="Duracao alvo do clipe (s)")
    parser.add_argument("--max", type=float, default=Durations.max_sec, help="Duracao maxima do clipe (s)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ClipForge - Cortes")
    commands = parser.add_subparsers(dest="command", required=True)

    analyze_parser = commands.add_parser("analyze", help="Le o bruto e grava <bruto>.cortes.json")
    analyze_parser.add_argument("source", help="Bruto do react")
    analyze_parser.add_argument("--start", help="Comecar em (ex.: 2:24.44)")
    analyze_parser.add_argument("--end", help="Terminar em (ex.: 1:58:00)")
    analyze_parser.add_argument("--film-track", type=int, default=1, help="Faixa de audio do filme (1 = primeira)")
    analyze_parser.add_argument("--mic-track", type=int, default=2, help="Faixa de audio do mic")
    analyze_parser.add_argument("--judge", default="none", help="Modelo do LLM local (juiz e titulos) ou 'none'")
    add_duration_args(analyze_parser)
    analyze_parser.add_argument("--whisper-model", default=subtitle_service.DEFAULT_MODEL)
    analyze_parser.add_argument("--cpu", action="store_true")
    analyze_parser.set_defaults(handler=cmd_analyze)

    xml = commands.add_parser("xml", help="Gera o XML do Premiere com os clipes")
    xml.add_argument("--template", required=True, help="XML de molde exportado do Premiere")
    xml.add_argument("--analysis", help="<bruto>.cortes.json gerado pelo analyze")
    xml.add_argument("--clips", help="So estes clipes da analise, ex.: 1,3,5")
    xml.add_argument("--top", type=int, help="So os N clipes de maior nota")
    xml.add_argument("--source", help="Bruto do react (junto com --ranges)")
    xml.add_argument("--ranges", help="Trechos no bruto, ex.: 2:24.44-3:39.72,3:39.72-5:28.56")
    xml.add_argument("--out", help="Onde gravar (padrao: ao lado da analise ou do bruto)")
    xml.set_defaults(handler=cmd_xml)

    evaluate = commands.add_parser("evaluate", help="Compara os cortes com uma sequencia montada a mao")
    evaluate.add_argument("--reference", required=True, help="XML exportado da sequencia montada pelo usuario")
    evaluate.add_argument("--analysis", required=True, help="<bruto>.cortes.json")
    evaluate.add_argument("--from", dest="from_time", help="Avaliar a partir de (padrao: inicio da analise)")
    evaluate.add_argument("--to", dest="to_time", help="Avaliar ate (padrao: fim da analise)")
    evaluate.add_argument("--tolerance", type=float, default=10.0, help="Acerto se cair a ate N segundos")
    evaluate.set_defaults(handler=cmd_evaluate)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        emit("error", "error", "cancelled", "Processo interrompido.", error="Processo interrompido.")
        return 130
    except (ValueError, RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr, flush=True)
        emit("error", "error", "runtime", "Falha no modulo de cortes.", error=str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
