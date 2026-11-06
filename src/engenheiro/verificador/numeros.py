"""Checagem determinística de números: todo número de uma afirmação precisa
ter vindo de algum lugar verificável (trecho citado, pergunta do usuário ou,
a partir da fase 3, saída de ferramenta).

Isto é código, não LLM, de propósito: um LLM verificador pode "achar" que
17,3 e 17,8 são parecidos o bastante. Aqui ou o valor aparece na origem ou
ele é marcado como suspeito.

Limitação conhecida (fase 2): compara só o VALOR, não a unidade. "12 V" na
afirmação casa com "12 A" na fonte. A coerência da unidade fica a cargo do
verificador LLM; a conversão de unidades (pint) entra na fase 3.
"""

from __future__ import annotations

import re

# Número isolado: não pega dígitos dentro de palavras (GPIO34, T3, AP1600),
# que são nomes/códigos e não grandezas.
_RE_NUMERO = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)*)(?![.,]?\d)")
# Ids de trecho que o modelo às vezes escreve dentro do texto: [T3], (T3).
_RE_ID_TRECHO = re.compile(r"\[?\(?\bT\d+\b\)?\]?")


def _interpretacoes(tok: str) -> set[float]:
    """Um número escrito pode ter mais de uma leitura (1.000 = mil em PT, um
    em EN). Devolvemos todas as leituras plausíveis; basta uma coincidir."""
    tok = tok.strip(".,")
    if not tok:
        return set()
    valores: set[float] = set()
    tem_v, tem_p = "," in tok, "." in tok

    def add(s: str) -> None:
        try:
            valores.add(round(float(s), 6))
        except ValueError:
            pass

    if not tem_v and not tem_p:
        add(tok)
    elif tem_v and tem_p:
        # O separador que aparece por último é o decimal.
        if tok.rfind(",") > tok.rfind("."):
            add(tok.replace(".", "").replace(",", "."))
        else:
            add(tok.replace(",", ""))
    else:
        sep = "," if tem_v else "."
        partes = tok.split(sep)
        if len(partes) == 2:
            add(partes[0] + "." + partes[1])  # decimal
        if all(len(p) == 3 for p in partes[1:]):
            add("".join(partes))  # separador de milhar
    return valores


def extrair_numeros(texto: str) -> list[str]:
    texto = _RE_ID_TRECHO.sub(" ", texto)
    return [m.group(1).strip(".,") for m in _RE_NUMERO.finditer(texto)]


def valores_em(texto: str) -> set[float]:
    v: set[float] = set()
    for tok in extrair_numeros(texto):
        v |= _interpretacoes(tok)
    return v


def numeros_sem_origem(afirmacao: str, origens: list[str]) -> list[str]:
    """Números da afirmação que não aparecem em nenhum texto de origem."""
    disponiveis: set[float] = set()
    for o in origens:
        disponiveis |= valores_em(o)
    suspeitos = []
    for tok in extrair_numeros(afirmacao):
        if not (_interpretacoes(tok) & disponiveis):
            suspeitos.append(tok)
    return suspeitos
