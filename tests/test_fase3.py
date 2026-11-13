"""Fase 3: ferramentas no fluxo da resposta, web não verificada, perfil e caderno."""

import json
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from engenheiro import rastro
from engenheiro.assistente import Engenheiro
from engenheiro.caderno import Caderno
from engenheiro.config import Config
from engenheiro.dev.embedder_falso import EmbedderFalso
from engenheiro.eventos import Barramento
from engenheiro.ferramentas import criar_registro
from engenheiro.geracao import prompts
from engenheiro.ingest.extrator import ExtratorTexto
from engenheiro.ingest.indexador import Indexador
from engenheiro.ingest.modelos import Trecho
from engenheiro.perfil import Perfil, PerfilInvalido
from engenheiro.persona import Persona
from engenheiro.recuperacao.pipeline import Recuperador
from engenheiro.recuperacao.reescrita import Glossario
from engenheiro.seguranca import Seguranca
from engenheiro.store.db import Banco, DadosDocumento
from engenheiro.web import ResultadoWeb

RAIZ = Path(__file__).parents[1]


class LLMComFerramentas:
    """Roteiriza as 4 chamadas possíveis: tradução, etapa de ferramentas
    (reconhecida por receber `ferramentas`), resposta e verificação."""

    def __init__(self, rodadas=None, resposta=None, verificacao=None, falhar_ferramentas=False):
        self.rodadas = list(rodadas or [])     # cada item: lista de {"nome", "argumentos"}
        self.resposta = resposta
        self.verificacao = verificacao or {"avaliacoes": []}
        self.falhar_ferramentas = falhar_ferramentas
        self.chamadas: list[tuple[str, list[dict]]] = []

    def chat(self, modelo, mensagens, formato=None, opcoes=None, pensar=None, ferramentas=None):
        sistema = mensagens[0]["content"]
        if prompts.TRADUCAO in sistema:
            self.chamadas.append(("traducao", mensagens))
            return {"conteudo": json.dumps({"consulta_en": "question"}), "metricas": {}}
        if prompts.VERIFICADOR in sistema:
            self.chamadas.append(("verificacao", mensagens))
            return {"conteudo": json.dumps(self.verificacao), "metricas": {}}
        if ferramentas is not None:
            self.chamadas.append(("ferramentas", [dict(m) for m in mensagens]))
            if self.falhar_ferramentas:
                raise RuntimeError("model does not support tools")
            pedidas = self.rodadas.pop(0) if self.rodadas else []
            return {"conteudo": "" if pedidas else "PRONTO", "metricas": {}, "chamadas": pedidas,
                    "mensagem": {"role": "assistant", "content": ""}}
        self.chamadas.append(("resposta", mensagens))
        return {"conteudo": json.dumps(self.resposta), "metricas": {}}

    def tipos(self):
        return [t for t, _ in self.chamadas]

    def mensagens_de(self, tipo, n=0):
        return [m for t, m in self.chamadas if t == tipo][n]


class RerankerFixo:
    nome = "fixo"

    def pontuar(self, consulta, textos):
        return [0.9 if "resistor" in t.lower() or "bateria" in t.lower() else 0.001 for t in textos]


@pytest.fixture
def montar(tmp_path):
    cfg = Config(raiz=tmp_path)
    b = Banco(":memory:")
    d = DadosDocumento("eletrica_automotiva/livro.pdf", "eletrica_automotiva", "s", "d", "Livro", "Livro-E",
                       deslocamento_paginas=0)
    b.substituir_documento(d, [Trecho("Um resistor limita a corrente conforme a lei de Ohm.", ["Ohm"], 3, 3,
                                      ["paragrafo"], ["texto"])], ["pt"])
    perfil = Perfil(RAIZ / "modelos" / "perfil_veiculo.yaml")

    def criar(llm, busca_web=None, modo_web="pedido"):
        cfg.web.modo = modo_web
        bus = Barramento()
        rec = Recuperador(cfg, b, Glossario([]), None, RerankerFixo(), bus)
        reg = criar_registro(RAIZ, bus)
        return Engenheiro(cfg, rec, llm, Persona(), Seguranca.carregar(RAIZ / "dados_ref" / "seguranca.yaml"), bus,
                          perfil.para_prompt(), reg, busca_web, perfil.valores_confirmados())

    return cfg, criar


PERGUNTA = "Qual a corrente num resistor de 6 ohms ligado em 12 V?"


def test_conta_feita_pela_ferramenta_vira_fonte_citavel(montar):
    cfg, criar = montar
    llm = LLMComFerramentas(
        rodadas=[[{"nome": "lei_de_ohm", "argumentos": {"tensao_v": 12, "resistencia_ohm": 6}}]],
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "A corrente é de 2 A e a potência dissipada é de 24 W.", "tipo": "fonte", "trechos": ["F1"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "resultado da ferramenta"}]},
    )
    resp = criar(llm).responder(PERGUNTA)
    assert "[cálculo: lei_de_ohm]" in resp.texto and "Das fontes:" in resp.texto
    assert not resp.problemas_criticos
    assert llm.tipos() == ["traducao", "ferramentas", "ferramentas", "resposta", "verificacao"]
    r = rastro.carregar(cfg.caminho(cfg.caminhos.rastros), resp.rastro_id)
    assert r["ferramentas"]["chamadas"][0]["saida"]["resultado"]["corrente_a"] == 2
    # O resultado da ferramenta chegou ao modelo da etapa 2 e ao verificador:
    assert "lei_de_ohm" in llm.mensagens_de("resposta")[1]["content"]
    assert "[F1] Ferramenta lei_de_ohm" in llm.mensagens_de("verificacao")[1]["content"]
    assert any(e["tipo"] == "ferramenta.chamada" for e in r["eventos"])


def test_conta_de_cabeca_e_pega(montar):
    _, criar = montar
    llm = LLMComFerramentas(
        rodadas=[[]],   # o modelo não chamou ferramenta nenhuma...
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            # ...e fez a conta de cabeça (12/6 = 2 está "certo", mas não veio de fonte nem de ferramenta).
            {"texto": "A corrente será de 2 A.", "tipo": "fonte", "trechos": ["T1"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "lei de Ohm"}]},
    )
    resp = criar(llm).responder(PERGUNTA)
    assert resp.problemas_criticos and "2" in resp.problemas_criticos[0]
    assert "Das fontes:" not in resp.texto


def test_ferramenta_com_erro_volta_para_o_modelo(montar):
    cfg, criar = montar
    llm = LLMComFerramentas(
        rodadas=[[{"nome": "lambda_afr", "argumentos": {"combustivel": "etanol_hidratado", "lambda": 1.0}}]],
        resposta={"encontrou": False, "falta": "Sem a relação estequiométrica confirmada.", "sugestoes": [], "afirmacoes": []},
    )
    resp = criar(llm).responder("Quanto é AFR para lambda 1 no etanol?")
    msgs = llm.mensagens_de("ferramentas", 1)
    assert any(m["role"] == "tool" and "não foi confirmada" in m["content"] for m in msgs)
    assert "Não encontrei" in resp.texto


def test_etapa_de_ferramentas_falhando_nao_derruba(montar):
    _, criar = montar
    llm = LLMComFerramentas(
        falhar_ferramentas=True,
        resposta={"encontrou": False, "falta": "x", "sugestoes": [], "afirmacoes": []},
    )
    resp = criar(llm).responder(PERGUNTA)
    assert "Etapa de ferramentas falhou" in resp.texto


def test_prefixo_compartilhado_entre_as_duas_etapas(montar):
    _, criar = montar
    llm = LLMComFerramentas(rodadas=[[]], resposta={"encontrou": False, "falta": "", "sugestoes": [], "afirmacoes": []})
    criar(llm).responder(PERGUNTA)
    a = llm.mensagens_de("ferramentas")
    b = llm.mensagens_de("resposta")
    assert a[0]["content"] == b[0]["content"]                       # mesmo sistema
    pre = b[1]["content"].split(prompts.INSTRUCAO_RESPOSTA)[0]
    base = a[1]["content"].split(prompts.INSTRUCAO_FERRAMENTAS)[0].rstrip()
    assert pre.startswith(base)                                     # mesmo começo do usuário


def test_web_so_quando_pedido_e_sempre_nao_verificada(montar):
    _, criar = montar
    chamado = []

    def web(q):
        chamado.append(q)
        return [ResultadoWeb("W1", "Fórum", "https://forum.exemplo.com/t/1", "Dizem que é 2 A.")]

    resposta = {"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
        {"texto": "Num fórum dizem que é 2 A.", "tipo": "fonte", "trechos": ["W1"], "critica": True}]}
    criar(LLMComFerramentas(rodadas=[[]], resposta=resposta), web).responder(PERGUNTA)
    assert chamado == []   # não pediu web: não buscou

    resp = criar(LLMComFerramentas(rodadas=[[]], resposta=resposta), web).responder(PERGUNTA + " Pesquise na internet.")
    assert chamado
    assert "Web (NÃO verificado" in resp.texto and "https://forum.exemplo.com/t/1" in resp.texto
    assert "Das fontes:" not in resp.texto                          # "fonte" virou web
    assert any("SÓ da web" in p for p in resp.problemas_criticos)   # crítico vindo da web


def test_web_fora_do_ar_avisa(montar):
    _, criar = montar

    def web(q):
        raise ConnectionError("searxng fora")

    resp = criar(LLMComFerramentas(rodadas=[[]], resposta={"encontrou": False, "falta": "", "sugestoes": [], "afirmacoes": []}),
                 web).responder("pesquise na web o pinout do EL817")
    assert "Busca na web falhou" in resp.texto


# ------------------------------------------------------------------ perfil
def test_perfil_separa_confirmado_de_suposicao():
    txt = Perfil(RAIZ / "modelos" / "perfil_veiculo.yaml").para_prompt()
    conf, resto = txt.split("SUPOSIÇÃO", 1)
    sup, desconhecido = resto.split("DESCONHECIDO", 1)
    assert "veiculo.motor: AP 1.6" in conf and "etanol" in conf
    assert "carburador.fabricante: Weber" in sup and "Weber" not in conf
    assert "ignicao.tipo" in sup
    assert "carburador.modelo" in desconhecido
    assert "REVERSÍVEL".lower() in txt.lower() or "reversível" in txt


def test_ano_do_perfil_nao_e_numero_suspeito(montar):
    _, criar = montar
    llm = LLMComFerramentas(rodadas=[[]], resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
        {"texto": "Seu Gol 1994 tem motor AP 1.6.", "tipo": "inferencia", "trechos": [], "critica": False}]})
    resp = criar(llm).responder(PERGUNTA)
    assert "sem origem" not in resp.texto


def test_perfil_definir_grava_historico_e_mantem_comentarios(tmp_path):
    p = tmp_path / "perfil.yaml"
    p.write_text((RAIZ / "modelos" / "perfil_veiculo.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    perfil = Perfil(p)
    with pytest.raises(PerfilInvalido, match="fonte"):
        perfil.definir("carburador.modelo", "Weber 460", "confirmado", None)
    perfil.definir("carburador.modelo", "Weber 460", "confirmado", "gravação no corpo do carburador")
    texto = p.read_text(encoding="utf-8")
    assert texto.startswith("# Perfil do veículo")
    novo = Perfil(p)
    assert novo.valor_confirmado("carburador.modelo") == "Weber 460"
    assert novo.dados["historico"][-1]["campo"] == "carburador.modelo"
    assert novo.valor_confirmado("carburador.fabricante") is None   # suposição não vira parâmetro


# ------------------------------------------------------------------ caderno
def test_caderno_registra_busca_e_entra_no_indice(tmp_path):
    cfg = Config(raiz=tmp_path)
    bib = tmp_path / "data" / "biblioteca"
    banco = Banco(tmp_path / "i.sqlite")
    idx = Indexador(cfg, banco, None, ExtratorTexto(), EmbedderFalso())
    cad = Caderno(bib / "caderno_de_bordo", ao_gravar=lambda: idx.indexar(colecoes=["caderno_de_bordo"]))
    a = cad.registrar("Medi 12,6 V na bateria com o motor desligado.", "Medição da bateria", ["bateria"],
                      quando=datetime(2026, 11, 7, 14, 32))
    assert a.citacao == "[Caderno 2026-11-07 14:32]"
    cad.registrar("Soldei os headers do conversor de nível.", quando=datetime(2026, 11, 7, 18, 0))
    assert [x.titulo for x in cad.buscar("bateria")] == ["Medição da bateria"]
    assert len(cad.buscar("")) == 2
    ficha = yaml.safe_load((bib / "caderno_de_bordo" / "2026-11-07.yaml").read_text(encoding="utf-8"))
    assert ficha["citacao"] == "Caderno 2026-11-07"
    t = banco.obter_trechos([r[0] for r in banco.con.execute("SELECT id FROM trechos")])
    assert any("12,6 V" in x.texto and x.citacao == "Caderno 2026-11-07" for x in t.values())


def test_ferramenta_buscar_caderno(tmp_path):
    cad = Caderno(tmp_path / "cad")
    cad.registrar("Bateria: 12,6 V em repouso.", "Bateria", quando=datetime(2026, 11, 7, 9, 0))
    reg = criar_registro(RAIZ, caderno=cad)
    ch = reg.executar("buscar_caderno", {"termo": "bateria"})
    assert ch.saida["resultado"]["anotacoes"][0]["citacao"] == "[Caderno 2026-11-07 09:00]"


# ------------------------------------------------------------------ SearXNG
def test_cliente_searxng(monkeypatch):
    import httpx

    from engenheiro import web

    def get_ok(url, params, timeout):
        assert url == "http://homelab:8888/search" and params["format"] == "json"
        return httpx.Response(200, json={"results": [
            {"title": "EL817 datasheet", "url": "https://everlight.example/el817.pdf", "content": "4-pin DIP"}]},
            request=httpx.Request("GET", url))

    monkeypatch.setattr(web.httpx, "get", get_ok)
    r = web.buscar("http://homelab:8888/", "EL817")
    assert r[0].id == "W1" and r[0].citacao == "[web: everlight.example]" and "NÃO VERIFICADA" in r[0].para_prompt()

    monkeypatch.setattr(web.httpx, "get", lambda url, params, timeout: httpx.Response(403, request=httpx.Request("GET", url)))
    with pytest.raises(web.WebIndisponivel, match="json"):
        web.buscar("http://homelab:8888", "x")
    with pytest.raises(web.WebIndisponivel, match="não configurado"):
        web.buscar("", "x")


# ---------------------------------------------------------------- furos fechados
def test_numero_inventado_nao_e_lavado_por_ferramenta(montar):
    """O modelo passa um número que não está em lugar nenhum por uma ferramenta
    e cita o F#: não pode sair como "Das fontes [cálculo: ...]"."""
    cfg, criar = montar
    llm = LLMComFerramentas(
        rodadas=[[{"nome": "converter_unidade", "argumentos": {"valor": 83, "de": "N.m", "para": "N.m"}}]],
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "O torque de aperto é 83 N·m.", "tipo": "fonte", "trechos": ["F1"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "está no F1"}]},
    )
    resp = criar(llm).responder("Qual o torque de aperto do cabeçote?")
    assert "Das fontes:" not in resp.texto
    assert any("83" in p for p in resp.problemas_criticos)
    assert "não conta como fonte" in resp.texto
    r = rastro.carregar(cfg.caminho(cfg.caminhos.rastros), resp.rastro_id)
    assert r["ferramentas"]["chamadas"][0]["argumentos_sem_origem"] == ["valor=83"]


def test_resultado_de_uma_ferramenta_serve_de_argumento_para_a_proxima(montar):
    _, criar = montar
    llm = LLMComFerramentas(
        rodadas=[[{"nome": "lei_de_ohm", "argumentos": {"tensao_v": 12, "resistencia_ohm": 6}}],
                 [{"nome": "lei_de_ohm", "argumentos": {"tensao_v": 12, "corrente_a": 2}}]],
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "A potência dissipada é de 24 W.", "tipo": "fonte", "trechos": ["F2"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "resultado da ferramenta"}]},
    )
    resp = criar(llm).responder(PERGUNTA)   # 12 e 6 vêm da pergunta; o 2 vem do F1
    assert "Das fontes:" in resp.texto and not resp.problemas_criticos


def test_ferramenta_com_erro_nao_e_origem_de_numero(montar):
    _, criar = montar
    llm = LLMComFerramentas(
        rodadas=[[{"nome": "calcular_tudo", "argumentos": {"corrente": 9}}]],
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "A corrente é de 9 A.", "tipo": "fonte", "trechos": ["F1"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "está no F1"}]},
    )
    resp = criar(llm).responder(PERGUNTA)
    assert "Das fontes:" not in resp.texto and any("9" in p for p in resp.problemas_criticos)


def test_valor_que_so_esta_na_web_nao_pega_carona_na_citacao_do_livro(montar):
    _, criar = montar

    def web(q):
        return [ResultadoWeb("W1", "Fórum", "https://forum.exemplo.com/t/1", "Dizem que a corrente é 9 A.")]

    llm = LLMComFerramentas(
        rodadas=[[]],
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "A corrente é de 9 A.", "tipo": "fonte", "trechos": ["T1", "W1"], "critica": True},
            {"texto": "Então o fusível deve ser maior que 9 A.", "tipo": "inferencia", "trechos": ["W1"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "W1 diz 9 A"}]},
    )
    resp = criar(llm, web).responder(PERGUNTA + " Pesquise na internet.")
    assert "Das fontes:" not in resp.texto
    assert any("9" in p and "sem origem" in p for p in resp.problemas_criticos)    # a "fonte" T1+W1
    assert any("SÓ da web" in p for p in resp.problemas_criticos)                   # a inferência só de W1
    # O verificador não recebe o resultado web como se fosse trecho de livro.
    assert "forum" not in llm.mensagens_de("verificacao")[1]["content"].lower()
    assert "Dizem que" not in llm.mensagens_de("verificacao")[1]["content"]
