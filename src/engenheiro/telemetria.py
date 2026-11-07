"""Cache da telemetria ao vivo do carro (alimentado pelo MQTT).

O ESP32 do carro publica, por exemplo:
    carro/telemetria/rpm          -> 912            (número puro)
    carro/telemetria/temp_motor   -> {"valor": 88.5, "unidade": "°C"}

O cliente MQTT do Hefesto guarda o último valor de cada sinal com a hora de
chegada, e a ferramenta `ler_telemetria` lê daqui. Um valor velho (mais que
`max_idade_s`) é recusado: dado parado parece dado atual e engana.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass


@dataclass
class Leitura:
    sinal: str
    valor: float | str
    unidade: str | None
    topico: str
    quando: float          # time.time() da chegada


class TelemetriaCache:
    def __init__(self, prefixo: str = "carro/telemetria/", max_idade_s: float = 10.0, relogio=time.time) -> None:
        self.prefixo = prefixo
        self.max_idade_s = max_idade_s
        self.relogio = relogio
        self._dados: dict[str, Leitura] = {}
        self._trava = threading.Lock()

    def atualizar(self, topico: str, payload: bytes | str) -> Leitura | None:
        if not topico.startswith(self.prefixo):
            return None
        sinal = topico[len(self.prefixo):].strip("/")
        texto = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
        unidade = None
        try:
            d = json.loads(texto)
            if isinstance(d, dict):
                valor, unidade = d.get("valor"), d.get("unidade")
            else:
                valor = d
        except json.JSONDecodeError:
            valor = texto.strip()
        leitura = Leitura(sinal, valor, unidade, topico, self.relogio())
        with self._trava:
            self._dados[sinal] = leitura
        return leitura

    def sinais(self) -> list[str]:
        with self._trava:
            return sorted(self._dados)

    def ler(self, sinal: str) -> dict:
        from engenheiro.ferramentas.base import ErroFerramenta

        with self._trava:
            leitura = self._dados.get(sinal)
            disponiveis = sorted(self._dados)
        if leitura is None:
            raise ErroFerramenta(
                f"sem leitura do sinal '{sinal}'. Sinais recebidos: {disponiveis or 'nenhum (o carro não está publicando)'}"
            )
        idade = self.relogio() - leitura.quando
        if idade > self.max_idade_s:
            raise ErroFerramenta(f"a última leitura de '{sinal}' tem {idade:.0f} s (limite {self.max_idade_s:.0f} s): dado velho, não uso")
        return {
            "resultado": {"sinal": sinal, "valor": leitura.valor, "unidade": leitura.unidade, "idade_s": round(idade, 1)},
            "formula": f"última mensagem em {leitura.topico}",
            "notas": ["Leitura ao vivo do sensor: a exatidão depende do circuito de medição e da calibração."],
        }
