from typing import Any


class ValidationError(Exception):
    """Levantado quando a saida da traducao nao passa nas checagens. A
    mensagem sempre nomeia o grupo e a regra — nunca falha silenciosa."""


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

    for group in groups:
        zh = group["zh"]
        grupo_ref = group["cards"]

        # So faz sentido pra idioma alvo que NAO usa alfabeto latino (o caso
        # real e chines — pega nome esquecido sem traduzir). Pra "en" isso
        # sempre dispararia, ja que ingles E letra latina.
        if target_lang == "zh" and any("a" <= ch.lower() <= "z" for ch in zh):
            erros.append(f"grupo {grupo_ref}: caractere latino em '{zh}'")

        if len(zh) > max_chars:
            erros.append(f"grupo {grupo_ref}: {len(zh)} chars (max {max_chars}) '{zh}'")

        duration = group["end"] - group["start"]
        if duration < min_duration:
            erros.append(f"grupo {grupo_ref}: {duration:.2f}s na tela (min {min_duration}s)")

        if group.get("flag"):
            erros.append(f"grupo {grupo_ref}: FLAG -> {group['flag']}")

    texto_completo = "".join(g["zh"] for g in groups)
    for character in glossary.get("characters", []):
        canonical = character["zh"]
        for variant in character.get("variants", []):
            if variant and variant != canonical and variant in texto_completo:
                erros.append(
                    f"nome '{character['source_name']}': grafia '{variant}' divergente da canonica '{canonical}'"
                )

    if erros:
        raise ValidationError("\n".join(erros))
