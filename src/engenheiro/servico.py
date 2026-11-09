"""Núcleo do serviço: o Hefesto como "personagem" sempre ligado.

A API HTTP e o MQTT usam este mesmo núcleo. Responsabilidades:

- uma conversa (com memória) por interlocutor: você pela API, você pelo
  MQTT, outro personagem do Divine Machinery... cada um com o seu histórico;
- serializar o uso do modelo: o notebook do LLM só dá conta de uma resposta
  por vez, então pedidos simultâneos esperam na fila (trava);
- avisar o estado (online, pensando, sem_cerebro) para quem quiser mostrar.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from engenheiro.conversa import Conversador, Sessao


class Servico:
    def __init__(self, engenheiro, perfil, caderno, pasta_conversas: Path, telemetria=None) -> None:
        self.eng = engenheiro
        self.perfil = perfil
        self.caderno = caderno
        self.pasta = pasta_conversas
        self.telemetria = telemetria
        self._conversas: dict[str, Conversador] = {}
        # Uma trava para o modelo E para o índice: anotar no caderno reindexa o
        # banco, que não pode ser usado por duas threads ao mesmo tempo.
        self._trava_modelo = threading.Lock()
        self._trava_conversas = threading.Lock()
        self.ouvintes_estado: list[Callable[[str], None]] = []
        self.estado = "online"

    # ------------------------------------------------------------ estado
    @property
    def tem_cerebro(self) -> bool:
        return self.eng.llm is not None

    def _mudar_estado(self, estado: str) -> None:
        self.estado = estado
        for f in self.ouvintes_estado:
            try:
                f(estado)
            except Exception:  # noqa: BLE001 - publicar estado nunca derruba uma resposta
                pass

    def status(self) -> dict:
        c = self.eng.cerebro
        ollama = c is not None
        return {
            "nome": self.eng.persona.nome,
            "id": self.eng.cfg.assistente.id,
            "estado": self.estado if ollama else "sem_cerebro",
            "ollama": ollama,
            "cerebro": {"nome": c.nome, "forte": c.modelos.forte, "rapido": c.modelos.rapido} if c else None,
            "conversas_ativas": len(self._conversas),
            "telemetria": self.telemetria.sinais() if self.telemetria else [],
            "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    # ------------------------------------------------------------ conversas
    def conversa(self, chave: str) -> Conversador:
        """Conversa do interlocutor `chave` (ex.: "api", "mqtt:joao", "mqtt:grilo").
        Retoma a última sessão salva desse interlocutor, se existir."""
        with self._trava_conversas:
            if chave not in self._conversas:
                pasta = self.pasta / _seguro(chave)
                sessao = Sessao.ultima(pasta) or Sessao.nova()
                self._conversas[chave] = Conversador(self.eng, self.perfil, self.caderno, pasta, sessao)
            return self._conversas[chave]

    def nova_conversa(self, chave: str) -> str:
        with self._trava_conversas:
            pasta = self.pasta / _seguro(chave)
            conv = Conversador(self.eng, self.perfil, self.caderno, pasta, Sessao.nova())
            self._conversas[chave] = conv
            return conv.sessao.id

    def turno(self, chave: str, fala: str) -> dict:
        conv = self.conversa(chave)
        with self._trava_modelo:
            self._mudar_estado("pensando")
            try:
                r = conv.turno(fala)
            finally:
                self._mudar_estado("online")
        d = asdict(r)
        d["conversa"] = conv.sessao.id
        return d

    def anotar(self, texto: str, titulo: str | None = None, tags: list[str] | None = None):
        """Anotação no caderno, na mesma fila do modelo (ela reindexa o banco)."""
        with self._trava_modelo:
            return self.caderno.registrar(texto, titulo, tags or [])

    def perguntar(self, pergunta: str) -> dict:
        """Pergunta isolada, sem memória (como `engenheiro perguntar`)."""
        with self._trava_modelo:
            self._mudar_estado("pensando")
            try:
                r = self.eng.responder(pergunta)
            finally:
                self._mudar_estado("online")
        return asdict(r)


def _seguro(chave: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in chave)[:60] or "padrao"

