"""Cliente mínimo da API HTTP do Ollama.

Uso o HTTP direto (httpx) em vez da biblioteca `ollama` para ter controle
total do que vai e volta: tudo isso entra no rastro de auditoria.
"""

from __future__ import annotations

import base64
import io
import math
from typing import Protocol

import httpx


class OllamaIndisponivel(RuntimeError):
    """O notebook do LLM está desligado ou fora da rede."""


class Embedder(Protocol):
    nome: str

    def embed(self, textos: list[str]) -> list[list[float]]: ...


class RespostaLLM(dict):
    """Resposta do chat: {"conteudo": str, "modelo": str, "metricas": {...}}."""


class LLM(Protocol):
    def chat(
        self,
        modelo: str,
        mensagens: list[dict],
        formato: dict | None = None,
        opcoes: dict | None = None,
        pensar: bool | None = None,
        ferramentas: list[dict] | None = None,
    ) -> RespostaLLM: ...


class RespostaInvalida(RuntimeError):
    """O modelo devolveu algo que não é o JSON pedido."""


def normalizar(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class ClienteOllama:
    def __init__(self, url: str, timeout_s: float = 900, manter_carregado: str | None = None) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout_s
        # keep_alive do Ollama: evita descarregar e recarregar o modelo entre perguntas.
        self.manter_carregado = manter_carregado

    def _post(self, caminho: str, corpo: dict) -> dict:
        try:
            r = httpx.post(f"{self.url}{caminho}", json=corpo, timeout=self.timeout)
        except httpx.TransportError as e:
            raise OllamaIndisponivel(f"Ollama inacessível em {self.url}: {e}") from e
        # Erro do próprio Ollama (404: modelo não baixado; 500: faltou memória)
        # é tratado como indisponibilidade, para quem chama degradar com aviso
        # em vez de cair. O corpo traz o motivo (ex.: "model 'x' not found").
        if r.status_code >= 400:
            motivo = r.text.strip()[:300]
            dica = f" Rode: ollama pull {corpo['model']}" if r.status_code == 404 and corpo.get("model") else ""
            raise OllamaIndisponivel(f"Ollama em {self.url} respondeu {r.status_code}: {motivo}.{dica}")
        try:
            return r.json()
        except ValueError as e:
            raise OllamaIndisponivel(f"Ollama em {self.url} devolveu uma resposta que não é JSON: {e}") from e

    def disponivel(self) -> bool:
        try:
            return httpx.get(f"{self.url}/api/tags", timeout=5).status_code == 200
        except httpx.HTTPError:
            return False

    def modelos_instalados(self) -> list[str]:
        try:
            r = httpx.get(f"{self.url}/api/tags", timeout=5)
            return [m["name"] for m in r.json().get("models", [])]
        except httpx.HTTPError:
            return []

    def embed(self, modelo: str, textos: list[str]) -> list[list[float]]:
        corpo = {"model": modelo, "input": textos}
        if self.manter_carregado:
            corpo["keep_alive"] = self.manter_carregado
        dados = self._post("/api/embed", corpo)
        return dados["embeddings"]

    def chat(
        self,
        modelo: str,
        mensagens: list[dict],
        formato: dict | None = None,
        opcoes: dict | None = None,
        pensar: bool | None = None,
        ferramentas: list[dict] | None = None,
    ) -> RespostaLLM:
        """Chama /api/chat sem streaming.

        `ferramentas`: esquemas no formato do Ollama (tool calling). As chamadas
        pedidas pelo modelo voltam em resposta["chamadas"]: [{"nome", "argumentos"}].

        `formato` é um JSON Schema: o Ollama restringe a geração para que a
        saída siga o esquema (structured outputs). Isso elimina a classe de
        erro "o modelo esqueceu de citar o trecho" no nível da sintaxe; o
        conteúdo continua sendo checado pelo verificador.
        """
        corpo: dict = {"model": modelo, "messages": mensagens, "stream": False, "options": opcoes or {}}
        if formato is not None:
            corpo["format"] = formato
        if pensar is not None:
            corpo["think"] = pensar
        if ferramentas:
            corpo["tools"] = ferramentas
        if self.manter_carregado:
            corpo["keep_alive"] = self.manter_carregado
        d = self._post("/api/chat", corpo)
        metricas = {k: d.get(k) for k in ("total_duration", "prompt_eval_count", "eval_count", "done_reason")}
        chamadas = [
            {"nome": c["function"]["name"], "argumentos": c["function"].get("arguments") or {}}
            for c in d["message"].get("tool_calls") or []
        ]
        return RespostaLLM(conteudo=d["message"].get("content", ""), modelo=modelo, metricas=metricas,
                           chamadas=chamadas, mensagem=d["message"])

    def descrever_imagem(self, modelo: str, imagem, prompt: str) -> str:
        buf = io.BytesIO()
        imagem.save(buf, format="PNG")
        corpo = {
            "model": modelo,
            "prompt": prompt,
            "images": [base64.b64encode(buf.getvalue()).decode()],
            "stream": False,
            "options": {"temperature": 0},
        }
        return self._post("/api/generate", corpo)["response"]


class EmbedderOllama:
    def __init__(self, cliente: ClienteOllama, modelo: str) -> None:
        self.cliente = cliente
        self.modelo = modelo
        self.nome = f"ollama:{modelo}"

    def embed(self, textos: list[str]) -> list[list[float]]:
        # Normalizamos aqui para a distância de cosseno ficar consistente,
        # independentemente de o modelo já devolver vetores unitários.
        return [normalizar(v) for v in self.cliente.embed(self.modelo, textos)]


PROMPT_FIGURA = (
    "Você está descrevendo uma figura de um livro técnico de mecânica/elétrica automotiva "
    "para indexação. Transcreva fielmente todos os rótulos, números, nomes de pinos e "
    "cores de fio que estiverem legíveis. Descreva o que a figura mostra (componentes e "
    "ligações) em português. NÃO invente valores que não estejam escritos na imagem; se algo "
    "estiver ilegível, diga 'ilegível'. Legenda original: {legenda}"
)


def descritor_figura_ollama(cliente: ClienteOllama, modelo: str):
    def descrever(imagem, legenda: str) -> str:
        return cliente.descrever_imagem(modelo, imagem, PROMPT_FIGURA.format(legenda=legenda or "(sem legenda)"))

    return descrever
