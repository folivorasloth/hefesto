"""Monta os componentes a partir do config (um lugar só para a "fiação")."""

from __future__ import annotations

from pathlib import Path

from engenheiro.config import Config
from engenheiro.eventos import Barramento
from engenheiro.ingest.extrator import ExtratorPDF, ExtratorTexto
from engenheiro.ingest.indexador import Indexador
from engenheiro.llm.ollama import ClienteOllama, EmbedderOllama, descritor_figura_ollama
from engenheiro.recuperacao.pipeline import Recuperador
from engenheiro.recuperacao.reescrita import Glossario
from engenheiro.recuperacao.reranker import RerankerCrossEncoder
from engenheiro.store.db import Banco


def cliente_ollama(cfg: Config) -> ClienteOllama:
    return ClienteOllama(cfg.ollama.url, cfg.ollama.timeout_s)


def embedder(cfg: Config, falso: bool = False):
    if falso:
        from engenheiro.dev.embedder_falso import EmbedderFalso

        return EmbedderFalso()
    return EmbedderOllama(cliente_ollama(cfg), cfg.ollama.modelos.embeddings)


def banco(cfg: Config, indice: Path | None = None) -> Banco:
    return Banco(indice or cfg.caminho(cfg.caminhos.indice))


def indexador(cfg: Config, bco: Banco, emb, bus: Barramento, biblioteca: Path | None = None) -> Indexador:
    ing = cfg.ingestao
    descritor = None
    if ing.figuras.descrever_com_visao:
        descritor = descritor_figura_ollama(cliente_ollama(cfg), cfg.ollama.modelos.visao)
    pdf = ExtratorPDF(
        ocr_ativo=ing.ocr.ativo,
        idiomas_ocr=ing.ocr.idiomas,
        limiar_ocr=ing.ocr.limiar_caracteres_pagina,
        pasta_figuras=cfg.caminho(cfg.caminhos.figuras) if ing.figuras.salvar_imagens else None,
        descritor_figura=descritor,
    )
    return Indexador(cfg, bco, pdf, ExtratorTexto(), emb, bus, biblioteca)


def recuperador(cfg: Config, bco: Banco, emb, bus: Barramento, com_reranker: bool | None = None) -> Recuperador:
    usar = cfg.busca.reranker.ativo if com_reranker is None else com_reranker
    rr = None
    if usar:
        r = cfg.busca.reranker
        rr = RerankerCrossEncoder(r.modelo, r.max_tokens, r.dispositivo)
    glossario = Glossario.carregar(cfg.dados_ref / "glossario.yaml")
    return Recuperador(cfg, bco, glossario, emb, rr, bus)


def engenheiro(cfg: Config, bco: Banco, bus: Barramento, embedder_falso: bool = False, com_reranker: bool | None = None):
    """Monta o assistente completo. Se o Ollama não responder agora, o LLM fica
    None e o assistente opera no modo "sem modelo" (não improvisa respostas)."""
    from engenheiro.assistente import Engenheiro
    from engenheiro.persona import Persona
    from engenheiro.seguranca import Seguranca

    cli = cliente_ollama(cfg)
    llm = cli if cli.disponivel() else None
    emb = embedder(cfg, embedder_falso) if (llm is not None or embedder_falso) else None
    rec = recuperador(cfg, bco, emb, bus, com_reranker)
    persona = Persona.carregar(cfg.caminho(cfg.assistente.persona))
    seg = Seguranca.carregar(cfg.dados_ref / "seguranca.yaml")
    return Engenheiro(cfg, rec, llm, persona, seg, bus)
