import hashlib
import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from shutil import which

WINDOWS_PATH_WARN_CHARS = 240


def _resolve_binary(name: str, windows_name: str) -> str:
    found = which(name) or which(windows_name)
    if found:
        return found

    candidates = [
        Path("C:/ffmpeg/bin") / windows_name,
        Path("C:/tools/ffmpeg/bin") / windows_name,
        Path(os.environ.get("PROGRAMFILES", "")) / "ffmpeg" / "bin" / windows_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError(
        f"{name} nao encontrado no PATH nem em pastas conhecidas do Windows. "
        "Instale o ffmpeg e adicione ao PATH, ou coloque em C:\\ffmpeg\\bin."
    )


def resolve_ffmpeg_path() -> str:
    return _resolve_binary("ffmpeg", "ffmpeg.exe")


def resolve_ffprobe_path() -> str:
    return _resolve_binary("ffprobe", "ffprobe.exe")


@dataclass
class VideoInfo:
    duration_sec: float
    width: int
    height: int


def probe_video(path: str) -> VideoInfo:
    ffprobe = resolve_ffprobe_path()
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffprobe falhou para {path}: {result.stderr.strip()}")

    data = json.loads(result.stdout)
    stream = data["streams"][0]
    duration = float(data["format"]["duration"])

    return VideoInfo(duration_sec=duration, width=int(stream["width"]), height=int(stream["height"]))


def escape_path_for_subtitles_filter(path: str) -> str:
    # No Windows, o filtro subtitles= do ffmpeg trata ":" como separador de opcoes.
    # Converter backslash pra forward slash (ffmpeg aceita nativamente) e escapar
    # so o ":" da unidade (ex.: "C:") evita a maior parte dos problemas de parsing.
    normalized = path.replace("\\", "/")
    return normalized.replace(":", "\\:")


def escape_force_style_value(value: str) -> str:
    # O valor de force_style='...' e delimitado por aspas simples dentro do filtro.
    # Aspas simples, ":" (separador de opcao do filtro) e "," (separador entre filtros
    # encadeados) dentro do valor precisam ser escapados pra nao quebrar o parsing do
    # ffmpeg. Hoje o valor e sempre montado so com constantes numericas conhecidas
    # (fontsize/margin), mas a funcao existe pra cobrir qualquer valor textual futuro
    # (ex.: nome de fonte customizado) sem precisar revisitar o parsing do filtro.
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    escaped = escaped.replace(":", "\\:")
    return escaped


def assert_safe_path_length(path: str, label: str) -> None:
    if len(path) > WINDOWS_PATH_WARN_CHARS:
        raise RuntimeError(
            f"Caminho de {label} muito longo para Windows ({len(path)} chars, limite seguro "
            f"~{WINDOWS_PATH_WARN_CHARS}): {path}\n"
            "Mova o arquivo pra uma pasta mais curta e tente novamente."
        )


def resolve_short_temp_dir(reference_path: Path) -> Path:
    # Espelha a mesma estrategia ja usada em python/clip_splitter_service.py (projeto
    # externo) pra esse exato problema, mas self-contained aqui, sem importar de la.
    env_dir = os.environ.get("CLIPFORGE_TEMP")
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir))
    if sys.platform == "win32":
        drive = reference_path.drive or "C:"
        candidates.append(Path(f"{drive}\\cs_tmp"))
        candidates.append(Path("C:\\cs_tmp"))
    else:
        candidates.append(Path("/tmp/cs_tmp"))
    candidates.append(reference_path.parent)

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue

    return reference_path.parent


def ensure_short_srt_path(srt_path: str) -> str:
    # O caminho do .srt entra dentro do filtro subtitles=..., que e o ponto mais
    # sensivel ao limite de 260 chars do Windows (o filtro adiciona escaping por cima
    # do caminho). Se o caminho original ja e curto o bastante, devolve sem mudanca;
    # senao copia o arquivo pra uma pasta curta e devolve o novo caminho.
    if len(srt_path) <= WINDOWS_PATH_WARN_CHARS:
        return srt_path

    source = Path(srt_path)
    short_dir = resolve_short_temp_dir(source)
    short_dir.mkdir(parents=True, exist_ok=True)
    short_name = hashlib.sha1(srt_path.encode("utf-8")).hexdigest()[:12] + source.suffix
    short_path = short_dir / short_name
    short_path.write_bytes(source.read_bytes())

    return str(short_path)


def _drain_stderr(stderr: "subprocess.Popen[str].stderr", collected: list[str]) -> None:
    # Le stderr continuamente numa thread separada. O ffmpeg escreve bastante log
    # (banner do codec, resumo final do libx264) mesmo com -nostats — se ninguem
    # ler esse pipe em paralelo, o buffer do SO enche e o processo trava esperando
    # espaco pra escrever, enquanto o thread principal fica esperando progresso no
    # stdout que nunca chega (deadlock classico de subprocess com PIPE duplo).
    for line in stderr:
        collected.append(line)
        if len(collected) > 500:
            collected.pop(0)


def run_ffmpeg_with_progress(
    args: list[str],
    total_duration_sec: float,
    on_progress: Callable[[int], None],
) -> None:
    full_args = [*args[:1], "-progress", "pipe:1", "-nostats", *args[1:]] if args else args
    process = subprocess.Popen(
        full_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stderr_lines: list[str] = []
    stderr_thread = threading.Thread(target=_drain_stderr, args=(process.stderr, stderr_lines), daemon=True)
    stderr_thread.start()

    last_percent = 0
    for line in process.stdout:
        line = line.strip()
        if line.startswith("out_time_ms="):
            try:
                out_time_ms = int(line.split("=", 1)[1])
            except ValueError:
                continue
            if total_duration_sec > 0:
                percent = min(99, int((out_time_ms / 1_000_000) / total_duration_sec * 100))
                if percent > last_percent:
                    last_percent = percent
                    on_progress(percent)
        elif line == "progress=end":
            on_progress(100)

    return_code = process.wait()
    stderr_thread.join(timeout=5)

    if return_code != 0:
        stderr_output = "".join(stderr_lines)
        raise RuntimeError(f"ffmpeg terminou com codigo {return_code}: {stderr_output.strip()[-2000:]}")
