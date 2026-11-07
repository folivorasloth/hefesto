"""Fase 6: API HTTP e MQTT (este último contra um Mosquitto de verdade)."""

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_conversa import GERAL_1, GERAL_2, LLMConversa, conversa  # noqa: E402,F401  (fixture reaproveitada)

from engenheiro.ferramentas import criar_registro  # noqa: E402
from engenheiro.interfaces.mqtt import interpretar_entrada  # noqa: E402
from engenheiro.servico import Servico  # noqa: E402
from engenheiro.telemetria import TelemetriaCache  # noqa: E402

RAIZ = Path(__file__).parents[1]


@pytest.fixture
def servico(conversa, tmp_path):
    cfg, perfil, criar = conversa

    def montar(llm):
        conv = criar(llm)
        tele = TelemetriaCache()
        conv.eng.registro = criar_registro(RAIZ, conv.eng.bus, conv.caderno, perfil, tele)
        return Servico(conv.eng, perfil, conv.caderno, tmp_path / "conversas", tele)

    return cfg, montar


# ------------------------------------------------------------------ API
@pytest.fixture
def api(servico):
    from fastapi.testclient import TestClient

    from engenheiro.interfaces.api import criar_app

    cfg, montar = servico
    svc = montar(LLMConversa(respostas=[GERAL_1, GERAL_2], reescritas=["E agora?"]))
    return svc, TestClient(criar_app(svc, token="segredo"))


H = {"Authorization": "Bearer segredo"}


def test_status_e_publico_o_resto_exige_token(api):
    _, c = api
    assert c.get("/status").json()["nome"] == "Hefesto"
    assert c.post("/perguntar", json={"pergunta": "x"}).status_code == 401
    assert c.post("/perguntar", json={"pergunta": "x"}, headers={"Authorization": "Bearer errado"}).status_code == 401


def test_conversa_pela_api_tem_memoria(api):
    svc, c = api
    r1 = c.post("/conversas/joao/turno", json={"fala": "Hefesto, como eu identifico o tipo de ignição?"}, headers=H).json()
    assert r1["espera_resposta"] and "distribuidor" in r1["fala"] and r1["rastro_id"]
    r2 = c.post("/conversas/joao/turno", json={"fala": "tem 3 fios"}, headers=H).json()
    assert r2["conversa"] == r1["conversa"]                     # mesma conversa
    rastro = c.get(f"/rastro/{r2['rastro_id']}", headers=H).json()
    assert rastro["pergunta_reescrita"] == "E agora?" and "CONVERSA ATÉ AQUI" in rastro["historico"]


def test_rastro_valida_o_id(api):
    _, c = api
    assert c.get("/rastro/..%2F..%2Fetc", headers=H).status_code == 404
    assert c.get("/rastro/20260101T000000Z-abcdef", headers=H).status_code == 404


def test_caderno_perfil_e_ferramentas_pela_api(api):
    _, c = api
    r = c.post("/caderno", json={"texto": "Medi 12,6 V na bateria.", "tags": ["bateria"]}, headers=H).json()
    assert r["citacao"].startswith("[Caderno ")
    assert c.get("/caderno", params={"termo": "bateria"}, headers=H).json()[0]["texto"] == "Medi 12,6 V na bateria."
    assert "CONFIRMADO" in c.get("/perfil", headers=H).json()["texto"]
    ok = c.post("/ferramentas/lei_de_ohm", json={"argumentos": {"tensao_v": 12, "resistencia_ohm": 6}}, headers=H).json()
    assert ok["saida"]["resultado"]["corrente_a"] == 2
    assert c.post("/ferramentas/lei_de_ohm", json={"argumentos": {}}, headers=H).status_code == 422
    assert c.post("/ferramentas/nao_existe", json={}, headers=H).status_code == 404


# ------------------------------------------------------------------ MQTT (entrada)
def test_entrada_texto_puro_ou_json():
    assert interpretar_entrada(b"onde fica a bobina?") == {"texto": "onde fica a bobina?", "id": None, "de": "joao"}
    assert interpretar_entrada('{"texto": "oi", "id": "a1", "de": "grilo"}') == {"texto": "oi", "id": "a1", "de": "grilo"}


# ------------------------------------------------------------------ MQTT real
def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mosquitto(tmp_path):
    binario = shutil.which("mosquitto") or "/usr/sbin/mosquitto"
    if not Path(binario).exists():
        pytest.skip("mosquitto não instalado")
    porta = _porta_livre()
    conf = tmp_path / "m.conf"
    conf.write_text(f"listener {porta} 127.0.0.1\nallow_anonymous true\n")
    proc = subprocess.Popen([binario, "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", porta), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield porta
    proc.terminate()
    proc.wait(5)


class Ouvinte:
    """Cliente MQTT que guarda tudo o que chega em npc/engenheiro/#."""

    def __init__(self, porta):
        import paho.mqtt.client as mqtt

        self.msgs: list[tuple[str, dict]] = []
        self.cond = threading.Condition()
        self.cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="teste-ouvinte")
        self.cli.on_message = self._msg
        self.cli.connect("127.0.0.1", porta)
        self.cli.subscribe("npc/engenheiro/#", qos=1)
        self.cli.loop_start()

    def _msg(self, cli, ud, m):
        with self.cond:
            self.msgs.append((m.topic, json.loads(m.payload)))
            self.cond.notify_all()

    def esperar(self, pred, timeout=15):
        fim = time.time() + timeout
        with self.cond:
            while time.time() < fim:
                achados = [x for x in self.msgs if pred(*x)]
                if achados:
                    return achados[-1]
                self.cond.wait(0.2)
        raise AssertionError(f"mensagem não chegou; recebidas: {self.msgs}")

    def publicar(self, topico, payload, retain=False):
        self.cli.publish(topico, payload, qos=1, retain=retain).wait_for_publish(5)

    def fechar(self):
        self.cli.loop_stop()
        self.cli.disconnect()


def test_mqtt_conversa_status_telemetria_e_last_will(servico, mosquitto):
    from engenheiro.interfaces.mqtt import ClienteMqtt

    _, montar = servico
    svc = montar(LLMConversa(respostas=[GERAL_1, GERAL_2], reescritas=["E agora?"]))
    ouvinte = Ouvinte(mosquitto)
    cli = ClienteMqtt(svc, "127.0.0.1", mosquitto)
    cli.iniciar()
    try:
        assert cli.conectado.wait(10)
        ouvinte.esperar(lambda t, d: t == "npc/engenheiro/status" and d["estado"] == "online")

        # Pergunta em JSON, de você
        ouvinte.publicar("joao/fala/engenheiro", json.dumps({"texto": "Hefesto, como eu identifico o tipo de ignição?",
                                                              "id": "p1", "de": "joao"}))
        _, fala = ouvinte.esperar(lambda t, d: t == "npc/engenheiro/fala" and d.get("em_resposta_a") == "p1")
        assert fala["para"] == "joao" and fala["nome"] == "Hefesto" and "distribuidor" in fala["texto"]
        assert fala["espera_resposta"] is True and fala["rastro_id"]
        ouvinte.esperar(lambda t, d: t == "npc/engenheiro/status" and d["estado"] == "pensando")

        # Texto puro de outro personagem: conversa separada
        ouvinte.publicar("joao/fala/engenheiro", "tem 3 fios")
        ouvinte.esperar(lambda t, d: t == "npc/engenheiro/fala" and d.get("para") == "joao" and d.get("em_resposta_a") is None)
        assert len(svc._conversas) == 1  # "joao" nos dois casos

        # Telemetria ao vivo chega ao cache da ferramenta
        ouvinte.publicar("carro/telemetria/rpm", "912")
        for _ in range(50):
            if "rpm" in svc.telemetria.sinais():
                break
            time.sleep(0.1)
        assert svc.eng.registro.executar("ler_telemetria", {"sinal": "rpm"}).saida["resultado"]["valor"] == 912

        # Last Will: queda sem despedida -> o BROKER publica "offline"
        n_antes = len(ouvinte.msgs)
        cli.cli.socket().close()
        ouvinte.esperar(lambda t, d: t == "npc/engenheiro/status" and d["estado"] == "offline"
                        and ouvinte.msgs.index((t, d)) >= n_antes)
    finally:
        cli.parar()
        ouvinte.fechar()


def test_mqtt_despedida_limpa_deixa_offline_retido(servico, mosquitto):
    from engenheiro.interfaces.mqtt import ClienteMqtt

    _, montar = servico
    cli = ClienteMqtt(montar(LLMConversa(respostas=[])), "127.0.0.1", mosquitto)
    cli.iniciar()
    assert cli.conectado.wait(10)
    cli.parar()
    # Um cliente novo recebe o status RETIDO: offline.
    ouvinte = Ouvinte(mosquitto)
    try:
        ouvinte.esperar(lambda t, d: t == "npc/engenheiro/status" and d["estado"] == "offline")
    finally:
        ouvinte.fechar()
