"""MQTT: o Hefesto como personagem do Divine Machinery.

Tópicos (padrão; `{id}` = assistente.id = "engenheiro"):

  ENTRADA  joao/fala/engenheiro      o que você (ou um personagem) diz a ele
  SAÍDA    npc/engenheiro/fala       o que ele responde
  ESTADO   npc/engenheiro/status     online | pensando | sem_cerebro | offline (retido;
                                     "offline" também é o Last Will: o broker publica
                                     sozinho se o Hefesto cair sem se despedir)
  MUMBLING npc/engenheiro/pensamento "deixa eu ver na parte de ignição..." (opcional)
  CARRO    carro/telemetria/#        valores ao vivo, guardados para ler_telemetria

Mensagem de ENTRADA: texto puro ("onde fica a bobina?") ou JSON:
  {"texto": "...", "id": "abc123", "de": "joao"}
  - "de" separa as conversas (cada interlocutor tem a sua memória);
  - "id" volta como "em_resposta_a", para quem perguntou casar a resposta.

Mensagem de SAÍDA (JSON):
  {"de": "engenheiro", "nome": "Hefesto", "para": "joao", "em_resposta_a": "abc123",
   "texto": "<versão falada, curta>", "texto_completo": "<texto da tela>",
   "rastro_id": "...", "espera_resposta": true,
   "problemas_criticos": [], "conversa": "...", "quando": "2026-11-07T15:30:00"}

O processamento roda numa thread própria: o laço de rede do MQTT nunca fica
parado esperando o modelo (senão o broker derrubaria a conexão).
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time

from engenheiro.servico import Servico

log = logging.getLogger(__name__)


def interpretar_entrada(payload: bytes | str) -> dict:
    """Aceita texto puro ou JSON {"texto", "id", "de"}."""
    texto = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
    texto = texto.strip()
    try:
        d = json.loads(texto)
    except json.JSONDecodeError:
        d = None
    if isinstance(d, dict):
        return {"texto": str(d.get("texto") or d.get("fala") or "").strip(), "id": d.get("id"),
                "de": str(d.get("de") or "joao")}
    return {"texto": texto, "id": None, "de": "joao"}


class ClienteMqtt:
    def __init__(self, servico: Servico, host: str, porta: int = 1883, usuario: str = "", senha: str | None = None,
                 qos: int = 1, topicos: dict | None = None, id_personagem: str = "engenheiro") -> None:
        import paho.mqtt.client as mqtt

        self.servico = servico
        self.host, self.porta, self.qos = host, porta, qos
        self.id = id_personagem
        t = topicos or {}
        fmt = lambda x: x.format(id=id_personagem)  # noqa: E731
        self.t_fala = fmt(t.get("fala", "npc/{id}/fala"))
        self.t_status = fmt(t.get("status", "npc/{id}/status"))
        self.t_entrada = fmt(t.get("entrada", "joao/fala/{id}"))
        self.t_pensamento = fmt(t.get("pensamento", "npc/{id}/pensamento")) if t.get("pensamento", "x") else ""
        self.t_telemetria = t.get("telemetria", "carro/telemetria/")
        self._fila: queue.Queue[dict | None] = queue.Queue()
        self._parar = threading.Event()
        self.conectado = threading.Event()

        self.cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"npc-{id_personagem}")
        senha = senha if senha is not None else os.environ.get("HEFESTO_MQTT_SENHA")
        if usuario:
            self.cli.username_pw_set(usuario, senha)
        # Last Will: se a conexão cair sem despedida, o broker anuncia "offline".
        self.cli.will_set(self.t_status, self._json_status("offline"), qos=1, retain=True)
        self.cli.on_connect = self._ao_conectar
        self.cli.on_message = self._ao_receber
        self.cli.on_disconnect = lambda *a, **k: self.conectado.clear()
        self.cli.reconnect_delay_set(min_delay=1, max_delay=60)

        servico.ouvintes_estado.append(self.publicar_status)
        if self.t_pensamento:
            from engenheiro.voz.mumbling import Mumbler

            servico.eng.bus.assinar(Mumbler(self._publicar_pensamento, intervalo_minimo_s=2.0))

    # ------------------------------------------------------------ publicação
    def _json_status(self, estado: str) -> str:
        return json.dumps({"estado": estado, "nome": self.servico.eng.persona.nome, "id": self.id,
                           "quando": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False)

    def publicar_status(self, estado: str | None = None) -> None:
        estado = estado or ("online" if self.servico.tem_cerebro else "sem_cerebro")
        if estado == "online" and not self.servico.tem_cerebro:
            estado = "sem_cerebro"
        self.cli.publish(self.t_status, self._json_status(estado), qos=1, retain=True)

    def _publicar_pensamento(self, frase: str) -> None:
        self.cli.publish(self.t_pensamento, json.dumps({"de": self.id, "texto": frase}, ensure_ascii=False), qos=0)

    # ------------------------------------------------------------ callbacks
    def _ao_conectar(self, cli, userdata, flags, reason_code, properties=None) -> None:
        if reason_code.is_failure:
            log.error("MQTT recusou a conexão: %s", reason_code)
            return
        cli.subscribe(self.t_entrada, qos=self.qos)
        if self.t_telemetria and self.servico.telemetria is not None:
            cli.subscribe(self.t_telemetria + "#", qos=0)
        self.publicar_status()
        self.conectado.set()

    def _ao_receber(self, cli, userdata, msg) -> None:
        if self.servico.telemetria is not None and msg.topic.startswith(self.t_telemetria):
            self.servico.telemetria.atualizar(msg.topic, msg.payload)
            return
        if msg.topic == self.t_entrada:
            entrada = interpretar_entrada(msg.payload)
            if entrada["texto"]:
                self._fila.put(entrada)   # nunca processa aqui: este é o laço de rede

    # ------------------------------------------------------------ trabalho
    def _trabalhar(self) -> None:
        while not self._parar.is_set():
            entrada = self._fila.get()
            if entrada is None:
                return
            try:
                r = self.servico.turno(f"mqtt:{entrada['de']}", entrada["texto"])
                saida = {
                    "de": self.id, "nome": self.servico.eng.persona.nome, "para": entrada["de"],
                    "em_resposta_a": entrada["id"], "texto": r.get("fala") or r["texto"], "texto_completo": r["texto"],
                    "rastro_id": r.get("rastro_id"), "espera_resposta": r.get("espera_resposta", False),
                    "problemas_criticos": r.get("problemas_criticos", []), "conversa": r.get("conversa"),
                    "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            except Exception as e:  # noqa: BLE001 - erro numa mensagem não derruba o personagem
                log.exception("erro ao responder via MQTT")
                saida = {"de": self.id, "nome": self.servico.eng.persona.nome, "para": entrada["de"],
                         "em_resposta_a": entrada["id"], "texto": "Tive um erro interno ao montar a resposta.",
                         "erro": repr(e), "quando": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self.cli.publish(self.t_fala, json.dumps(saida, ensure_ascii=False, default=str), qos=self.qos)

    def iniciar(self) -> None:
        self.cli.connect_async(self.host, self.porta, keepalive=30)
        self.cli.loop_start()
        threading.Thread(target=self._trabalhar, daemon=True, name="mqtt-trabalho").start()

    def parar(self) -> None:
        """Despedida limpa: publica offline (retido) antes de desconectar."""
        self._parar.set()
        self._fila.put(None)
        if self.conectado.is_set():
            self.cli.publish(self.t_status, self._json_status("offline"), qos=1, retain=True).wait_for_publish(5)
        self.cli.disconnect()
        self.cli.loop_stop()
