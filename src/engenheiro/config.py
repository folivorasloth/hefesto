"""Carregamento da configuração (config.yaml) com validação.

Por que pydantic: um erro de digitação no YAML (ex.: `max_caracteres: "2400a"`)
deve falhar na hora, com mensagem clara, e não virar um comportamento estranho
no meio de uma indexação noturna.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Assistente(BaseModel):
    id: str = "engenheiro"
    nome: str = "Engenheiro"


class Caminhos(BaseModel):
    biblioteca: Path = Path("data/biblioteca")
    indice: Path = Path("data/indice.sqlite")
    cache: Path = Path("data/cache")
    figuras: Path = Path("data/figuras")
    rastros: Path = Path("data/rastros")


class ModelosOllama(BaseModel):
    embeddings: str = "bge-m3"
    rapido: str = "qwen3:4b"
    forte: str = "qwen3:14b"
    visao: str = "qwen2.5vl:7b"


class Ollama(BaseModel):
    url: str = "http://localhost:11434"
    timeout_s: float = 900
    modelos: ModelosOllama = Field(default_factory=ModelosOllama)


class Ocr(BaseModel):
    ativo: bool = True
    idiomas: list[str] = ["por", "eng"]
    limiar_caracteres_pagina: int = 30


class Figuras(BaseModel):
    salvar_imagens: bool = True
    descrever_com_visao: bool = False


class Corte(BaseModel):
    max_caracteres: int = Field(2400, gt=200)
    sobreposicao_caracteres: int = Field(300, ge=0)


class Ingestao(BaseModel):
    ocr: Ocr = Field(default_factory=Ocr)
    figuras: Figuras = Field(default_factory=Figuras)
    corte: Corte = Field(default_factory=Corte)
    embeddings_lote: int = 16


class Reranker(BaseModel):
    ativo: bool = True
    modelo: str = "BAAI/bge-reranker-v2-m3"
    max_tokens: int = 1024
    dispositivo: str = "cpu"


class Busca(BaseModel):
    candidatos_por_lista: int = 30
    candidatos_rerank: int = 25
    final: int = 6
    rrf_k: int = 60
    roteamento: str = "palavras_chave"
    reranker: Reranker = Field(default_factory=Reranker)


COLECOES_PADRAO = [
    "veiculo",
    "carburacao_etanol",
    "ignicao",
    "eletrica_automotiva",
    "eletronica",
    "mecanica_motor",
    "sensores",
    "esp32",
    "aquisicao_dados",
    "caderno_de_bordo",
]


class Config(BaseModel):
    assistente: Assistente = Field(default_factory=Assistente)
    caminhos: Caminhos = Field(default_factory=Caminhos)
    ollama: Ollama = Field(default_factory=Ollama)
    colecoes: list[str] = Field(default_factory=lambda: list(COLECOES_PADRAO))
    colecoes_sempre: list[str] = Field(default_factory=lambda: ["veiculo", "caderno_de_bordo"])
    ingestao: Ingestao = Field(default_factory=Ingestao)
    busca: Busca = Field(default_factory=Busca)

    # Pasta raiz do projeto (onde fica o config.yaml e dados_ref/).
    raiz: Path = Path(".")

    def caminho(self, p: Path) -> Path:
        """Resolve um caminho do config relativo à pasta do config.yaml."""
        return p if p.is_absolute() else (self.raiz / p)

    @property
    def dados_ref(self) -> Path:
        return self.raiz / "dados_ref"


def _normalizar_url_ollama(valor: str) -> str:
    # OLLAMA_HOST costuma vir como "maquina:11434", sem esquema. O próprio
    # Ollama aceita assim, então aceitamos também.
    valor = valor.strip().rstrip("/")
    if not valor.startswith(("http://", "https://")):
        valor = "http://" + valor
    return valor


def carregar_config(caminho: str | Path | None = None) -> Config:
    """Lê o config.yaml.

    Ordem de busca: argumento > variável ENGENHEIRO_CONFIG > ./config.yaml.
    Sem arquivo, usa os padrões (útil para testes), mas avisa quem chamou
    via `Config.raiz`, que aponta para o diretório atual.
    """
    caminho = caminho or os.environ.get("ENGENHEIRO_CONFIG") or "config.yaml"
    caminho = Path(caminho)
    dados: dict = {}
    if caminho.exists():
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        raiz = caminho.resolve().parent
    else:
        raiz = Path.cwd()
    cfg = Config.model_validate({**dados, "raiz": raiz})
    if os.environ.get("OLLAMA_HOST"):
        cfg.ollama.url = _normalizar_url_ollama(os.environ["OLLAMA_HOST"])
    else:
        cfg.ollama.url = _normalizar_url_ollama(cfg.ollama.url)
    return cfg
