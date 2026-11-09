"""Fase 4: avaliação completa."""

import json
from pathlib import Path

import pytest

from engenheiro.avaliacao import (Cenario, Pergunta, avaliar_cenarios, avaliar_completo, carregar_cenarios,
                                  comparar, fato_presente)
from engenheiro.conversa import RespostaTurno

RAIZ = Path(__file__).parents[1]


@pytest.mark.parametrize("fato, texto, esperado", [
    ("17,3 N·m", "Na etapa 1 aperte a 17.3 N.m.", True),
    ("corrente de 0,15 A", "A corrente é de 150 mA.", True),          # unidade convertida
    ("corrente de 0,15 A", "A tensão é de 0,15 V.", False),            # grandeza errada
    ("911 rpm", "Ajuste a marcha lenta para 911 rpm.", True),
    ("911 rpm", "Ajuste a marcha lenta para 900 rpm.", False),
    ("local ventilado", "Trabalhe em LOCAL VENTILADO.", True),
    ("não tem resistor de pull-up", "O GPIO34 não tem resistor de pull-up interno.", True),
])
def test_fato_presente(fato, texto, esperado):
    assert fato_presente(fato, texto) is esperado


def test_cenarios_do_repositorio_carregam():
    cs = carregar_cenarios(RAIZ / "eval" / "cenarios.yaml")
    assert {c.id for c in cs} >= {"guiado-ignicao", "honestidade-fora-da-base"}


def test_avaliar_cenarios_aponta_a_falha_certa():
    class ConvFalso:
        def __init__(self):
            self.respostas = [
                RespostaTurno("Olhe o distribuidor. ➜ Quantos fios?", espera_resposta=True),
                RespostaTurno("Ok.", propostas=[]),          # deveria ter proposto 1
            ]

        def turno(self, fala):
            return self.respostas.pop(0)

    c = Cenario("x", [
        {"fala": "como identifico a ignição?", "contem": ["Distribuidor"], "nao_contem": ["volts"], "pergunta_de_volta": True},
        {"fala": "tem 3 fios", "propostas": 1},
    ])
    res = avaliar_cenarios(ConvFalso, [c])
    assert res["metricas"]["cenarios_ok"] == 0.0
    assert res["itens"][0]["falhas"] == ["turno 2: 0 propostas (esperado 1)"]


def test_comparacao_de_cenarios():
    antes = {"execucao": "A", "metricas": {"cenarios_ok": 1.0}, "itens": [{"id": "x", "ok": True}]}
    agora = {"execucao": "B", "metricas": {"cenarios_ok": 0.0}, "itens": [{"id": "x", "ok": False}]}
    assert comparar(agora, antes)["pioraram"] == ["x"]


def test_avaliar_completo_junta_busca_e_resposta(tmp_path):
    # Reaproveita o ambiente roteirizado da fase 2.
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from test_assistente import LLMRoteirizado, RerankerPalavra, TRECHOS  # noqa: F401

    from engenheiro.assistente import Engenheiro
    from engenheiro.config import Config
    from engenheiro.eventos import Barramento
    from engenheiro.persona import Persona
    from engenheiro.recuperacao.pipeline import Recuperador
    from engenheiro.recuperacao.reescrita import Glossario
    from engenheiro.seguranca import Seguranca
    from engenheiro.store.db import Banco, DadosDocumento

    cfg = Config(raiz=tmp_path)
    b = Banco(":memory:")
    for col, ts in TRECHOS.items():
        b.substituir_documento(DadosDocumento(f"{col}/livro.pdf", col, "s", "d", "L", f"Livro-{col}", deslocamento_paginas=0),
                               ts, ["pt"] * len(ts))
    llm = LLMRoteirizado(
        resposta={"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
            {"texto": "Na etapa 1, aperte a 17,3 N·m.", "tipo": "fonte", "trechos": ["T1"], "critica": True}]},
        verificacao={"avaliacoes": [{"id": "A1", "veredito": "suporta", "justificativa": "ok"}]},
    )
    bus = Barramento()
    eng = Engenheiro(cfg, Recuperador(cfg, b, Glossario([]), None, RerankerPalavra(), bus), llm, Persona(),
                     Seguranca.carregar(RAIZ / "dados_ref" / "seguranca.yaml"), bus)
    p = Pergunta("torque", "Qual o torque do cabeçote?", [{"arquivo": "veiculo/livro.pdf"}], ["17.3 N.m"], critica=True)
    res = avaliar_completo(eng, [p], cfg.caminho(cfg.caminhos.rastros), 6)
    m = res["metricas"]
    assert m["busca.acerto@6"] == 1.0 and m["resposta.fatos_chave"] == 1.0
    assert m["resposta.citacao_na_fonte_esperada"] == 1.0 and m["resposta.fonte_aprovada"] == 1.0
    assert res["itens"][0]["recuperacao"]["acertou"] is True
    json.dumps(res)  # o relatório precisa ser serializável
