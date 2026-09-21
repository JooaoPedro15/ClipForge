import json
import os
import sys
from pathlib import Path
from typing import Any

import glossary_service
import llm_service
import llm_translation
import sentence_grouping
import srt_utils
import subtitle_validation
import translation_postprocess

# Motor de traducao pro chines:
#   "auto" -> LLM local (Ollama) se disponivel; senao erro claro (nao cai
#             silenciosamente no NLLB, que gera legenda ruim demais pra postar)
#   "llm"  -> exige o LLM
#   "nllb" -> forca o NLLB (fallback deliberado, ex.: sem GPU/Ollama)
# Idiomas que nao sao chines (ex.: ingles) sempre usam o NLLB.
# Sem valor explicito, vem da env CLIPFORGE_TRANSLATION_ENGINE (padrao "auto").
ENGINE_AUTO = "auto"
ENGINE_LLM = "llm"
ENGINE_NLLB = "nllb"
LLM_TARGET_LANGS = {"zh"}


def resolve_engine(engine: str | None) -> str:
    return engine or os.environ.get("CLIPFORGE_TRANSLATION_ENGINE", ENGINE_AUTO)


def _translate_with_nllb(
    cards: list[dict[str, Any]],
    translator: Any,
    source_lang: str,
    target_lang: str,
    channel_glossary: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Caminho NLLB: agrupa por segmento do Whisper, traduz cada grupo,
    pos-processa nome/genero por heuristica."""
    cards_text = [c["text"] for c in cards]
    video_glossary = glossary_service.build_video_glossary(
        cards_text, channel_glossary, translator, source_lang=source_lang, target_lang=target_lang
    )

    groups = sentence_grouping.group_cards_into_sentences(cards)
    group_texts = [g["text"] for g in groups]
    # Guarda explicita (em vez de deixar o early-return do proprio
    # translate_segments cuidar disso) pra nao registrar uma chamada no mock
    # dos testes quando nao ha nada pra traduzir.
    translated_texts = (
        translator.translate_segments(group_texts, source_lang=source_lang, target_lang=target_lang)
        if group_texts
        else []
    )

    for group, zh in zip(groups, translated_texts):
        zh = translation_postprocess.normalize_names(zh, video_glossary)
        zh = translation_postprocess.fix_gender_and_marriage_verb(zh, source_text=group["text"], glossary=video_glossary)
        group["zh"] = zh
        group["flag"] = translation_postprocess.confidence_flag(group.get("avg_logprob"))

    return groups, video_glossary


def _translate_with_llm(
    cards: list[dict[str, Any]],
    channel_glossary: dict[str, Any],
    video_type: str,
    client: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Caminho LLM: estagio 1 (glossario a partir da transcricao inteira) e
    estagio 2 (traducao por frase, agrupando cards)."""
    if not cards:
        return [], {"characters": [], "terms": []}
    sheet = glossary_service.build_video_glossary_llm(cards, channel_glossary, video_type, client)
    groups = llm_translation.translate_with_llm(cards, sheet, client)
    return groups, sheet


def _resolve_llm_client(target_lang: str, engine: str, llm_client: Any) -> Any:
    """Devolve o cliente LLM a usar, ou None pra cair no NLLB. Levanta erro
    claro quando o chines foi pedido e o Ollama nao esta disponivel."""
    if target_lang not in LLM_TARGET_LANGS or engine == ENGINE_NLLB:
        return None
    client = llm_client or llm_service.create_default_client()
    if client.is_available():
        return client
    raise llm_service.LLMUnavailableError(
        f"Traducao pra '{target_lang}' precisa do LLM local, mas o Ollama nao respondeu em "
        f"{getattr(client, 'base_url', '?')} ou o modelo '{getattr(client, 'model', '?')}' nao foi baixado. "
        f"Rode `ollama serve` e `ollama pull {getattr(client, 'model', '?')}`, "
        f"ou force o NLLB com CLIPFORGE_TRANSLATION_ENGINE=nllb."
    )


def rejected_output_path(output_path: str) -> str:
    """Caminho do rascunho gravado quando a validacao reprova — nome
    inequivoco pra ninguem confundir com a legenda final."""
    output = Path(output_path)
    return str(output.with_name(f"{output.stem}.REJEITADO{output.suffix}"))


def traduzir_cards(
    cards: list[dict[str, Any]],
    translator: Any,
    source_lang: str,
    target_lang: str,
    output_path: str,
    channel_glossary_path: str = glossary_service.DEFAULT_CHANNEL_GLOSSARY_PATH,
    uppercase: bool = False,
    lowercase: bool = False,
    video_type: str = "",
    engine: str | None = None,
    llm_client: Any = None,
) -> str:
    """Recebe os cards JA CARREGADOS em memoria (chamado no mesmo processo que
    acabou de transcrever — sem round-trip por disco). `traduzir_video`
    (abaixo) e so um wrapper fino que le o cards.json e delega pra ca."""
    channel_glossary = glossary_service.load_channel_glossary(channel_glossary_path)

    client = _resolve_llm_client(target_lang, resolve_engine(engine), llm_client)
    if client is not None:
        groups, video_glossary = _translate_with_llm(cards, channel_glossary, video_type, client)
    else:
        groups, video_glossary = _translate_with_nllb(cards, translator, source_lang, target_lang, channel_glossary)

    # Aplicado so na exibicao final, depois da validacao — uppercase/lowercase
    # em chines e um no-op (CJK nao tem caixa), entao e seguro aplicar sempre,
    # igual o comportamento que o fluxo antigo ja tinha pro .srt traduzido.
    def _apply_case(text: str) -> str:
        if uppercase:
            return text.upper()
        if lowercase:
            return text.lower()
        return text

    entries = [
        (srt_utils.format_timestamp(g["start"]), srt_utils.format_timestamp(g["end"]), _apply_case(g["zh"]))
        for g in groups
    ]

    try:
        subtitle_validation.validate_translation_output(groups, cards, glossary=video_glossary, target_lang=target_lang)
    except subtitle_validation.ValidationError as error:
        # Falha visivel: nada de .srt final. O rascunho vai num arquivo com
        # nome explicito so pra dar pra inspecionar o que o modelo devolveu.
        rejected = rejected_output_path(output_path)
        srt_utils.write_srt(entries, rejected)
        print(f"[traducao] validacao reprovou, rascunho em {rejected}", file=sys.stderr, flush=True)
        raise subtitle_validation.ValidationError(f"{error}\nrascunho: {rejected}") from error

    glossary_service.merge_into_channel_glossary(video_glossary, channel_glossary_path)

    srt_utils.write_srt(entries, output_path)
    return output_path


def traduzir_video(
    cards_path: str,
    original_srt_path: str,
    translator: Any,
    source_lang: str,
    target_lang: str,
    channel_glossary_path: str = glossary_service.DEFAULT_CHANNEL_GLOSSARY_PATH,
    output_path: str | None = None,
    uppercase: bool = False,
    lowercase: bool = False,
    video_type: str = "",
    engine: str | None = None,
    llm_client: Any = None,
) -> str:
    """Usado pela queima: le os cards de um cards.json ja gravado em disco por
    uma transcricao ANTERIOR (processo Python diferente)."""
    cards = json.loads(Path(cards_path).read_text(encoding="utf-8"))
    output = output_path or str(Path(original_srt_path).with_suffix(f".{target_lang}.srt"))
    return traduzir_cards(
        cards,
        translator,
        source_lang,
        target_lang,
        output,
        channel_glossary_path,
        uppercase,
        lowercase,
        video_type,
        engine,
        llm_client,
    )
