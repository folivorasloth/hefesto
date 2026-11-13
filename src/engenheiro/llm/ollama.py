"""Cliente mínimo da API HTTP do Ollama.

Uso o HTTP direto (httpx) em vez da biblioteca `ollama` para ter controle
total do que vai e volta: tudo isso entra no rastro de auditoria.
"""

from __future__ import annotations

import base64
import io
import json
import math
import re
from typing import Protocol

import httpx


class OllamaIndisponivel(RuntimeError):
    """O notebook do LLM está desligado ou fora da rede."""

    def __init__(self, mensagem: str, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.status = status   # código HTTP, quando o Ollama respondeu com erro


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


# Modelos que "pensam" (qwen3, deepseek-r1...) podem devolver o raciocínio
# dentro do próprio conteúdo, entre <think> e </think>, dependendo da versão
# do Ollama e da opção `think`. Esse bloco não é resposta: não pode ser
# mostrado, falado, nem atrapalhar a leitura do JSON.
_RE_PENSAMENTO = re.compile(r"<think>(.*?)</think>\s*", re.DOTALL | re.IGNORECASE)
_RE_PENSAMENTO_ABERTO = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)   # cortado antes de fechar
_RE_CERCA = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL | re.IGNORECASE)


def separar_pensamento(conteudo: str) -> tuple[str, str]:
    """(conteúdo sem o raciocínio, raciocínio)."""
    pensado = "\n".join(p.strip() for p in _RE_PENSAMENTO.findall(conteudo))
    limpo = _RE_PENSAMENTO.sub("", conteudo)
    aberto = _RE_PENSAMENTO_ABERTO.search(limpo)
    if aberto:
        pensado = (pensado + "\n" + aberto.group(0)[len("<think>"):].strip()).strip()
        limpo = limpo[: aberto.start()]
    return limpo.strip(), pensado


def extrair_json(conteudo: str) -> str:
    """Quando se pediu JSON e o modelo o embrulhou (cerca ```json, uma frase
    antes ou depois), devolve só o objeto. Se já é JSON válido, ou se não há
    objeto recuperável, devolve o texto como veio: quem chama decide o que
    fazer com uma resposta inválida."""
    try:
        json.loads(conteudo)
        return conteudo
    except ValueError:
        pass
    candidatos = []
    cerca = _RE_CERCA.match(conteudo)
    if cerca:
        candidatos.append(cerca.group(1).strip())
    inicio, fim = conteudo.find("{"), conteudo.rfind("}")
    if 0 <= inicio < fim:
        candidatos.append(conteudo[inicio : fim + 1])
    for c in candidatos:
        try:
            if isinstance(json.loads(c), dict):
                return c
        except ValueError:
            continue
    return conteudo


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
            raise OllamaIndisponivel(f"Ollama em {self.url} respondeu {r.status_code}: {motivo}.{dica}", r.status_code)
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
        try:
            d = self._post("/api/chat", corpo)
        except OllamaIndisponivel as e:
            # Modelo sem suporte a `think` recusa o pedido com 400: repete sem a opção.
            if e.status != 400 or "think" not in corpo:
                raise
            del corpo["think"]
            d = self._post("/api/chat", corpo)
        msg = d.get("message")
        if not isinstance(msg, dict):
            raise RespostaInvalida(f"resposta do Ollama sem mensagem: {str(d)[:200]}")
        metricas = {k: d.get(k) for k in ("total_duration", "prompt_eval_count", "eval_count", "done_reason")}
        chamadas = [
            {"nome": c["function"]["name"], "argumentos": c["function"].get("arguments") or {}}
            for c in msg.get("tool_calls") or []
        ]
        conteudo, pensado = separar_pensamento(msg.get("content") or "")
        if formato is not None:
            conteudo = extrair_json(conteudo)
        # A mensagem volta para o modelo na etapa de ferramentas: vai sem o raciocínio.
        msg = {**msg, "content": conteudo}
        # O raciocínio fica no rastro (auditoria), separado da resposta.
        raciocinio = "\n".join(p for p in (msg.get("thinking") or "", pensado) if p)
        if raciocinio:
            metricas["raciocinio"] = raciocinio   # as métricas da geração são gravadas no rastro
        return RespostaLLM(conteudo=conteudo, modelo=modelo, metricas=metricas, chamadas=chamadas, mensagem=msg,
                           raciocinio=raciocinio)

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
