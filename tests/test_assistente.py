"""Fase 2: respostas com citação e verificador, com um LLM roteirizado.

O LLM falso permite testar exatamente os comportamentos ruins que o sistema
precisa pegar (citação inventada, número inventado, verificador fora do ar),
o que um modelo real não faz sob encomenda.
"""

import json
from pathlib import Path

import pytest

from engenheiro import rastro
from engenheiro.assistente import Engenheiro
from engenheiro.config import Config
from engenheiro.eventos import Barramento
from engenheiro.geracao import prompts
from engenheiro.ingest.modelos import Trecho
from engenheiro.llm.selecao import escolher
from engenheiro.persona import Persona
from engenheiro.recuperacao.pipeline import Recuperador
from engenheiro.recuperacao.reescrita import Glossario
from engenheiro.seguranca import Seguranca
from engenheiro.store.db import Banco, DadosDocumento

RAIZ = Path(__file__).parents[1]


class LLMRoteirizado:
    """Responde conforme o tipo de prompt. `resposta` e `verificacao` são dicts
    (viram JSON) ou exceções a lançar."""

    def __init__(self, resposta=None, verificacao=None, traducao="cylinder head bolt torque"):
        self.resposta = resposta
        self.verificacao = verificacao
        self.traducao = traducao
        self.chamadas: list[tuple[str, list[dict]]] = []

    def chat(self, modelo, mensagens, formato=None, opcoes=None, pensar=None):
        sistema = mensagens[0]["content"]
        if prompts.TRADUCAO in sistema:
            tipo, saida = "traducao", {"consulta_en": self.traducao}
        elif prompts.VERIFICADOR in sistema:
            tipo, saida = "verificacao", self.verificacao
        elif prompts.CONVERSA in sistema:
            tipo, saida = "conversa", "Olá! Pode perguntar."
        else:
            tipo, saida = "resposta", self.resposta
        self.chamadas.append((tipo, mensagens))
        if isinstance(saida, Exception):
            raise saida
        conteudo = saida if isinstance(saida, str) else json.dumps(saida)
        return {"conteudo": conteudo, "modelo": modelo, "metricas": {"prompt_eval_count": 100}}

    def tipos(self):
        return [t for t, _ in self.chamadas]


class RerankerPalavra:
    """Score alto se o trecho contém alguma palavra da consulta com 5+ letras."""

    nome = "teste"

    def pontuar(self, consulta, textos):
        palavras = {p.lower().strip("?.,") for p in consulta.split() if len(p) >= 5}
        return [0.9 if any(p in t.lower() for p in palavras) else 0.001 for t in textos]


TRECHOS = {
    "veiculo": [
        Trecho("Torque do cabeçote: etapa 1 a 17,3 N·m, etapa 2 a 41,7 N·m.", ["Motor", "Cabeçote"], 5, 5, ["tabela"], ["texto"]),
        Trecho("A bateria fica no cofre do motor, lado esquerdo.", ["Elétrica", "Bateria"], 9, 9, ["paragrafo"], ["texto"]),
    ],
    "carburacao_etanol": [
        Trecho("Giclê principal com diâmetro de teste 1,37 mm.", ["Apostila"], 1, 1, ["paragrafo"], ["ocr"]),
    ],
}


@pytest.fixture
def ambiente(tmp_path):
    cfg = Config(raiz=tmp_path)
    b = Banco(":memory:")
    for col, ts in TRECHOS.items():
        d = DadosDocumento(f"{col}/livro.pdf", col, "s", "d", f"Livro {col}", f"Livro-{col}", deslocamento_paginas=0)
        b.substituir_documento(d, ts, ["pt"] * len(ts))

    def criar(llm, reranker=RerankerPalavra()):
        bus = Barramento()
        rec = Recuperador(cfg, b, Glossario([]), None, reranker, bus)
        seg = Seguranca.carregar(RAIZ / "dados_ref" / "seguranca.yaml")
        return Engenheiro(cfg, rec, llm, Persona.carregar(RAIZ / "persona" / "engenheiro.yaml"), seg, bus)

    return cfg, criar


def _contexto_ids(llm):
    """Ids T# que o gerador recebeu, mapeados para o início do texto."""
    msgs = next(m for t, m in llm.chamadas if t == "resposta")
    return msgs[1]["content"]


# ---------------------------------------------------------------- caminho feliz
def test_afirmacao_suportada_sai_com_citacao_de_livro_e_pagina(ambiente):
    cfg, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "Na etapa 1, o aperto do cabeçote é de 17,3 N·m.", "tipo": "fonte", "trechos": ["T1"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "tabela do trecho"}]},
    )
    resp = criar(llm).responder("Qual o torque do cabeçote?")
    assert "[Livro-veiculo, p. 5]" in resp.texto
    assert "Das fontes:" in resp.texto
    assert "T1" not in resp.texto           # id interno nunca aparece
    assert resp.encontrou and not resp.problemas_criticos
    assert llm.tipos() == ["traducao", "resposta", "verificacao"]
    # A tradução virou variante de busca e consulta do reranker:
    r = rastro.carregar(cfg.caminho(cfg.caminhos.rastros), resp.rastro_id)
    assert any(v["tipo"] == "llm_ingles" for v in r["busca"]["variantes"])
    # Trecho em português é pontuado pela pergunta original (o inglês fica para trechos em inglês).
    assert set(r["busca"]["candidatos"][0]["rerank_por_consulta"]) == {"original"}


# ---------------------------------------------------------------- citação inventada
def test_citacao_inexistente_e_descartada_e_afirmacao_rebaixada(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "O cabeçote é de alumínio.", "tipo": "fonte", "trechos": ["T9"], "critica": False}]},
        verificacao={"avaliacoes": []},
    )
    resp = criar(llm).responder("Qual o torque do cabeçote?")
    assert "Das fontes:" not in resp.texto
    assert "Inferência" in resp.texto and "sem citação válida" in resp.texto
    assert "citação inexistente descartada: T9" in resp.texto


# ---------------------------------------------------------------- reprovação crítica
def test_reprovacao_critica_remove_e_aparece_no_topo(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "O torque final é 17,3 N·m sem aperto angular.", "tipo": "fonte", "trechos": ["T1"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "nao_suporta", "justificativa": "o trecho tem duas etapas"}]},
    )
    resp = criar(llm).responder("Qual o torque do cabeçote?")
    assert resp.texto.startswith("⚠ VERIFICAÇÃO")
    assert "REPROVOU" in resp.texto and "o trecho tem duas etapas" in resp.texto
    assert "Removidas pelo verificador" in resp.texto
    assert "Das fontes:" not in resp.texto
    assert not resp.encontrou


def test_suporte_parcial_rebaixa_para_inferencia(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "O aperto tem duas etapas e é igual em todos os motores AP.", "tipo": "fonte", "trechos": ["T1"], "critica": False}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "parcial", "justificativa": "não fala de todos os motores"}]},
    )
    resp = criar(llm).responder("Qual o torque do cabeçote?")
    assert "Inferência" in resp.texto and "sustenta só em parte" in resp.texto


# ---------------------------------------------------------------- número inventado
def test_numero_sem_origem_e_pego_pelo_codigo_mesmo_se_o_verificador_aprovar(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "Na etapa 1, aperte a 17,8 N·m.", "tipo": "fonte", "trechos": ["T1"], "critica": True}]},
        # Verificador LLM "distraído" aprova; o código não deixa passar.
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "ok"}]},
    )
    resp = criar(llm).responder("Qual o torque do cabeçote?")
    assert resp.problemas_criticos and "17,8" in resp.problemas_criticos[0]
    assert resp.texto.startswith("⚠ VERIFICAÇÃO")
    assert "número(s) sem origem verificável: 17,8" in resp.texto
    assert "Das fontes:" not in resp.texto  # não pode parecer que o livro diz 17,8


def test_numero_vindo_da_pergunta_nao_e_suspeito(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "Os 12,6 V que você mediu são da bateria em repouso.", "tipo": "inferencia", "trechos": ["T2"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "parcial", "justificativa": "plausível"}]},
    )
    resp = criar(llm).responder("Medi 12,6 V na bateria, está boa?")
    assert not resp.problemas_criticos


# ---------------------------------------------------------------- não encontrei
def test_sem_trecho_relevante_diz_que_nao_encontrou(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": False, "afirmacoes": [], "falta": "A base não tem dados de caminhões Scania.",
                  "sugestoes": ["Procure o manual do fabricante do caminhão."]},
        verificacao={"avaliacoes": []},
        traducao="Scania truck tire pressure",
    )
    resp = criar(llm).responder("Qual a pressão do pneu de um caminhão Scania?")
    assert "Não encontrei isso nas fontes" in resp.texto
    assert not resp.encontrou
    assert prompts.SEM_FONTES in _contexto_ids(llm)  # o gerador soube que não havia fonte
    assert "Das fontes:" not in resp.texto


def test_modelo_que_cita_sem_haver_contexto_e_rebaixado(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "A pressão é de 110 psi.", "tipo": "fonte", "trechos": ["T1"], "critica": True}]},
        verificacao={"avaliacoes": []}, traducao="Scania truck tire pressure",
    )
    resp = criar(llm).responder("Qual a pressão do pneu de um caminhão Scania?")
    assert "Das fontes:" not in resp.texto
    assert resp.problemas_criticos and "110" in resp.problemas_criticos[0]
    assert "Não encontrei isso nas fontes" in resp.texto


# ---------------------------------------------------------------- falhas
def test_sem_llm_nao_improvisa_e_mostra_onde_procurar(ambiente):
    _, criar = ambiente
    resp = criar(None).responder("Qual o torque do cabeçote?")
    assert "sem o modelo de linguagem" in resp.texto
    assert "[Livro-veiculo, p. 5]" in resp.texto
    assert "17,3" not in resp.texto


def test_verificador_fora_do_ar_nunca_vira_aprovado(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "Na etapa 1, aperte a 17,3 N·m.", "tipo": "fonte", "trechos": ["T1"], "critica": True}]},
        verificacao=ConnectionError("caiu"),
    )
    resp = criar(llm).responder("Qual o torque do cabeçote?")
    assert "NÃO passou pelo verificador" in resp.texto
    assert "Das fontes:" not in resp.texto
    assert resp.problemas_criticos and "NÃO verificada" in resp.problemas_criticos[0]


def test_json_invalido_do_modelo_vira_resposta_sem_llm(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado(resposta="isto não é json", verificacao={"avaliacoes": []})
    resp = criar(llm).responder("Qual o torque do cabeçote?")
    assert "sem o modelo de linguagem" in resp.texto and "não devolveu JSON" in resp.texto


def test_ocr_aparece_como_aviso_na_afirmacao(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "O giclê principal de teste tem 1,37 mm.", "tipo": "fonte", "trechos": ["T1"], "critica": False}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "ok"}]},
        traducao="main jet diameter",
    )
    resp = criar(llm).responder("Qual o diâmetro do giclê principal?")
    assert "OCR: confira no original" in resp.texto


# ---------------------------------------------------------------- segurança
def test_avisos_de_seguranca_deterministicos(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "A bateria fica no cofre, lado esquerdo.", "tipo": "fonte", "trechos": ["T1"], "critica": False}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "ok"}]},
        traducao="battery location",
    )
    resp = criar(llm).responder("Onde fica a bateria?")
    assert "Segurança" in resp.texto and "cabo NEGATIVO" in resp.texto


# ---------------------------------------------------------------- rastro
def test_rastro_completo(ambiente):
    cfg, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "Etapa 1: 17,3 N·m.", "tipo": "fonte", "trechos": ["T1"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "ok"}]},
    )
    resp = criar(llm).responder("Qual o torque do cabeçote?")
    r = rastro.carregar(cfg.caminho(cfg.caminhos.rastros), resp.rastro_id)
    for chave in ("pergunta", "escolha_modelo", "traducao", "busca", "geracao", "verificacao", "resposta_final", "eventos"):
        assert chave in r, chave
    assert r["geracao"]["contexto"][0]["citacao"] == "[Livro-veiculo, p. 5]"
    assert r["verificacao"]["afirmacoes"][0]["veredito"] == "suporta"
    assert r["busca"]["candidatos"][0]["rerank"] is not None
    tipos = [e["tipo"] for e in r["eventos"]]
    assert tipos.index("busca.rerank") < tipos.index("geracao.concluida") < tipos.index("verificacao.concluida")


# ---------------------------------------------------------------- conversa e seleção
def test_conversa_nao_busca_nem_verifica(ambiente):
    _, criar = ambiente
    llm = LLMRoteirizado()
    resp = criar(llm).responder("Bom dia!")
    assert resp.modo == "conversa" and llm.tipos() == ["conversa"]


@pytest.mark.parametrize("pergunta, modo, nivel", [
    ("bom dia", "conversa", "rapido"),
    ("valeu, obrigado!", "conversa", "rapido"),
    ("oi, qual a tensão da bateria?", "tecnico", "forte"),
    ("como regular o carburador?", "tecnico", "forte"),
    ("me explica o ciclo Otto", "tecnico", "forte"),
])
def test_escolha_de_modelo(pergunta, modo, nivel):
    e = escolher(pergunta)
    assert (e.modo, e.nivel) == (modo, nivel)


# ---------------------------------------------------------------- avaliação (modo resposta)
def test_avaliacao_modo_resposta(ambiente):
    from engenheiro.avaliacao import Pergunta, avaliar_respostas

    cfg, criar = ambiente
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "Na etapa 1, aperte a 17,3 N·m.", "tipo": "fonte", "trechos": ["T1"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "ok"}]},
    )
    eng = criar(llm)
    perguntas = [Pergunta("p1", "Qual o torque do cabeçote?", fatos_chave=["17.3 N.m"], critica=True)]
    res = avaliar_respostas(eng, perguntas, cfg.caminho(cfg.caminhos.rastros))
    m = res["metricas"]
    assert m["fonte_aprovada"] == 1.0 and m["fatos_chave"] == 1.0 and m["falso_nao_sei"] == 0.0


def test_volta_sozinho_quando_o_ollama_liga(ambiente):
    _, criar = ambiente

    class ClienteQueLiga(LLMRoteirizado):
        ligado = False

        def disponivel(self):
            return self.ligado

    cli = ClienteQueLiga(
        resposta={"encontrou": False, "falta": "x", "sugestoes": [], "afirmacoes": []}, verificacao={"avaliacoes": []})
    eng = criar(cli)
    eng._INTERVALO_CHECAGEM_S = 0
    assert "sem o modelo de linguagem" in eng.responder("Qual o torque do cabeçote?").texto
    cli.ligado = True                     # o notebook do LLM ligou
    assert "sem o modelo de linguagem" not in eng.responder("Qual o torque do cabeçote?").texto
