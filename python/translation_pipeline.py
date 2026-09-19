import json
from pathlib import Path
from typing import Any

import glossary_service
import sentence_grouping
import srt_utils
import subtitle_validation
import translation_postprocess


def traduzir_cards(
    cards: list[dict[str, Any]],
    translator: Any,
    source_lang: str,
    target_lang: str,
    output_path: str,
    channel_glossary_path: str = glossary_service.DEFAULT_CHANNEL_GLOSSARY_PATH,
    uppercase: bool = False,
    lowercase: bool = False,
) -> str:
    """Recebe os cards JA CARREGADOS em memoria (usado por uma task futura, que
    chama isso no mesmo processo que acabou de transcrever — sem round-trip por
    disco). `traduzir_video` (abaixo) e so um wrapper fino que le o cards.json e
    delega pra ca."""
    cards_text = [c["text"] for c in cards]

    channel_glossary = glossary_service.load_channel_glossary(channel_glossary_path)
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

    subtitle_validation.validate_translation_output(groups, cards, glossary=video_glossary, target_lang=target_lang)

    glossary_service.merge_into_channel_glossary(video_glossary, channel_glossary_path)

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
) -> str:
    """Usado pela queima: le os cards de um cards.json ja gravado em disco por
    uma transcricao ANTERIOR (processo Python diferente)."""
    cards = json.loads(Path(cards_path).read_text(encoding="utf-8"))
    output = output_path or str(Path(original_srt_path).with_suffix(f".{target_lang}.srt"))
    return traduzir_cards(
        cards, translator, source_lang, target_lang, output, channel_glossary_path, uppercase, lowercase
    )
