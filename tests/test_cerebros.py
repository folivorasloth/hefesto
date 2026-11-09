"""Vários cérebros: prioridade, troca automática, escolha fixa por resposta."""

import json
import sys
from pathlib import Path

import httpx
import pytest

from engenheiro import rastro
from engenheiro.config import ModelosOllama, carregar_config
from engenheiro.llm.cerebros import Cerebro, Cerebros
from engenheiro.llm.ollama import ClienteOllama

sys.path.insert(0, str(Path(__file__).parent))


class Cliente:
    def __init__(self, nome, ligado=True):
        self.nome, self.ligado, self.url = nome, ligado, f"http://{nome}:11434"
        self.usos = []

    def disponivel(self):
        return self.ligado

    def chat(self, modelo, mensagens, **kw):
        self.usos.append(modelo)
        if not self.ligado:
            raise ConnectionError("caiu")
        return {"conteudo": json.dumps({"encontrou": False, "falta": "x", "sugestoes": [], "afirmacoes": [],
                                        "consulta_en": "q", "avaliacoes": []}), "metricas": {}}


def _cer(*clientes):
    return Cerebros([Cerebro(c.nome, c, ModelosOllama(forte=f"forte-{c.nome}", rapido=f"rapido-{c.nome}"))
                     for c in clientes], intervalo_s=0)


def test_prioridade_e_troca_automatica():
    trab, ryzen = Cliente("trabalho"), Cliente("ryzen")
    c = _cer(trab, ryzen)
    assert c.escolher().nome == "trabalho"
    trab.ligado = False
    assert c.escolher().nome == "ryzen"
    ryzen.ligado = False
    assert c.escolher() is None
    trab.ligado = True
    assert c.escolher().nome == "trabalho"      # voltou sozinho


def test_forcar_para_comparar():
    c = _cer(Cliente("trabalho"), Cliente("ryzen"))
    c.forcar("ryzen")
    assert c.escolher().nome == "ryzen"
    with pytest.raises(ValueError):
        c.forcar("nao_existe")


def test_nomes_repetidos_recusados():
    with pytest.raises(ValueError):
        Cerebros([Cerebro("a", Cliente("a"), ModelosOllama()), Cerebro("a", Cliente("b"), ModelosOllama())])


def test_resposta_inteira_usa_um_cerebro_so(tmp_path):
    """Mesmo se o preferido voltar no meio da resposta, ela termina no mesmo cérebro."""
    from test_assistente import RerankerPalavra  # noqa: F401

    from engenheiro.assistente import Engenheiro
    from engenheiro.config import Config
    from engenheiro.eventos import Barramento
    from engenheiro.persona import Persona
    from engenheiro.recuperacao.pipeline import Recuperador
    from engenheiro.recuperacao.reescrita import Glossario
    from engenheiro.seguranca import Seguranca
    from engenheiro.store.db import Banco

    raiz = Path(__file__).parents[1]
    trab, ryzen = Cliente("trabalho", ligado=False), Cliente("ryzen")
    cer = _cer(trab, ryzen)
    cfg = Config(raiz=tmp_path)
    bus = Barramento()
    eng = Engenheiro(cfg, Recuperador(cfg, Banco(":memory:"), Glossario([]), None, None, bus), cer, Persona(),
                     Seguranca.carregar(raiz / "dados_ref" / "seguranca.yaml"), bus)

    original = ryzen.chat

    def chat_que_liga_o_outro(modelo, mensagens, **kw):
        trab.ligado = True                      # o preferido liga no meio da resposta
        return original(modelo, mensagens, **kw)

    ryzen.chat = chat_que_liga_o_outro
    resp = eng.responder("qual a tensão da bobina?")
    assert trab.usos == [] and ryzen.usos and all(m.endswith("-ryzen") for m in ryzen.usos)
    r = rastro.carregar(cfg.caminho(cfg.caminhos.rastros), resp.rastro_id)
    assert r["cerebro"]["nome"] == "ryzen" and r["cerebro"]["forte"] == "forte-ryzen"
    assert eng.cerebro.nome == "trabalho"       # na PRÓXIMA resposta, volta ao preferido


def test_config_de_cerebros(tmp_path):
    c = tmp_path / "config.yaml"
    c.write_text(
        "ollama:\n  url_embeddings: homelab:11434\n  cerebros:\n"
        "    - {nome: trabalho, url: 'http://t:11434', modelos: {forte: 'qwen3:14b'}}\n"
        "    - {nome: ryzen, url: 'r:11434', modelos: {forte: 'qwen3:8b'}}\n", encoding="utf-8")
    cfg = carregar_config(c)
    from engenheiro import fabrica

    cer = fabrica.cerebros(cfg)
    assert [x.nome for x in cer.lista] == ["trabalho", "ryzen"]
    assert cer.lista[1].cliente.url == "http://r:11434" and cer.lista[1].modelos.forte == "qwen3:8b"
    assert cer.lista[1].modelos.rapido == "qwen3:4b"          # herdado do bloco padrão
    assert fabrica.url_embeddings(cfg) == "http://homelab:11434"
    c.write_text("ollama:\n  cerebros:\n    - {nome: x, url: 'x', modelos: {fortissimo: 'a'}}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fortissimo"):
        carregar_config(c)


def test_keep_alive_vai_na_requisicao(monkeypatch):
    enviados = []

    def post(url, json, timeout):
        enviados.append(json)
        return httpx.Response(200, json={"message": {"content": "{}"}, "embeddings": [[0.1]]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    cli = ClienteOllama("http://x:11434", manter_carregado="30m")
    cli.chat("m", [{"role": "user", "content": "oi"}])
    cli.embed("bge-m3", ["oi"])
    assert all(e["keep_alive"] == "30m" for e in enviados)
