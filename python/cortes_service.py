"""Modulo Cortes pela linha de comando (o Electron chama do mesmo jeito).

Subcomandos:
  xml   grava o XML do Premiere a partir de trechos do bruto (--source + --ranges)
"""

import argparse
import sys
from pathlib import Path

from cortes.media import probe_source
from cortes.timebase import parse_ranges
from cortes.xmeml_template import load_template
from cortes.xmeml_writer import ClipSpec, write_xml
from events import emit


def cmd_xml(args: argparse.Namespace) -> int:
    template = load_template(args.template)
    if not (args.source and args.ranges):
        raise ValueError("Informe --source <bruto> e --ranges <inicio-fim,...>.")
    source = probe_source(args.source)
    clips = [ClipSpec(start, end) for start, end in parse_ranges(args.ranges)]
    out = Path(args.out) if args.out else Path(args.source).with_suffix(".cortes.xml")
    write_xml(template, source, clips, out, f"{Path(source.path).stem} - Cortes")
    emit("done", "completed", "done", f"XML com {len(clips)} clipe(s) gravado.", outputPath=str(out), clips=len(clips))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ClipForge - Cortes")
    commands = parser.add_subparsers(dest="command", required=True)

    xml = commands.add_parser("xml", help="Gera o XML do Premiere com os clipes")
    xml.add_argument("--template", required=True, help="XML de molde exportado do Premiere")
    xml.add_argument("--source", help="Bruto do react (junto com --ranges)")
    xml.add_argument("--ranges", help="Trechos no bruto, ex.: 2:24.44-3:39.72,3:39.72-5:28.56")
    xml.add_argument("--out", help="Onde gravar (padrao: <bruto>.cortes.xml)")
    xml.set_defaults(handler=cmd_xml)

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
