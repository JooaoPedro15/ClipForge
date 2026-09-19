import os
from pathlib import Path
from typing import Any

# Repositorio HuggingFace original (formato transformers) usado como fonte pra conversao
# ctranslate2 local. Nao baixamos um .bin ja convertido de terceiros porque mirrors da
# comunidade (ex.: michaelfeil/ct2fast-nllb-200-distilled-600M, removido do HF; e
# JustFrederik/nllb-200-distilled-600M-ct2, que gera traducao degenerada por tokenizer
# incompativel com o model.bin) sao instaveis. Converter localmente garante que o
# sentencepiece.bpe.model bate exatamente com os pesos do model.bin.
SOURCE_MODEL_REPO = "facebook/nllb-200-distilled-600M"

# sentencepiece (biblioteca C++) nao le corretamente caminhos do Windows com acentos
# (ex.: "C:\Users\Jo\xe3o\..."), o que inclui o cache padrao do huggingface_hub sob o
# perfil do usuario. Por isso o modelo convertido mora num diretorio ASCII-only fixo,
# dentro de D:\Projetos\subtitle-forge (raiz ja usada pelo runner) em vez de C:\ — pastas
# soltas em C:\ fora de D:\Projetos nao sobrevivem entre sessoes neste ambiente.
DEFAULT_MODEL_DIR = "D:\\Projetos\\subtitle-forge\\models\\nllb-200-distilled-600M-ct2"

CONVERT_COMMAND = (
    "ct2-transformers-converter --model facebook/nllb-200-distilled-600M "
    f"--output_dir {DEFAULT_MODEL_DIR} --quantization int8 --copy_files sentencepiece.bpe.model"
)

# Mapeia codigos curtos usados na UI/whisper para o codigo FLORES-200 esperado pelo NLLB.
LANGUAGE_TO_FLORES = {
    "pt": "por_Latn",
    "en": "eng_Latn",
    "zh": "zho_Hans",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "it": "ita_Latn",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "ru": "rus_Cyrl",
}


def resolve_model_dir() -> str:
    return os.environ.get("CLIPFORGE_NLLB_MODEL_DIR", DEFAULT_MODEL_DIR)


def resolve_flores_code(language: str) -> str:
    code = LANGUAGE_TO_FLORES.get(language.lower())
    if not code:
        raise ValueError(f"Idioma sem mapeamento FLORES-200 conhecido: {language}")
    return code


class Translator:
    """Traduz lotes de texto via NLLB-200 (ctranslate2). Carregamento do modelo e lazy."""

    def __init__(self, device: str = "cuda", compute_type: str = "default"):
        self._device = device
        self._compute_type = compute_type
        self._translator: Any = None
        self._tokenizer: Any = None

    def _ensure_loaded(self) -> None:
        if self._translator is not None:
            return

        import ctranslate2
        import sentencepiece as spm

        model_dir = Path(resolve_model_dir())
        if not (model_dir / "model.bin").exists():
            raise FileNotFoundError(
                f"Modelo NLLB ctranslate2 nao encontrado em {model_dir}. "
                f"Rode uma vez: {CONVERT_COMMAND}"
            )

        self._translator = ctranslate2.Translator(
            str(model_dir),
            device=self._device,
            compute_type=self._compute_type,
        )
        self._tokenizer = spm.SentencePieceProcessor()
        self._tokenizer.load(str(model_dir / "sentencepiece.bpe.model"))

    def translate_segments(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]:
        if not texts:
            return []

        source_code = resolve_flores_code(source_lang)
        target_code = resolve_flores_code(target_lang)

        self._ensure_loaded()

        # Formato NLLB: fonte = [lingua_origem, ...tokens, </s>]; o decoder comeca em
        # </s> (decoder_start_token) seguido do codigo da lingua alvo (forced_bos).
        source_tokens = [
            [source_code, *self._tokenizer.encode(text, out_type=str), "</s>"] for text in texts
        ]
        target_prefix = [["</s>", target_code] for _ in texts]

        results = self._translator.translate_batch(source_tokens, target_prefix=target_prefix)

        translated: list[str] = []
        for result in results:
            tokens = result.hypotheses[0][2:]  # remove </s> e o token de idioma alvo
            translated.append(self._tokenizer.decode(tokens).strip())

        return translated
