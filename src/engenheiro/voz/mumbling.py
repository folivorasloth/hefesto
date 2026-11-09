"""Mumbling: o Hefesto "pensa em voz alta" enquanto trabalha.

Cada frase nasce de um EVENTO REAL do barramento (busca feita, trechos
achados, conta feita, verificação começando) e usa os dados desse evento
(nomes das coleções, livros, ferramenta). Se a etapa não aconteceu, não há
evento e não há frase: nada é encenado.

Variação: cada tipo de evento tem algumas formas de dizer, usadas em rodízio
(não aleatório, para os testes e o comportamento serem previsíveis).
"""

from __future__ import annotations

import time
from typing import Callable

from engenheiro.eventos import Evento

_COLECOES = {
    "veiculo": "nos manuais do Gol", "carburacao_etanol": "na parte de carburação", "ignicao": "na parte de ignição",
    "eletrica_automotiva": "na parte de elétrica", "eletronica": "na eletrônica", "mecanica_motor": "na mecânica do motor",
    "sensores": "nos sensores", "esp32": "nas coisas do ESP32", "aquisicao_dados": "em aquisição de dados",
    "caderno_de_bordo": "no seu caderno",
}
_FERRAMENTAS = {
    "lei_de_ohm": "fazendo a conta da lei de Ohm", "potencia": "calculando a potência",
    "divisor_tensao": "conferindo esse divisor de tensão", "escolher_divisor": "procurando resistores que você tem para o divisor",
    "queda_tensao_fio": "calculando a queda de tensão no fio", "dimensionar_fusivel": "vendo o fusível",
    "filtro_rc": "calculando o filtro", "converter_unidade": "convertendo a unidade",
    "verificar_pinos_esp32": "conferindo os pinos do ESP32", "rotacao_por_pulsos": "convertendo pulso em rotação",
    "velocidade_por_rotacao": "calculando a velocidade", "lambda_afr": "vendo a mistura",
    "consultar_inventario": "vendo o que você tem na bancada", "buscar_caderno": "olhando o seu caderno",
    "ler_telemetria": "tentando ler o carro",
}


def _lista(itens: list[str]) -> str:
    itens = list(dict.fromkeys(itens))
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1]


class Mumbler:
    def __init__(self, falar: Callable[[str], None], intervalo_minimo_s: float = 4.0,
                 relogio: Callable[[], float] = time.monotonic) -> None:
        self.falar = falar
        self.intervalo = intervalo_minimo_s
        self.relogio = relogio
        self._ultimo = -1e9
        self._rodizio: dict[str, int] = {}
        self.ativo = True

    def _escolher(self, tipo: str, opcoes: list[str]) -> str:
        i = self._rodizio.get(tipo, 0)
        self._rodizio[tipo] = i + 1
        return opcoes[i % len(opcoes)]

    def frase(self, ev: Evento) -> str | None:
        d = ev.dados
        if ev.tipo == "busca.roteamento":
            lugares = [_COLECOES.get(c, c) for c in d["colecoes"] if c != "caderno_de_bordo"][:2]
            if not lugares:
                return None
            return self._escolher(ev.tipo, [f"Deixa eu ver {_lista(lugares)}...", f"Vou olhar {_lista(lugares)}..."])
        if ev.tipo == "busca.final":
            n = len(d["trechos"])
            if n == 0:
                return "Não achei nada nos livros sobre isso..."
            livros = [t["livro"] for t in d["trechos"]][:2]
            return self._escolher(ev.tipo, [f"Achei {n} trechos, no {_lista(livros)}...",
                                            f"Tem coisa no {_lista(livros)}, deixa eu ler..."])
        if ev.tipo == "ferramenta.chamada":
            return _FERRAMENTAS.get(d["nome"], "fazendo uma conta") + "..."
        if ev.tipo == "web.busca":
            return "Procurando na internet; isso eu vou te passar como não verificado..."
        if ev.tipo == "verificacao.iniciada" and d.get("afirmacoes"):
            return self._escolher(ev.tipo, ["Conferindo a resposta com as fontes...", "Deixa eu conferir isso..."])
        return None

    def __call__(self, ev: Evento) -> None:
        """Ouvinte do barramento."""
        if not self.ativo:
            return
        f = self.frase(ev)
        if not f:
            return
        agora = self.relogio()
        if agora - self._ultimo < self.intervalo:
            return   # falar demais irrita: descarta, não acumula
        self._ultimo = agora
        self.falar(f)
