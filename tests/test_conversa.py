"""Modo conversa: o cenário "Hefesto, como eu identifico o tipo de ignição?"."""

import json
from pathlib import Path

import pytest

from engenheiro import rastro
from engenheiro.assistente import Engenheiro
from engenheiro.caderno import Caderno
from engenheiro.config import Config
from engenheiro.conversa import (PROMPT_FATOS, PROMPT_REESCRITA, Conversador, Sessao, interpretar_confirmacao,
                                 remover_ativacao, validar_fato)
from engenheiro.eventos import Barramento
from engenheiro.ferramentas import criar_registro
from engenheiro.geracao import prompts
from engenheiro.perfil import Perfil
from engenheiro.persona import Persona
from engenheiro.recuperacao.pipeline import Recuperador
from engenheiro.recuperacao.reescrita import Glossario
from engenheiro.seguranca import Seguranca
from engenheiro.store.db import Banco

RAIZ = Path(__file__).parents[1]


class LLMConversa:
    def __init__(self, respostas, reescritas=None, fatos=None):
        self.respostas = list(respostas)
        self.reescritas = list(reescritas or [])
        self.fatos = list(fatos or [])
        self.log: list[tuple[str, str, list]] = []

    def chat(self, modelo, mensagens, formato=None, opcoes=None, pensar=None, ferramentas=None):
        s = mensagens[0]["content"]
        if PROMPT_REESCRITA in s:
            tipo, out = "reescrita", {"pergunta": self.reescritas.pop(0)}
        elif s.startswith(PROMPT_FATOS):
            tipo, out = "fatos", {"fatos": self.fatos.pop(0) if self.fatos else []}
        elif prompts.TRADUCAO in s:
            tipo, out = "traducao", {"consulta_en": "ignition type"}
        elif prompts.VERIFICADOR in s:
            tipo, out = "verificacao", {"avaliacoes": []}
        elif ferramentas is not None:
            tipo, out = "ferramentas", None
            self.log.append((tipo, modelo, mensagens))
            return {"conteudo": "PRONTO", "chamadas": [], "mensagem": {"role": "assistant", "content": "PRONTO"}, "metricas": {}}
        else:
            tipo, out = "resposta", self.respostas.pop(0)
        self.log.append((tipo, modelo, mensagens))
        return {"conteudo": json.dumps(out), "metricas": {}}

    def tipos(self):
        return [t for t, _, _ in self.log]

    def ultima(self, tipo):
        return [x for x in self.log if x[0] == tipo][-1]


@pytest.fixture
def conversa(tmp_path):
    cfg = Config(raiz=tmp_path)
    perfil_arq = tmp_path / "perfil_veiculo.yaml"
    perfil_arq.write_text((RAIZ / "perfil_veiculo.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    perfil = Perfil(perfil_arq)

    def criar(llm):
        bus = Barramento()
        rec = Recuperador(cfg, Banco(":memory:"), Glossario([]), None, None, bus)   # base VAZIA, como hoje
        eng = Engenheiro(cfg, rec, llm, Persona.carregar(RAIZ / "persona" / "engenheiro.yaml"),
                         Seguranca.carregar(RAIZ / "dados_ref" / "seguranca.yaml"), bus,
                         perfil.para_prompt(), criar_registro(RAIZ, bus), None, perfil.valores_confirmados())
        return Conversador(eng, perfil, Caderno(tmp_path / "caderno"), tmp_path / "conversas")

    return cfg, perfil, criar


GERAL_1 = {"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
    {"texto": "Abra o capô e localize o distribuidor, a peça de onde saem os cabos de vela.", "tipo": "geral", "trechos": [], "critica": False},
    {"texto": "Olhe o conector na lateral do distribuidor e conte quantos fios entram nele.", "tipo": "geral", "trechos": [], "critica": True},
], "pergunta_ao_usuario": "Quantos fios entram no conector do distribuidor?"}

GERAL_2 = {"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
    {"texto": "Um conector com vários fios no distribuidor costuma indicar ignição eletrônica com sensor.", "tipo": "geral", "trechos": [], "critica": False},
], "pergunta_ao_usuario": "Tem algum módulo de ignição separado perto da bobina?"}


def test_cenario_identificar_ignicao_em_tres_turnos(conversa):
    cfg, perfil, criar = conversa
    llm = LLMConversa(
        respostas=[GERAL_1, GERAL_2],
        reescritas=["O conector do distribuidor do Gol tem 3 fios. O que isso indica sobre o tipo de ignição?"],
        fatos=[[
            {"campo": "ignicao.fios_conector", "valor": "3 fios", "tipo": "observacao", "trecho_da_fala": "tem 3 fios no conector"},
            {"campo": "ignicao.tipo", "valor": "sensor Hall", "tipo": "observacao", "trecho_da_fala": "tem 3 fios"},
            {"campo": "carburador.modelo", "valor": "Weber 460", "tipo": "observacao", "trecho_da_fala": "o carburador é Weber 460"},
        ]],
    )
    conv = criar(llm)

    # --- turno 1: pergunta de orientação, base vazia
    r1 = conv.turno("Hefesto, como eu identifico o tipo de ignição?")
    assert "Conhecimento geral" in r1.texto and "distribuidor" in r1.texto
    assert r1.texto.rstrip().endswith("➜ Quantos fios entram no conector do distribuidor?")
    # Orientação no modo conversa: modelo RÁPIDO e sem etapa de ferramentas.
    assert "ferramentas" not in llm.tipos()
    assert llm.ultima("resposta")[1] == cfg.ollama.modelos.rapido
    # A orientação sobre ignição NÃO foi removida só por ser assunto "crítico":
    assert "conte quantos fios" in r1.texto

    # --- turno 2: resposta curta; ele entende pelo histórico
    r2 = conv.turno("tem 3 fios no conector")
    _, _, msgs = llm.ultima("resposta")
    assert "PERGUNTA DO USUÁRIO:\nO conector do distribuidor do Gol tem 3 fios" in msgs[1]["content"]
    assert "CONVERSA ATÉ AQUI" in msgs[0]["content"] and "como eu identifico o tipo de ignição" in msgs[0]["content"]
    # Propostas: o fato literal entra como confirmado; a interpretação, como suposição;
    # o fato que você não disse (Weber 460) é descartado pelo código.
    assert [(p.campo, p.status) for p in r2.propostas] == [
        ("observacoes.fios_conector", "confirmado"), ("ignicao.tipo", "suposicao")]
    assert "Quer que eu registre isso?" in r2.texto and "Weber 460" not in r2.texto
    rr = rastro.carregar(cfg.caminho(cfg.caminhos.rastros), r2.rastro_id)
    assert rr["fala_original"] == "tem 3 fios no conector" and rr["pergunta_reescrita"].startswith("O conector")

    # --- turno 3: "sim" grava no perfil, sem chamar o modelo
    n = len(llm.log)
    r3 = conv.turno("sim")
    assert len(llm.log) == n
    assert "Anotado" in r3.texto
    novo = Perfil(perfil.caminho)
    assert novo.valor_confirmado("observacoes.fios_conector") == "3 fios"
    assert novo.campo("ignicao.tipo")["status"] == "suposicao"            # interpretação NÃO virou fato
    assert "observacoes.fios_conector: 3 fios" in conv.eng.perfil_txt   # a próxima resposta já sabe

    # A sessão foi salva e pode ser retomada.
    retomada = Sessao.ultima(conv.pasta)
    assert retomada.id == conv.sessao.id and len(retomada.turnos) == 6


def test_nao_descarta_propostas(conversa):
    _, perfil, criar = conversa
    llm = LLMConversa(respostas=[GERAL_2], fatos=[[{"campo": "x", "valor": "3", "tipo": "observacao", "trecho_da_fala": "3 fios"}]])
    conv = criar(llm)
    conv.turno("o conector tem 3 fios")
    r = conv.turno("não")
    assert "não anotei" in r.texto and conv.sessao.pendentes == []
    assert Perfil(perfil.caminho).campo("observacoes.x") is None


def test_medicao_vai_para_o_caderno(conversa, tmp_path):
    _, _, criar = conversa
    llm = LLMConversa(respostas=[GERAL_2], fatos=[[{"campo": "eletrica.bateria", "valor": "12,6 V", "tipo": "medicao",
                                                     "trecho_da_fala": "medi 12,6 V na bateria"}]])
    conv = criar(llm)
    r = conv.turno("medi 12,6 V na bateria agora")
    assert r.propostas[0].tipo == "caderno"
    conv.turno("sim")
    assert conv.caderno.buscar("12,6")[0].texto == "medi 12,6 V na bateria"


def test_valor_tecnico_vai_para_o_modelo_forte_mesmo_na_conversa(conversa):
    cfg, _, criar = conversa
    llm = LLMConversa(respostas=[{"encontrou": False, "falta": "Sem fonte.", "sugestoes": [], "afirmacoes": []}])
    criar(llm).turno("qual a tensão no sensor hall?")
    assert llm.ultima("resposta")[1] == cfg.ollama.modelos.forte
    assert "ferramentas" in llm.tipos()


def test_conhecimento_geral_com_valor_ou_instrucao_e_removido(conversa):
    _, _, criar = conversa
    llm = LLMConversa(respostas=[{"encontrou": True, "falta": "", "sugestoes": [], "afirmacoes": [
        {"texto": "O sensor Hall trabalha com 12 V.", "tipo": "geral", "trechos": [], "critica": True},
        {"texto": "Desconecte o conector e meça a resistência.", "tipo": "geral", "trechos": [], "critica": False},
        {"texto": "O distribuidor fica na lateral do motor.", "tipo": "geral", "trechos": [], "critica": False},
    ]}])
    r = criar(llm).turno("onde fica o distribuidor?")
    principal, removidas = r.texto.split("Removidas pelo verificador")
    assert "O distribuidor fica na lateral do motor." in principal
    assert "12 V" not in principal and "Desconecte" not in principal
    assert "12 V" in removidas and "Desconecte" in removidas


# ------------------------------------------------------------------ funções puras
def test_palavra_de_ativacao():
    assert remover_ativacao("Hefesto, como eu identifico o tipo de ignição?") == "como eu identifico o tipo de ignição?"
    assert remover_ativacao("ei hefesto! tudo bem") == "tudo bem"
    assert remover_ativacao("o que o Hefesto acha?") == "o que o Hefesto acha?"


def test_confirmacao_com_continuacao():
    assert interpretar_confirmacao("Sim, e agora vejo um fio verde") == ("sim", "e agora vejo um fio verde")
    assert interpretar_confirmacao("não") == ("nao", "")
    assert interpretar_confirmacao("tem 3 fios") == (None, "tem 3 fios")


def test_fato_inventado_e_descartado():
    assert validar_fato({"campo": "a.b", "valor": "Weber", "tipo": "observacao", "trecho_da_fala": "é weber"},
                        "o carro é azul", {"a.b"}, "2026-11-07", "s") is None


def test_aviso_de_seguranca_completo_uma_vez_e_depois_lembrete(conversa):
    _, _, criar = conversa
    conv = criar(LLMConversa(respostas=[GERAL_1, GERAL_2], reescritas=["E a bobina, onde fica na ignição?"]))
    r1 = conv.turno("como eu identifico o tipo de ignição?")
    r2 = conv.turno("e a bobina?")
    assert "alta tensão" in r1.texto
    assert "alta tensão" not in r2.texto and "Continuam valendo os avisos que já dei nesta conversa sobre: ignição" in r2.texto
    # Observação do sistema ("sem embedder") só na primeira resposta.
    assert "Sem embedder" in r1.texto and "Sem embedder" not in r2.texto
    # Uma conversa NOVA volta a dar o aviso completo.
    conv.sessao = Sessao.nova()
    conv.eng.llm.respostas.append(GERAL_1)
    assert "alta tensão" in conv.turno("como eu identifico o tipo de ignição?").texto
