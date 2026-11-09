"""Barramento de eventos do pipeline.

Cada etapa real (busca, fusão, reranking, chamada de ferramenta, verificação)
publica um evento aqui. Duas coisas consomem esses eventos:

1. o rastro JSON (auditoria: por que ele respondeu o que respondeu);
2. o "mumbling" da fase de voz.

Como o mumbling só pode falar sobre eventos que de fato foram publicados,
ele nunca é encenado: se a busca não aconteceu, não existe evento, e não
existe frase. Essa é a garantia de projeto, não uma convenção.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass
class Evento:
    tipo: str            # ex.: "busca.bm25", "busca.rerank", "ingestao.documento"
    dados: dict[str, Any]
    t: float = field(default_factory=time.time)

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)


Ouvinte = Callable[[Evento], None]


class Barramento:
    def __init__(self) -> None:
        self._ouvintes: list[Ouvinte] = []
        self.eventos: list[Evento] = []

    def assinar(self, ouvinte: Ouvinte) -> None:
        self._ouvintes.append(ouvinte)

    def publicar(self, tipo: str, **dados: Any) -> Evento:
        ev = Evento(tipo=tipo, dados=dados)
        self.eventos.append(ev)
        for o in self._ouvintes:
            # Um ouvinte com defeito (ex.: TTS travado) não pode derrubar a
            # resposta técnica. Engolimos o erro, mas registramos no próprio rastro.
            try:
                o(ev)
            except Exception as e:  # noqa: BLE001
                self.eventos.append(Evento("erro.ouvinte", {"erro": repr(e), "evento": tipo}))
        return ev
