"""Helpers de texto puros (sem Whisper, sem arquivo) usados por varios servicos."""

import re
import unicodedata

# Palavras que nao deveriam fechar uma legenda: puxam a proxima palavra junto.
WEAK_TRAILING_WORDS = {
    "que",
    "de",
    "do",
    "da",
    "pra",
    "para",
    "com",
    "em",
    "e",
    "o",
    "a",
    "um",
    "uma",
    "se",
    "me",
    "te",
}


# Converte segundos para o formato padrao do arquivo .srt. Conta em milissegundos
# inteiros: floor em float transformava 9.1s em 09,099.
def format_timestamp(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def remove_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def remove_punctuation(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text)


# Limpeza aplicada antes de exibir a legenda.
def clean_text(text: str, no_accents: bool = False, no_punctuation: bool = False) -> str:
    if no_punctuation:
        text = remove_punctuation(text)
    if no_accents:
        text = remove_accents(text)
    return re.sub(r"\s+", " ", text).strip()


# Normaliza uma palavra so pra comparar (fronteira de legenda, alinhamento), sem mudar o texto exibido.
def normalize_token(word: str) -> str:
    return remove_accents(remove_punctuation(word)).strip().lower()


# Quebra a fala em linhas de no maximo max_width caracteres.
def split_text_into_lines(text: str, max_width: int) -> str:
    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        if current_line and len(current_line) + 1 + len(word) > max_width:
            lines.append(current_line)
            current_line = word
        else:
            current_line = f"{current_line} {word}".strip()

    if current_line:
        lines.append(current_line)

    return "\n".join(lines)
