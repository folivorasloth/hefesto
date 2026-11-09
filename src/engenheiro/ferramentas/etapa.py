"""Etapa 1 da resposta: o modelo forte decide e chama ferramentas.

Separada da etapa 2 (resposta em JSON) porque estruturar a saída e chamar
ferramentas na mesma chamada nem sempre é suportado de forma confiável. As
duas etapas compartilham o mesmo prefixo de prompt (ver gerador.mensagens_base).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from engenheiro.geracao import prompts
from engenheiro.llm.ollama import LLM

from .base import Chamada, Registro


@dataclass
class ResultadoEtapa:
    chamadas: list[Chamada] = field(default_factory=list)
    mensagens: list[dict] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    rodadas: int = 0


def executar(llm: LLM, modelo: str, registro: Registro, mensagens_base: list[dict], max_rodadas: int,
             opcoes: dict | None = None, pensar: bool | None = None) -> ResultadoEtapa:
    res = ResultadoEtapa()
    registro.nova_sessao()
    msgs = [mensagens_base[0], {"role": "user", "content": mensagens_base[1]["content"] + "\n\n" + prompts.INSTRUCAO_FERRAMENTAS}]
    for rodada in range(1, max_rodadas + 1):
        res.rodadas = rodada
        try:
            r = llm.chat(modelo, msgs, opcoes=opcoes, pensar=pensar, ferramentas=registro.esquemas())
        except Exception as e:  # noqa: BLE001 - ex.: modelo sem suporte a ferramentas
            res.avisos.append(f"Etapa de ferramentas falhou ({e!r}); resposta segue sem cálculos.")
            break
        pedidas = r.get("chamadas") or []
        msgs.append(r.get("mensagem") or {"role": "assistant", "content": r.get("conteudo", "")})
        if not pedidas:
            break
        for p in pedidas:
            ch = registro.executar(p["nome"], p.get("argumentos"))
            corpo = ch.saida if ch.erro is None else {"erro": ch.erro}
            msgs.append({"role": "tool", "tool_name": ch.nome,
                         "content": json.dumps({"id": ch.id, **corpo}, ensure_ascii=False, default=str)})
    else:
        res.avisos.append(f"Limite de {max_rodadas} rodadas de ferramentas atingido.")
    res.chamadas = list(registro.chamadas)
    res.mensagens = msgs
    return res
