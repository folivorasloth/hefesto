"""Ferramentas de cálculo elétrico.

Unidades: SI nos nomes dos argumentos (V, A, Ω), exceto capacitância em µF,
que é como ela aparece no componente. Os resultados vêm arredondados a 6
algarismos significativos: mais que isso seria precisão falsa, já que os
componentes têm tolerância de 1% ou mais.
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from .base import ErroFerramenta


def _r(x: float) -> float:
    return float(f"{x:.6g}")


def _dois_de_tres(nomes: tuple[str, str, str], valores: tuple) -> None:
    dados = [n for n, v in zip(nomes, valores) if v is not None]
    if len(dados) != 2:
        raise ErroFerramenta(f"informe exatamente dois entre {', '.join(nomes)} (veio: {', '.join(dados) or 'nenhum'})")


def _positivo(**kw) -> None:
    for nome, v in kw.items():
        if v is not None and v <= 0:
            raise ErroFerramenta(f"{nome} deve ser maior que zero (veio {v})")


# ------------------------------------------------------------------ Ohm e potência
def lei_de_ohm(tensao_v: float | None = None, corrente_a: float | None = None, resistencia_ohm: float | None = None) -> dict:
    _dois_de_tres(("tensao_v", "corrente_a", "resistencia_ohm"), (tensao_v, corrente_a, resistencia_ohm))
    _positivo(resistencia_ohm=resistencia_ohm)
    if tensao_v is None:
        tensao_v = corrente_a * resistencia_ohm
    elif corrente_a is None:
        corrente_a = tensao_v / resistencia_ohm
    else:
        if corrente_a == 0:
            raise ErroFerramenta("corrente zero: resistência indefinida")
        resistencia_ohm = tensao_v / corrente_a
    return {
        "resultado": {"tensao_v": _r(tensao_v), "corrente_a": _r(corrente_a), "resistencia_ohm": _r(resistencia_ohm),
                      "potencia_w": _r(tensao_v * corrente_a)},
        "formula": "V = I × R; P = V × I",
        "notas": [],
    }


def potencia(tensao_v: float | None = None, corrente_a: float | None = None, resistencia_ohm: float | None = None) -> dict:
    r = lei_de_ohm(tensao_v, corrente_a, resistencia_ohm)
    r["formula"] = "P = V × I = I² × R = V² / R"
    return r


# ------------------------------------------------------------------ divisor de tensão
def divisor_tensao(
    vin_v: float, r1_ohm: float, r2_ohm: float, tolerancia_pct: float = 1.0, vout_max_permitido_v: float | None = None
) -> dict:
    """R1 entre a entrada e o ponto de saída; R2 entre a saída e o GND."""
    _positivo(vin_v=vin_v, r1_ohm=r1_ohm, r2_ohm=r2_ohm)
    if not 0 <= tolerancia_pct < 50:
        raise ErroFerramenta("tolerancia_pct fora da faixa (0 a 50)")
    t = tolerancia_pct / 100
    nominal = vin_v * r2_ohm / (r1_ohm + r2_ohm)
    # Pior caso: R2 no máximo e R1 no mínimo dá a maior saída, e vice-versa.
    vmax = vin_v * r2_ohm * (1 + t) / (r1_ohm * (1 - t) + r2_ohm * (1 + t))
    vmin = vin_v * r2_ohm * (1 - t) / (r1_ohm * (1 + t) + r2_ohm * (1 - t))
    i = vin_v / (r1_ohm + r2_ohm)
    notas = [
        "Pior caso considera só a tolerância dos resistores; não inclui variação da tensão de entrada nem a impedância de entrada do ADC.",
        "No carro, a tensão de entrada varia (bateria parada x motor carregando) e tem transientes: proteja a entrada do ADC (ex.: diodo/zener e capacitor) além do divisor.",
    ]
    res = {
        "vout_nominal_v": _r(nominal),
        "vout_min_v": _r(vmin),
        "vout_max_v": _r(vmax),
        "razao": _r(r2_ohm / (r1_ohm + r2_ohm)),
        "corrente_a": _r(i),
        "potencia_r1_w": _r(i * i * r1_ohm),
        "potencia_r2_w": _r(i * i * r2_ohm),
        "resistencia_vista_pelo_adc_ohm": _r(r1_ohm * r2_ohm / (r1_ohm + r2_ohm)),
    }
    if vout_max_permitido_v is not None:
        res["dentro_do_limite"] = vmax <= vout_max_permitido_v
        if vmax > vout_max_permitido_v:
            notas.insert(0, f"ALERTA: no pior caso a saída chega a {_r(vmax)} V, acima do limite de {vout_max_permitido_v} V.")
    return {
        "resultado": res,
        "formula": "Vout = Vin × R2 / (R1 + R2); pior caso com R1(1∓t) e R2(1±t)",
        "notas": notas,
    }


def valores_do_kit(caminho_inventario: Path) -> list[float]:
    """Lê os valores do kit de resistores do inventário (só os confirmados)."""
    dados = yaml.safe_load(caminho_inventario.read_text(encoding="utf-8")) or {}
    for item in dados.get("itens", []):
        if item.get("id") == "resistores-kit-600":
            for e in item.get("especificacoes", []):
                if e.get("item") == "valores" and e.get("status") == "confirmado":
                    return [converter_notacao_resistor(v.strip()) for v in e["valor"].split(",")]
    return []


def converter_notacao_resistor(txt: str) -> float:
    """'4K7' -> 4700, '10R' -> 10, '1M' -> 1e6, '2K2' -> 2200."""
    t = txt.strip().upper().replace("Ω", "").replace(" ", "")
    for letra, mult in (("R", 1), ("K", 1e3), ("M", 1e6)):
        if letra in t:
            inteiro, _, frac = t.partition(letra)
            return float(f"{inteiro or 0}.{frac or 0}") * mult
    return float(t)


def escolher_divisor(
    vin_max_v: float,
    vout_max_v: float,
    valores_ohm: list[float],
    tolerancia_pct: float = 1.0,
    r_total_min_ohm: float = 10_000,
    r_total_max_ohm: float = 200_000,
    quantos: int = 3,
) -> dict:
    """Escolhe pares R1/R2 entre os valores DISPONÍVEIS para que, no pior caso,
    a saída nunca passe de vout_max_v com vin_max_v na entrada. Entre os que
    atendem, prefere o que usa mais da faixa (melhor resolução)."""
    _positivo(vin_max_v=vin_max_v, vout_max_v=vout_max_v)
    if vout_max_v >= vin_max_v:
        raise ErroFerramenta("vout_max_v precisa ser menor que vin_max_v para um divisor")
    if not valores_ohm:
        raise ErroFerramenta("nenhum valor de resistor disponível (inventário sem a lista confirmada)")
    t = tolerancia_pct / 100
    candidatos = []
    for r1 in valores_ohm:
        for r2 in valores_ohm:
            total = r1 + r2
            if not r_total_min_ohm <= total <= r_total_max_ohm:
                continue
            vmax = vin_max_v * r2 * (1 + t) / (r1 * (1 - t) + r2 * (1 + t))
            if vmax <= vout_max_v:
                candidatos.append((vmax, r1, r2))
    if not candidatos:
        raise ErroFerramenta("nenhum par dos valores disponíveis atende ao limite na faixa de resistência total pedida")
    candidatos.sort(reverse=True)
    melhores = [
        {"r1_ohm": r1, "r2_ohm": r2, "vout_max_pior_caso_v": _r(vmax),
         "vout_nominal_v": _r(vin_max_v * r2 / (r1 + r2)), "aproveitamento_da_faixa_pct": _r(100 * vmax / vout_max_v)}
        for vmax, r1, r2 in candidatos[:quantos]
    ]
    return {
        "resultado": {"pares": melhores},
        "formula": "para cada par (R1, R2) disponível: Vout_max = Vin_max × R2(1+t) / (R1(1−t) + R2(1+t)) ≤ limite",
        "notas": [
            f"Faixa de resistência total usada: {r_total_min_ohm:g} a {r_total_max_ohm:g} Ω (escolha de projeto, ajustável): "
            "muito baixa desperdiça corrente; muito alta deixa a leitura do ADC sensível a ruído e à impedância de entrada.",
            "Só usa resistores que estão no inventário.",
        ],
    }


# ------------------------------------------------------------------ fios
def awg_para_mm2(awg: int) -> float:
    if not -3 <= awg <= 40:
        raise ErroFerramenta("AWG fora da faixa (-3 = 0000 a 40)")
    d = 0.127 * 92 ** ((36 - awg) / 39)
    return math.pi * d * d / 4


def queda_tensao_fio(
    corrente_a: float,
    comprimento_m: float,
    secao_mm2: float | None = None,
    awg: int | None = None,
    retorno_pelo_chassi: bool = True,
    temperatura_c: float = 20.0,
    tensao_sistema_v: float | None = None,
    constantes: dict | None = None,
) -> dict:
    """Queda de tensão num fio de cobre.

    `comprimento_m` é a distância do fio de ida. Com retorno_pelo_chassi=True
    (o normal no carro) só o fio de ida conta; com False, ida e volta (2x).
    A resistência do chassi e das conexões NÃO entra: na prática ela existe.
    """
    if (secao_mm2 is None) == (awg is None):
        raise ErroFerramenta("informe secao_mm2 OU awg (um dos dois)")
    _positivo(corrente_a=corrente_a, comprimento_m=comprimento_m, secao_mm2=secao_mm2)
    c = constantes or {}
    rho20 = c.get("resistividade_20c_ohm_mm2_por_m", 0.017241)
    alfa = c.get("coef_temperatura_por_c", 0.00393)
    area = secao_mm2 if secao_mm2 is not None else awg_para_mm2(awg)
    rho = rho20 * (1 + alfa * (temperatura_c - 20))
    comprimento_total = comprimento_m * (1 if retorno_pelo_chassi else 2)
    resistencia = rho * comprimento_total / area
    queda = corrente_a * resistencia
    res = {
        "secao_mm2": _r(area),
        "resistencia_ohm": _r(resistencia),
        "queda_v": _r(queda),
        "potencia_dissipada_w": _r(corrente_a * queda),
        "comprimento_considerado_m": _r(comprimento_total),
    }
    if tensao_sistema_v:
        res["queda_pct"] = _r(100 * queda / tensao_sistema_v)
    return {
        "resultado": res,
        "formula": "R = ρ(T) × L / A; ρ(T) = ρ20 × (1 + α(T − 20)); ΔV = I × R",
        "notas": [
            f"Cobre IACS: ρ20 = {rho20} Ω·mm²/m, α = {alfa}/°C (dados_ref/constantes.yaml)."
            + (f" AWG {awg} = {_r(area)} mm² pela definição ASTM B258." if awg is not None else ""),
            "Não inclui resistência de conectores, emendas e do retorno pelo chassi." if retorno_pelo_chassi
            else "Considera ida e volta no mesmo fio; não inclui conectores e emendas.",
        ],
    }


# ------------------------------------------------------------------ fusível
def dimensionar_fusivel(
    corrente_carga_a: float, capacidade_fio_a: float | None = None, constantes: dict | None = None
) -> dict:
    _positivo(corrente_carga_a=corrente_carga_a)
    c = constantes or {}
    fator = c.get("fator_regra_pratica", 1.25)
    padroes = c.get("valores_a", [1, 2, 3, 4, 5, 7.5, 10, 15, 20, 25, 30, 35, 40])
    minimo = corrente_carga_a * fator
    escolhido = next((v for v in padroes if v >= minimo), None)
    notas = [
        f"REGRA PRÁTICA, não norma: fusível ≥ {fator} × corrente contínua da carga e ≤ capacidade do fio. "
        "Confirme com o livro de elétrica automotiva da base.",
        "O fusível protege o FIO: ele fica o mais perto possível do ponto onde a alimentação é derivada.",
    ]
    res = {"corrente_minima_fusivel_a": _r(minimo), "fusivel_padrao_a": escolhido}
    if escolhido is None:
        notas.insert(0, "ALERTA: corrente acima dos valores padrão de fusível de lâmina listados.")
    if capacidade_fio_a is not None and escolhido is not None:
        res["fio_suporta"] = escolhido <= capacidade_fio_a
        if escolhido > capacidade_fio_a:
            notas.insert(0, f"ALERTA: o fusível de {escolhido} A é maior que a capacidade do fio ({capacidade_fio_a} A): "
                            "use fio mais grosso ou reduza a carga.")
    return {"resultado": res, "formula": f"I_fusível ≥ {fator} × I_carga, arredondado para o próximo valor padrão",
            "notas": notas}


# ------------------------------------------------------------------ filtro RC
def filtro_rc(resistencia_ohm: float | None = None, capacitancia_uf: float | None = None,
              frequencia_corte_hz: float | None = None) -> dict:
    _dois_de_tres(("resistencia_ohm", "capacitancia_uf", "frequencia_corte_hz"),
                  (resistencia_ohm, capacitancia_uf, frequencia_corte_hz))
    _positivo(resistencia_ohm=resistencia_ohm, capacitancia_uf=capacitancia_uf, frequencia_corte_hz=frequencia_corte_hz)
    c = capacitancia_uf * 1e-6 if capacitancia_uf is not None else None
    if frequencia_corte_hz is None:
        frequencia_corte_hz = 1 / (2 * math.pi * resistencia_ohm * c)
    elif resistencia_ohm is None:
        resistencia_ohm = 1 / (2 * math.pi * frequencia_corte_hz * c)
    else:
        c = 1 / (2 * math.pi * frequencia_corte_hz * resistencia_ohm)
    tau = resistencia_ohm * c
    return {
        "resultado": {"resistencia_ohm": _r(resistencia_ohm), "capacitancia_uf": _r(c * 1e6),
                      "frequencia_corte_hz": _r(frequencia_corte_hz), "constante_tempo_s": _r(tau)},
        "formula": "fc = 1 / (2π R C); τ = R C",
        "notas": ["Filtro passa-baixa de 1ª ordem: atenua ~20 dB por década acima de fc."],
    }
