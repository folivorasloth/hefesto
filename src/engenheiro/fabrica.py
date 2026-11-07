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

    # O cliente e o embedder existem sempre: se o Ollama estiver fora agora,
    # cada pergunta percebe isso (e volta a usá-lo quando ele ligar).
    llm = cliente_ollama(cfg)
    emb = embedder(cfg, embedder_falso)
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


def loop_voz(cfg: Config, conv, modo_ativacao: str | None = None, dirigindo: bool = False, mostrar=None):
    """Monta o loop de voz com microfone e alto-falante reais."""
    from engenheiro.voz.ativacao import AtivacaoBotao, AtivacaoOpenWakeWord, AtivacaoTranscricao
    from engenheiro.voz.audio import AltoFalanteSD, MicrofoneSD
    from engenheiro.voz.orquestrador import LoopVoz
    from engenheiro.voz.stt_tts import Sintetizador, Transcritor
    from engenheiro.voz.vad import Recortador

    v = cfg.voz
    rec = Recortador(v.agressividade_vad, v.silencio_fim_fala_ms, v.duracao_max_fala_s)
    stt = Transcritor(v.whisper_modelo, v.dispositivo, v.whisper_compute_type)
    modo = modo_ativacao or v.ativacao.modo
    if modo == "transcricao":
        # Modelo pequeno só para achar a palavra; a pergunta usa o modelo principal.
        stt_ativ = stt if v.ativacao.modelo_whisper_ativacao == v.whisper_modelo else \
            Transcritor(v.ativacao.modelo_whisper_ativacao, v.dispositivo, v.whisper_compute_type)
        ativ = AtivacaoTranscricao(rec, stt_ativ, v.ativacao.palavra, transcritor_principal=stt)
    elif modo == "openwakeword":
        ativ = AtivacaoOpenWakeWord(v.ativacao.modelo_openwakeword, v.ativacao.limiar_openwakeword)
    elif modo == "botao":
        ativ = AtivacaoBotao()
    else:
        raise ValueError(f"voz.ativacao.modo inválido: {modo} (transcricao | openwakeword | botao)")
    sint = Sintetizador(cfg.caminho(v.piper_voz), v.velocidade_fala)
    conv.eng.rec.preaquecer()
    return LoopVoz(conv, MicrofoneSD(), AltoFalanteSD(), sint, stt, ativ, rec, v, dirigindo, mostrar)


def servico(cfg: Config, embedder_falso: bool = False):
    """Hefesto como serviço (API/MQTT): um assistente, perfil e caderno
    compartilhados, telemetria ao vivo ligada à ferramenta ler_telemetria."""
    from engenheiro.servico import Servico
    from engenheiro.telemetria import TelemetriaCache

    bus = Barramento()
    bco = banco(cfg)
    eng = engenheiro(cfg, bco, bus, embedder_falso)
    tele = TelemetriaCache(cfg.mqtt.telemetria_prefixo, cfg.mqtt.telemetria_max_idade_s)
    prf = perfil(cfg)
    cad = caderno(cfg, bco, eng.rec.embedder, bus)
    # O registro de ferramentas do serviço conhece a telemetria ao vivo.
    from engenheiro.ferramentas import criar_registro

    eng.registro = criar_registro(cfg.raiz, bus, cad, prf, tele)
    eng.rec.preaquecer()
    return Servico(eng, prf, cad, cfg.caminho(cfg.caminhos.rastros).parent / "conversas", tele)


def cliente_mqtt(cfg: Config, svc):
    from engenheiro.interfaces.mqtt import ClienteMqtt

    m = cfg.mqtt
    topicos = {"fala": m.topico_fala, "status": m.topico_status, "entrada": m.topico_entrada,
               "pensamento": m.topico_pensamento, "telemetria": m.telemetria_prefixo}
    return ClienteMqtt(svc, m.host, m.porta, m.usuario, None, m.qos, topicos, cfg.assistente.id)
