import re
from typing import Any


class ValidationError(Exception):
    """Levantado quando a saida da traducao nao passa nas checagens. A
    mensagem sempre nomeia o grupo e a regra — nunca falha silenciosa."""


_SHE = "她"
_HE = "他"
# Pronomes femininos/masculinos em portugues: se a fonte usa "ela", 她 e
# legitimo mesmo sem nome de mulher no grupo (e vice-versa).
_PT_FEMALE_PRONOUN = re.compile(r"\b(ela|dela|nela)\b", re.IGNORECASE)
_PT_MALE_PRONOUN = re.compile(r"\b(ele|dele|nele)\b", re.IGNORECASE)
# Sufixos tipicos de transliteracao: canonico + um desses = provavel grafia
# alternativa do mesmo nome (埃德加 -> 埃德加尔).
_TRANSLIT_SUFFIXES = "尔多德斯拉娜诺罗托索莫雷"


def _mentions_name(name: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) is not None


def _characters_in(source_text: str, glossary: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for character in glossary.get("characters", []):
        names = [character.get("source_name", ""), *character.get("variants", [])]
        if any(n and _mentions_name(n, source_text) for n in names):
            found.append(character)
    return found


def _gender_errors(group: dict[str, Any], glossary: dict[str, Any], source: str) -> list[str]:
    """Erro 3 da auditoria: 她 pra sujeito masculino ("o Bernardo morre" ->
    她死了). So acusa quando a fonte NAO da nenhuma pista feminina: nenhum
    personagem feminino mencionado e nenhum "ela". Simetrico pro 他."""
    zh = group["zh"]
    if not source:
        return []
    mentioned = _characters_in(source, glossary)
    males = [c for c in mentioned if c.get("gender") == "male"]
    females = [c for c in mentioned if c.get("gender") == "female"]
    erros = []
    if _SHE in zh and males and not females and not _PT_FEMALE_PRONOUN.search(source):
        names = ", ".join(c["source_name"] for c in males)
        erros.append(f"grupo {group['cards']}: 她 com sujeito masculino ({names}) em '{zh}' | fonte: '{source}'")
    if _HE in zh and females and not males and not _PT_MALE_PRONOUN.search(source):
        names = ", ".join(c["source_name"] for c in females)
        erros.append(f"grupo {group['cards']}: 他 com sujeito feminino ({names}) em '{zh}' | fonte: '{source}'")
    return erros


def _marriage_errors(group: dict[str, Any], glossary: dict[str, Any]) -> list[str]:
    """Erro 4 da auditoria: 嫁给 e "mulher casa com homem"; 娶 e "homem casa
    com mulher". Olha quem esta IMEDIATAMENTE antes do verbo: 他 ou nome
    masculino antes de 嫁给 (ou 她 / nome feminino antes de 娶) esta errado."""
    zh = group["zh"]
    male_names = [c["zh"] for c in glossary.get("characters", []) if c.get("gender") == "male" and c.get("zh")]
    female_names = [c["zh"] for c in glossary.get("characters", []) if c.get("gender") == "female" and c.get("zh")]
    erros = []
    for verb, wrong_pronoun, wrong_names, hint in (
        ("嫁给", _HE, male_names, "sujeito masculino nao usa 嫁给 (use 娶 ou 和…结婚)"),
        ("娶", _SHE, female_names, "sujeito feminino nao usa 娶 (use 嫁给 ou 和…结婚)"),
    ):
        for match in re.finditer(re.escape(verb), zh):
            before = zh[: match.start()]
            # Ignora palavras "de ligacao" entre sujeito e verbo (试图, 想, 要, 了...).
            before = re.sub(r"(试图|想要|想|要|会|去|已经|又|再|就|也|都)+$", "", before)
            subject_is_wrong = before.endswith(wrong_pronoun) or any(before.endswith(n) for n in wrong_names)
            if subject_is_wrong:
                erros.append(f"grupo {group['cards']}: {hint} em '{zh}'")
                break
    return erros


def _name_spelling_errors(groups: list[dict[str, Any]], glossary: dict[str, Any]) -> list[str]:
    """Erro 5 da auditoria: mesmo personagem com duas grafias. Alem das
    variantes listadas no glossario, pega dois padroes sem lista nenhuma:
    canonico + sufixo de transliteracao (埃德加尔) e canonico com o ultimo
    caractere trocado (伯纳德 vs 伯纳多)."""
    erros = []
    for character in glossary.get("characters", []):
        canonical = character.get("zh", "")
        if not canonical:
            continue
        suspects: set[str] = {v for v in character.get("variants", []) if v and v != canonical}
        for group in groups:
            zh = group["zh"]
            found = {v for v in suspects if v in zh}
            for match in re.finditer(re.escape(canonical), zh):
                nxt = zh[match.end() : match.end() + 1]
                if nxt and nxt in _TRANSLIT_SUFFIXES:
                    found.add(canonical + nxt)
            if len(canonical) >= 3:
                stem = canonical[:-1]
                for match in re.finditer(re.escape(stem), zh):
                    nxt = zh[match.end() : match.end() + 1]
                    if nxt and nxt != canonical[-1] and nxt in _TRANSLIT_SUFFIXES:
                        found.add(stem + nxt)
            for variant in sorted(found):
                erros.append(
                    f"grupo {group['cards']}: nome '{character.get('source_name', '?')}' com grafia '{variant}' "
                    f"divergente da canonica '{canonical}' em '{zh}'"
                )
    return erros


def validate_translation_output(
    groups: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    glossary: dict[str, Any],
    target_lang: str,
    max_chars: int = 20,
    min_duration: float = 1.2,
) -> None:
    erros: list[str] = []

    vistos = [i for g in groups for i in g["cards"]]
    esperados = [c["i"] for c in cards]
    if sorted(vistos) != sorted(esperados):
        faltando = sorted(set(esperados) - set(vistos))
        repetidos = sorted({i for i in vistos if vistos.count(i) > 1})
        erros.append(f"cobertura quebrada | faltando={faltando} repetidos={repetidos}")
    elif vistos != sorted(vistos):
        erros.append("grupos fora de ordem")

    is_chinese = target_lang == "zh"
    text_by_index = {c["i"]: c.get("text", "") for c in cards}

    for group in groups:
        zh = group["zh"]
        grupo_ref = group["cards"]

        # So faz sentido pra idioma alvo que NAO usa alfabeto latino (o caso
        # real e chines — pega nome esquecido sem traduzir). Pra "en" isso
        # sempre dispararia, ja que ingles E letra latina.
        if is_chinese and any("a" <= ch.lower() <= "z" for ch in zh):
            erros.append(f"grupo {grupo_ref}: caractere latino em '{zh}'")

        # Mesma logica do caractere latino acima: o teto de caracteres modela
        # "cabe numa linha de video vertical" pro chines (hanzi denso, poucos
        # caracteres por frase). Ingles/portugues precisam de bem mais
        # caracteres pra dizer a mesma coisa — aplicar o mesmo teto rejeitaria
        # quase toda traducao pro ingles (ex.: modo "Chines + ingles" na
        # queima, que falharia inteiro por causa da perna em ingles).
        if is_chinese and len(zh) > max_chars:
            erros.append(f"grupo {grupo_ref}: {len(zh)} chars (max {max_chars}) '{zh}'")

        duration = group["end"] - group["start"]
        if duration < min_duration:
            erros.append(f"grupo {grupo_ref}: {duration:.2f}s na tela (min {min_duration}s)")

        if group.get("flag"):
            erros.append(f"grupo {grupo_ref}: FLAG -> {group['flag']}")

        if is_chinese:
            source = group.get("text") or " ".join(text_by_index.get(i, "") for i in grupo_ref)
            erros.extend(_gender_errors(group, glossary, source))
            erros.extend(_marriage_errors(group, glossary))

    if is_chinese:
        erros.extend(_name_spelling_errors(groups, glossary))

    if erros:
        raise ValidationError("\n".join(erros))
