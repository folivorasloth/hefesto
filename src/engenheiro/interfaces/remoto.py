"""Cliente remoto: conversar (por texto ou voz) com o Hefesto que roda em outra
máquina (o serviço `engenheiro servir` no homelab), pela API HTTP.

Para que serve: o notebook da garagem só ouve e fala. Índice, livros, busca,
reranker, perfil, caderno e memória das conversas ficam no homelab, e o
notebook não precisa de cópia de nada. O "pensar em voz alta" (mumbling)
chega pelo MQTT (tópico npc/<id>/pensamento), que o serviço já publica.

`ConversadorRemoto` tem a mesma cara do `Conversador` local (método `turno`),
então o loop de voz e o chat de texto funcionam com os dois sem mudança.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import httpx

from engenheiro.conversa import Proposta, RespostaTurno
from engenheiro.eventos import Barramento


class ServidorIndisponivel(RuntimeError):
    pass


class ConversadorRemoto:
    def __init__(self, url: str, interlocutor: str = "voz", token: str | None = None, timeout_s: float = 1800) -> None:
        self.url = url.rstrip("/")
        self.interlocutor = interlocutor
        self.token = token if token is not None else os.environ.get("HEFESTO_API_TOKEN", "")
        self.timeout = timeout_s
        st = self.status()
        # O loop de voz espera `eng.bus` e `eng.persona.nome`; aqui eles são
        # só fachada (o barramento real está no servidor).
        self.eng = SimpleNamespace(bus=Barramento(), persona=SimpleNamespace(nome=st.get("nome", "Hefesto")),
                                   llm=True if st.get("ollama") else None)
        self.sessao = SimpleNamespace(id="remota", turnos=[None])   # retomada fica a cargo do servidor
        self.ultimo_status = st

    def _cab(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _req(self, metodo: str, caminho: str, **kw) -> dict:
        try:
            r = httpx.request(metodo, f"{self.url}{caminho}", headers=self._cab(), timeout=self.timeout, **kw)
        except httpx.HTTPError as e:
            raise ServidorIndisponivel(f"não consegui falar com o Hefesto em {self.url}: {e}") from e
        if r.status_code == 401:
            raise ServidorIndisponivel("o servidor recusou o token (defina HEFESTO_API_TOKEN igual ao do servidor)")
        r.raise_for_status()
        return r.json()

    def status(self) -> dict:
        return self._req("GET", "/status")

    def nova_conversa(self) -> str:
        return self._req("POST", "/conversas", params={"interlocutor": self.interlocutor})["conversa"]

    def perfil(self) -> str:
        return self._req("GET", "/perfil")["texto"]

    def turno(self, fala: str) -> RespostaTurno:
        try:
            d = self._req("POST", f"/conversas/{self.interlocutor}/turno", json={"fala": fala})
        except ServidorIndisponivel as e:
            msg = f"Não consegui falar com o servidor do Hefesto. {e}"
            return RespostaTurno(msg, fala="Não consegui falar com o servidor do Hefesto no homelab.")
        self.sessao.id = d.get("conversa", "remota")
        return RespostaTurno(
            texto=d["texto"], rastro_id=d.get("rastro_id"),
            propostas=[Proposta(**p) for p in d.get("propostas", [])], aplicadas=d.get("aplicadas", []),
            fala=d.get("fala", ""), espera_resposta=d.get("espera_resposta", False),
            problemas_criticos=d.get("problemas_criticos", []),
        )


def assinar_pensamentos(host: str, porta: int, topico: str, ao_receber, usuario: str = "", senha: str | None = None):
    """Recebe o mumbling do servidor pelo MQTT e entrega o texto a `ao_receber`.
    Devolve o cliente MQTT (para desligar no fim)."""
    import paho.mqtt.client as mqtt

    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"hefesto-voz-{os.getpid()}")
    if usuario:
        cli.username_pw_set(usuario, senha if senha is not None else os.environ.get("HEFESTO_MQTT_SENHA"))

    def _msg(c, ud, m):
        try:
            ao_receber(json.loads(m.payload).get("texto", ""))
        except (ValueError, AttributeError):
            pass

    cli.on_message = _msg
    cli.on_connect = lambda c, *a, **k: c.subscribe(topico, qos=0)
    cli.connect_async(host, porta, keepalive=30)
    cli.loop_start()
    return cli
