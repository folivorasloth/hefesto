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


def perfil(cfg: Config):
    from engenheiro.perfil import Perfil

    return Perfil(cfg.caminho(cfg.perfil_veiculo))


def caderno(cfg: Config, bco: Banco | None = None, emb=None, bus: Barramento | None = None):
    """Caderno de bordo. Com `bco`, cada anotação nova é indexada na hora
    (só a coleção do caderno; o resto da biblioteca não é tocado)."""
    from engenheiro.caderno import COLECAO, Caderno

    pasta = cfg.caminho(cfg.caminhos.biblioteca) / COLECAO
    ao_gravar = None
    if bco is not None:
        ao_gravar = lambda: indexador(cfg, bco, emb, bus or Barramento()).indexar(colecoes=[COLECAO])  # noqa: E731
    return Caderno(pasta, ao_gravar)


def registro_ferramentas(cfg: Config, bus: Barramento, cad=None, prf=None):
    from engenheiro.ferramentas import criar_registro

    return criar_registro(cfg.raiz, bus, cad, prf)


def engenheiro(cfg: Config, bco: Banco, bus: Barramento, embedder_falso: bool = False, com_reranker: bool | None = None):
    """Monta o assistente completo. Se o Ollama não responder agora, o LLM fica
    None e o assistente opera no modo "sem modelo" (não improvisa respostas)."""
    from engenheiro import web
    from engenheiro.assistente import Engenheiro
    from engenheiro.persona import Persona
    from engenheiro.seguranca import Seguranca

    cli = cliente_ollama(cfg)
    llm = cli if cli.disponivel() else None
    emb = embedder(cfg, embedder_falso) if (llm is not None or embedder_falso) else None
    rec = recuperador(cfg, bco, emb, bus, com_reranker)
    persona = Persona.carregar(cfg.caminho(cfg.assistente.persona))
    seg = Seguranca.carregar(cfg.dados_ref / "seguranca.yaml")
    prf = perfil(cfg)
    cad = caderno(cfg, bco, emb, bus)
    reg = registro_ferramentas(cfg, bus, cad, prf)
    busca_web = None
    if cfg.web.searxng_url:
        busca_web = lambda q: web.buscar(cfg.web.searxng_url, q, cfg.web.maximo_resultados)  # noqa: E731
    return Engenheiro(cfg, rec, llm, persona, seg, bus, prf.para_prompt(), reg, busca_web, prf.valores_confirmados())


def conversador(cfg: Config, bco: Banco, bus: Barramento, nova: bool = False, embedder_falso: bool = False,
                com_reranker: bool | None = None):
    """Assistente + sessão de conversa (continua a última, salvo `nova`)."""
    from engenheiro.conversa import Conversador, Sessao

    eng = engenheiro(cfg, bco, bus, embedder_falso, com_reranker)
    pasta = cfg.caminho(cfg.caminhos.rastros).parent / "conversas"
    sessao = None if nova else Sessao.ultima(pasta)
    prf = perfil(cfg)
    cad = caderno(cfg, bco, eng.rec.embedder, bus)
    return Conversador(eng, prf, cad, pasta, sessao)
