"""Escolha entre modelo rápido e forte.

Regra: na dúvida, FORTE. O rápido só responde quando a pergunta claramente
não envolve nada que possa machucar alguém ou estragar o carro se estiver
errado. A decisão é por regras (auditáveis no rastro), não por um LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from engenheiro.recuperacao.reescrita import normalizar

# Mensagem que é SÓ conversa: cumprimento, agradecimento, despedida.
_RE_CONVERSA = re.compile(
    r"^\s*(oi+|ola|e ai|bom dia|boa tarde|boa noite|obrigad[oa]|valeu|vlw|beleza|blz|"
    r"tudo bem|tchau|ate mais|ate logo|falou|show|ok|certo|entendi)\b[\s!.,?]*"
    r"(\w+[\s!.,?]*){0,3}$",
)

# Qualquer um destes manda para o modelo forte.
_GATILHOS_FORTE = [
    # (Unidades soltas como "V" e "A" não entram: "a" é artigo. Número já dispara por \d.)
    r"eletric", r"tensao", r"corrente", r"volt", r"amper", r"ohm", r"resist",
    r"potencia", r"watt", r"fusivel", r"rele", r"bateria", r"alternador", r"chicote", r"fio", r"bitola",
    r"aterr", r"curto", r"medi", r"multimetro", r"osciloscopio", r"torque", r"aperto", r"n\.?m\b",
    r"pressao", r"temperatura", r"\d", r"procedimento", r"passo", r"como (faco|fazer|trocar|instalar|ligar|"
    r"regular|ajustar|testar|medir|montar|desmontar)", r"segur", r"perigo", r"risco", r"combustivel",
    r"etanol", r"alcool", r"gasolina", r"ignicao", r"bobina", r"vela", r"carburador", r"partida",
    r"esp32", r"gpio", r"pino", r"sensor", r"circuito", r"regulador", r"divisor",
]
_RE_FORTE = re.compile("|".join(_GATILHOS_FORTE))


@dataclass
class Escolha:
    modo: str      # "conversa" (sem busca) ou "tecnico" (busca + citação + verificador)
    nivel: str     # "rapido" ou "forte"
    motivo: str


def escolher(pergunta: str) -> Escolha:
    n = normalizar(pergunta)
    gatilho = _RE_FORTE.search(n)
    if _RE_CONVERSA.match(n) and not gatilho:
        return Escolha("conversa", "rapido", "mensagem de conversa, sem termo técnico")
    if gatilho:
        return Escolha("tecnico", "forte", f"termo técnico/de segurança: '{gatilho.group(0)}'")
    # Pergunta técnica genérica sem gatilho ("o que é um carburador" cairia
    # acima; aqui sobram coisas como "me explica como funciona o motor").
    # Mesmo assim, padrão = forte, conforme o requisito de correção.
    return Escolha("tecnico", "forte", "padrão: na dúvida, modelo forte")
