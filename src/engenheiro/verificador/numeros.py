"""Checagem determinística de números: todo número de uma afirmação precisa
ter vindo de algum lugar verificável (trecho citado, pergunta do usuário ou,
a partir da fase 3, saída de ferramenta).

Isto é código, não LLM, de propósito: um LLM verificador pode "achar" que
17,3 e 17,8 são parecidos o bastante. Aqui ou o valor aparece na origem ou
ele é marcado como suspeito.

Desde a fase 4, a UNIDADE também conta: quando o número da afirmação tem
unidade ("12 V"), a origem precisa ter o mesmo valor na mesma grandeza
("12 V", "12000 mV") ou o número sem unidade. Assim "12 V" não é mais
"confirmado" por um "12 A", nem "2 A" por um "2ª marcha". Prefixos são
convertidos (mV, kΩ, mA...). Número sem unidade na afirmação continua
aceitando qualquer ocorrência do valor.
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


# Unidade logo depois do número -> (grandeza canônica, fator para a unidade base).
# Maiúsculas importam: "2 A" é ampère, "de 2 a 5" não é.
_UNIDADES: list[tuple[str, str, float]] = [
    (r"kV", "V", 1e3), (r"mV", "V", 1e-3), (r"V", "V", 1.0),
    (r"mA", "A", 1e-3), (r"µA|uA", "A", 1e-6), (r"A", "A", 1.0),
    (r"MΩ|Mohms?", "ohm", 1e6), (r"kΩ|kohms?|K(?=\b)", "ohm", 1e3), (r"Ω|ohms?", "ohm", 1.0),
    (r"kW", "W", 1e3), (r"mW", "W", 1e-3), (r"W", "W", 1.0),
    (r"kHz", "Hz", 1e3), (r"Hz", "Hz", 1.0),
    (r"N\s*[·.\-]?\s*m", "N.m", 1.0), (r"kgf\s*[·.]?\s*m", "kgf.m", 1.0),
    (r"mm²|mm2", "mm2", 1.0), (r"mm", "m", 1e-3), (r"cm", "m", 1e-2), (r"km(?!/)", "m", 1e3),
    (r"km/h", "km/h", 1.0), (r"rpm", "rpm", 1.0), (r"°C|ºC", "C", 1.0), (r"%", "%", 1.0),
    (r"psi", "psi", 1.0), (r"bar", "bar", 1.0),
    (r"µF|uF", "F", 1e-6), (r"nF", "F", 1e-9), (r"pF", "F", 1e-12),
    (r"ms", "s", 1e-3), (r"s(?=\b)", "s", 1.0),
    (r"[ªº]", "ordinal", 1.0),
]
# Três formas, nesta ordem: número + unidade conhecida; número COLADO a um
# sufixo desconhecido ("10µH", "100cv", "1e3", "5W30"); número solto. A do
# meio existe para o número não ficar invisível: o sufixo vira uma unidade
# "opaca", que só casa com o mesmo sufixo escrito igual na origem.
_RE_QUANTIDADE = re.compile(
    r"(?<![\w.,])(\d+(?:[.,]\d+)*)(?![.,]?\d)(?:"
    r"\s*(" + "|".join(f"(?:{u})" for u, _, _ in _UNIDADES) + r")(?![\w²])"
    r"|([^\W\d_][\w²]*)"
    r"|(?![\w²]))"
)
_RE_UNIDADES_COMPILADAS = [(re.compile(rf"^(?:{u})$"), g, f) for u, g, f in _UNIDADES]

# Notação de bancada para resistor: 4k7 = 4,7 kΩ, 4R7 = 4,7 Ω, 2M2 = 2,2 MΩ; e
# "10k" / "10K" / "1M" sozinhos. Reescritos para a forma com unidade.
_RE_RESISTOR_MEIO = re.compile(r"(?<![\w.,])(\d+)([kKRM])(\d+)(?![\w.,]?\d)(?!\w)")
_RE_RESISTOR_FIM = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s?([kM])(?![\w²Ω])")
_SUFIXO_RESISTOR = {"k": "kΩ", "K": "kΩ", "R": "Ω", "M": "MΩ"}

# Número que é só rótulo ("Figura 12", "passo 3", "p. 45"): não serve de
# origem para um valor COM unidade ("12 A").
_RE_ROTULO = re.compile(
    r"\b(?:figuras?|fig|tabelas?|tab|passos?|etapas?|itens|item|p[áa]ginas?|p[áa]g|p|cap[íi]tulos?|cap"
    r"|se[çc][ãa]o|se[çc][õo]es|figures?|tables?|steps?|pages?|chapters?|sections?)\.?\s*(?:n[ºo°]\.?\s*)?"
    r"\d+(?:[.,]\d+)*",
    re.IGNORECASE,
)


def _normalizar_resistores(texto: str) -> str:
    texto = _RE_RESISTOR_MEIO.sub(lambda m: f"{m.group(1)},{m.group(3)} {_SUFIXO_RESISTOR[m.group(2)]}", texto)
    return _RE_RESISTOR_FIM.sub(lambda m: f"{m.group(1)} {_SUFIXO_RESISTOR[m.group(2)]}", texto)


def _sig(v: float) -> float:
    """Arredonda por algarismos significativos, não por casas decimais:
    22 pF (2,2e-11) não pode virar zero, senão todo pF é igual a todo pF."""
    return float(f"{v:.9g}")


def _unidade(txt: str | None) -> tuple[str, float] | None:
    if not txt:
        return None
    for rx, grandeza, fator in _RE_UNIDADES_COMPILADAS:
        if rx.match(txt):
            return grandeza, fator
    return None


def quantidades(texto: str) -> list[tuple[str, set[float], str | None]]:
    """[(token, leituras na unidade base, grandeza ou None)]."""
    texto = _normalizar_resistores(_RE_ID_TRECHO.sub(" ", texto))
    saida = []
    for m in _RE_QUANTIDADE.finditer(texto):
        tok = m.group(1).strip(".,")
        u = _unidade(m.group(2))
        leituras = _interpretacoes(tok)
        if u:
            grandeza, fator = u
            saida.append((tok, {_sig(v * fator) for v in leituras}, grandeza))
        elif m.group(3):
            saida.append((tok, leituras, "?" + m.group(3)))  # sufixo desconhecido: casa só literalmente
        else:
            saida.append((tok, leituras, None))
    return saida


def extrair_numeros(texto: str) -> list[str]:
    texto = _RE_ID_TRECHO.sub(" ", texto)
    return [m.group(1).strip(".,") for m in _RE_NUMERO.finditer(texto)]


def valores_em(texto: str) -> set[float]:
    v: set[float] = set()
    for tok in extrair_numeros(texto):
        v |= _interpretacoes(tok)
    return v


def numeros_sem_origem(afirmacao: str, origens: list[str]) -> list[str]:
    """Números da afirmação sem origem verificável (valor + unidade)."""
    com_unidade: dict[str, set[float]] = {}
    sem_unidade: set[float] = set()
    todos: set[float] = set()
    for o in origens:
        for _, leituras, grandeza in quantidades(o):
            todos |= leituras
            if grandeza is not None:
                com_unidade.setdefault(grandeza, set()).update(leituras)
        # Número solto (célula de tabela) serve de origem para valor com
        # unidade; número de rótulo ("Figura 12") não.
        for _, leituras, grandeza in quantidades(_RE_ROTULO.sub(" ", o)):
            if grandeza is None:
                sem_unidade |= leituras
        # Leituras "brutas" (sem converter prefixo), para afirmação sem unidade.
        todos |= valores_em(o)
    suspeitos = []
    for tok, leituras, grandeza in quantidades(afirmacao):
        if grandeza is None:
            ok = bool(leituras & todos)
        else:
            ok = bool(leituras & com_unidade.get(grandeza, set())) or bool(_interpretacoes(tok) & sem_unidade)
        if not ok:
            suspeitos.append(tok)
    return suspeitos
