"""Vários "cérebros" (máquinas com Ollama) em ordem de preferência.

Exemplo: o notebook do trabalho com o qwen3:14b enquanto você o tem, e o
Ryzen com o qwen3:8b. A cada pergunta, o Hefesto usa o PRIMEIRO da lista que
estiver respondendo. Sair da empresa vira apagar uma entrada do config.

Regras:
- a escolha é fixada no começo de cada resposta e vale até o fim dela: os
  passos de uma mesma resposta (tradução, ferramentas, geração, verificação)
  nunca misturam modelos de máquinas diferentes;
- a disponibilidade de cada cérebro é conferida no máximo a cada
  `intervalo_s` segundos (consultar o Ollama a cada uso custaria tempo);
- `forcar(nome)` restringe a um cérebro só (usado na avaliação para comparar
  modelos/máquinas com as mesmas perguntas).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Cerebro:
    nome: str
    cliente: Any                 # ClienteOllama (ou um LLM falso nos testes)
    modelos: Any                 # ModelosOllama: forte, rapido, embeddings, visao
    _ultima_checagem: float = field(default=-1e9, repr=False)
    _disponivel: bool = field(default=False, repr=False)

    def disponivel(self, intervalo_s: float, relogio: Callable[[], float]) -> bool:
        checar = getattr(self.cliente, "disponivel", None)
        if checar is None:          # cliente sem checagem (testes): sempre disponível
            return True
        agora = relogio()
        if agora - self._ultima_checagem > intervalo_s:
            self._disponivel = bool(checar())
            self._ultima_checagem = agora
        return self._disponivel


class Cerebros:
    def __init__(self, lista: list[Cerebro], intervalo_s: float = 15.0, relogio: Callable[[], float] = time.monotonic) -> None:
        if not lista:
            raise ValueError("nenhum cérebro configurado")
        nomes = [c.nome for c in lista]
        if len(set(nomes)) != len(nomes):
            raise ValueError(f"nomes de cérebro repetidos: {nomes}")
        self.lista = lista
        self.intervalo_s = intervalo_s
        self.relogio = relogio
        self._forcado: str | None = None

    def forcar(self, nome: str | None) -> None:
        if nome is not None and nome not in {c.nome for c in self.lista}:
            raise ValueError(f"cérebro '{nome}' não existe; configurados: {[c.nome for c in self.lista]}")
        self._forcado = nome

    def escolher(self) -> Cerebro | None:
        """O primeiro (em ordem de preferência) que está respondendo agora."""
        for c in self.lista:
            if self._forcado and c.nome != self._forcado:
                continue
            if c.disponivel(self.intervalo_s, self.relogio):
                return c
        return None

    def situacao(self) -> list[dict]:
        """Para o `status`: cada cérebro, se responde e com quais modelos."""
        return [{"nome": c.nome, "url": getattr(c.cliente, "url", None),
                 "disponivel": c.disponivel(0, self.relogio),
                 "forte": c.modelos.forte, "rapido": c.modelos.rapido} for c in self.lista]
