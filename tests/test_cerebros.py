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


def test_erro_http_do_ollama_vira_indisponivel(monkeypatch):
    """404 (modelo não baixado) ou 500 (faltou memória) precisam degradar com
    aviso, não estourar HTTPStatusError em quem chama."""
    from engenheiro.llm.ollama import OllamaIndisponivel

    def post(url, json, timeout):
        return httpx.Response(404, json={"error": "model 'bge-m3' not found"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    cli = ClienteOllama("http://x:11434")
    with pytest.raises(OllamaIndisponivel, match="404.*not found.*ollama pull bge-m3"):
        cli.embed("bge-m3", ["oi"])

    def post_lixo(url, json, timeout):
        return httpx.Response(200, text="<html>proxy</html>", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post_lixo)
    with pytest.raises(OllamaIndisponivel, match="não é JSON"):
        cli.embed("bge-m3", ["oi"])


def _ollama_falso(monkeypatch, respostas):
    """Troca o httpx.post por uma fila de respostas; devolve os corpos enviados."""
    enviados = []

    def post(url, json, timeout):
        enviados.append(dict(json))
        status, corpo = respostas.pop(0)
        return httpx.Response(status, json=corpo, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    return enviados


def test_raciocinio_do_modelo_nao_entra_na_resposta(monkeypatch):
    """qwen3 e outros modelos que "pensam" podem devolver <think>...</think>
    dentro do conteúdo: isso quebrava o JSON e seria mostrado e falado."""
    import json as _json

    bruto = '<think>\nO usuário quer {algo}. Vou responder em JSON.\n</think>\n\n{"encontrou": true, "afirmacoes": []}'
    _ollama_falso(monkeypatch, [(200, {"message": {"role": "assistant", "content": bruto}})])
    r = ClienteOllama("http://x:11434").chat("qwen3:14b", [{"role": "user", "content": "oi"}], formato={"type": "object"})
    assert _json.loads(r["conteudo"]) == {"encontrou": True, "afirmacoes": []}
    assert "Vou responder em JSON" in r["raciocinio"]
    assert "<think>" not in r["mensagem"]["content"]      # não volta para o modelo na etapa de ferramentas

    # Sem formato (conversa): o texto sai limpo, sem o raciocínio.
    _ollama_falso(monkeypatch, [(200, {"message": {"content": "<think>hum</think>Bom dia!"}})])
    assert ClienteOllama("http://x:11434").chat("m", [])["conteudo"] == "Bom dia!"

    # Raciocínio cortado antes de fechar (limite de tokens): não vira resposta.
    _ollama_falso(monkeypatch, [(200, {"message": {"content": "<think>pensando sem parar"}})])
    r = ClienteOllama("http://x:11434").chat("m", [])
    assert r["conteudo"] == "" and "pensando sem parar" in r["raciocinio"]

    # Campo próprio do Ollama para o raciocínio também vai para o rastro.
    _ollama_falso(monkeypatch, [(200, {"message": {"content": "{}", "thinking": "raciocínio separado"}})])
    assert ClienteOllama("http://x:11434").chat("m", [])["raciocinio"] == "raciocínio separado"


def test_json_embrulhado_e_recuperado_e_lixo_continua_invalido(monkeypatch):
    import json as _json

    cli = ClienteOllama("http://x:11434")
    for bruto in ('```json\n{"a": 1}\n```', 'Aqui está a resposta:\n{"a": 1}\nEspero ter ajudado.', '{"a": 1}'):
        _ollama_falso(monkeypatch, [(200, {"message": {"content": bruto}})])
        assert _json.loads(cli.chat("m", [], formato={"type": "object"})["conteudo"]) == {"a": 1}, bruto
    # Sem objeto recuperável, o texto volta como veio: quem chama trata como resposta inválida.
    _ollama_falso(monkeypatch, [(200, {"message": {"content": "não sei responder"}})])
    assert cli.chat("m", [], formato={"type": "object"})["conteudo"] == "não sei responder"
    # Sem formato pedido, chaves no texto não são mexidas.
    _ollama_falso(monkeypatch, [(200, {"message": {"content": "use {x} aqui"}})])
    assert cli.chat("m", [])["conteudo"] == "use {x} aqui"


def test_modelo_sem_suporte_a_think_repete_sem_a_opcao(monkeypatch):
    from engenheiro.llm.ollama import OllamaIndisponivel, RespostaInvalida

    enviados = _ollama_falso(monkeypatch, [
        (400, {"error": "registry.ollama.ai/library/llama3 does not support thinking"}),
        (200, {"message": {"content": "ok"}}),
    ])
    assert ClienteOllama("http://x:11434").chat("llama3", [], pensar=False)["conteudo"] == "ok"
    assert "think" in enviados[0] and "think" not in enviados[1]

    # 400 sem ter mandado `think` não é repetido.
    enviados = _ollama_falso(monkeypatch, [(400, {"error": "bad request"})])
    with pytest.raises(OllamaIndisponivel):
        ClienteOllama("http://x:11434").chat("m", [])
    assert len(enviados) == 1

    # Resposta sem "message" é resposta inválida, não KeyError.
    _ollama_falso(monkeypatch, [(200, {"done": True})])
    with pytest.raises(RespostaInvalida):
        ClienteOllama("http://x:11434").chat("m", [])
