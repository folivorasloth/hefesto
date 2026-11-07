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


# Perguntas de orientação/identificação ("como identifico", "onde fica"...).
_RE_ORIENTACAO = re.compile(
    r"\b(como (eu )?(identific\w*|sei|descubr\w*|reconhec\w*|acho|encontro|localizo|vejo|confiro|diferenci\w*)|"
    r"onde (fica|esta|ficam|estao|acho)|o que (e|eh|sao)|qual (e|eh) (a|o) (diferenca|funcao)|"
    r"pra que serve|para que serve|me explica|explica)\b"
)
# O que NUNCA vai para o modelo rápido: valor, medida, número, procedimento
# que mexe em algo, segurança. Mesmo numa conversa de orientação.
_RE_VALOR_OU_RISCO = re.compile(
    r"\d|tensao|corrente|volt|amper|ohm|resist|potencia|watt|torque|aperto|pressao|temperatura|"
    r"medi|medida|valor|quanto|quantos|especifica|como (faco|fazer|trocar|instalar|ligar|regular|ajustar|testar|"
    r"montar|desmontar|soldar|derivar|emendar)|segur|perigo|risco|gpio|pino|fusivel|bitola|"
    r"desconect|desmont|remov"
)


def escolher(pergunta: str, conversa: bool = False) -> Escolha:
    """`conversa=True` (modo conversa) libera o modelo rápido para perguntas
    de ORIENTAÇÃO sem valores nem risco ("como identifico a ignição?"),
    para a conversa não esperar minutos a cada turno. O verificador e a
    checagem de números continuam valendo para ele."""
    n = normalizar(pergunta)
    gatilho = _RE_FORTE.search(n)
    if _RE_CONVERSA.match(n) and not gatilho:
        return Escolha("conversa", "rapido", "mensagem de conversa, sem termo técnico")
    if conversa and _RE_ORIENTACAO.search(n):
        risco = _RE_VALOR_OU_RISCO.search(n)
        if not risco:
            return Escolha("tecnico", "rapido", "orientação/identificação, sem valor nem procedimento de risco")
    if gatilho:
        return Escolha("tecnico", "forte", f"termo técnico/de segurança: '{gatilho.group(0)}'")
    # Na dúvida, forte, conforme o requisito de correção.
    return Escolha("tecnico", "forte", "padrão: na dúvida, modelo forte")
