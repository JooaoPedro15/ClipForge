import json
import os
import re
from typing import Any
from urllib import error, request

# LLM local via Ollama (http://localhost:11434). Custo zero, offline, roda na
# GPU do proprio usuario. Modelo padrao: Qwen2.5 7B instruct — forte em
# chines e cabe em 8GB de VRAM quantizado (Q4_K_M ~4.7GB).
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b-instruct"
DEFAULT_TIMEOUT_SECONDS = 600
# Janela de contexto: a transcricao inteira + glossario + prompt precisa caber
# de uma vez. 8k tokens cobre folgado um corte vertical (~30-150 cards).
DEFAULT_NUM_CTX = 8192


class LLMUnavailableError(RuntimeError):
    """Servidor Ollama fora do ar ou modelo nao baixado."""


class LLMResponseError(RuntimeError):
    """Modelo respondeu, mas o conteudo nao e JSON utilizavel."""


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def parse_json_payload(text: str) -> Any:
    """Tolera cerca markdown e comentario em volta do JSON — mesmo com
    format=json o modelo as vezes escapa do formato."""
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Tenta o maior trecho entre o primeiro { ou [ e o ultimo } ou ].
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
    ends = [i for i in (cleaned.rfind("}"), cleaned.rfind("]")) if i != -1]
    if starts and ends:
        candidate = cleaned[min(starts) : max(ends) + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    raise LLMResponseError(f"Resposta do modelo nao e JSON valido: {text[:200]!r}")


class OllamaClient:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        num_ctx: int = DEFAULT_NUM_CTX,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.num_ctx = num_ctx

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data is not None else "GET",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as http_error:
            detail = http_error.read().decode("utf-8", errors="replace")
            raise LLMUnavailableError(
                f"Ollama respondeu HTTP {http_error.code} em {path}: {detail[:300]}"
            ) from http_error
        except (error.URLError, TimeoutError, ConnectionError, OSError) as net_error:
            raise LLMUnavailableError(
                f"Ollama inacessivel em {self.base_url} ({net_error}). "
                f"Inicie o servidor (`ollama serve`) e baixe o modelo (`ollama pull {self.model}`)."
            ) from net_error

    def is_available(self) -> bool:
        """True se o servidor responde E o modelo configurado ja foi baixado."""
        try:
            tags = self._request("/api/tags")
        except LLMUnavailableError:
            return False
        names = {m.get("name", "") for m in tags.get("models", [])}
        return self.model in names or f"{self.model}:latest" in names

    def chat_json(self, system: str, user: str) -> Any:
        """Uma rodada de chat, temperature 0, saida forcada em JSON."""
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        response = self._request("/api/chat", payload)
        content = response.get("message", {}).get("content", "")
        return parse_json_payload(content)


def create_default_client() -> OllamaClient:
    return OllamaClient(
        model=os.environ.get("CLIPFORGE_OLLAMA_MODEL", DEFAULT_MODEL),
        base_url=os.environ.get("CLIPFORGE_OLLAMA_URL", DEFAULT_BASE_URL),
    )
