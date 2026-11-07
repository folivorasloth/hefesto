"""Ferramentas do motor: rotação, velocidade e lambda/AFR."""

from __future__ import annotations

import math
import re

from .base import ErroFerramenta
from .eletrica import _positivo, _r


def faiscas_por_volta(cilindros: int, tempos: int) -> float:
    """Num motor de 4 tempos, cada cilindro faz uma faísca a cada 2 voltas do
    virabrequim; num de 2 tempos, a cada volta."""
    if tempos not in (2, 4):
        raise ErroFerramenta("tempos deve ser 2 ou 4")
    if cilindros < 1:
        raise ErroFerramenta("cilindros deve ser >= 1")
    return cilindros / (tempos / 2)


def rotacao_por_pulsos(
    frequencia_hz: float | None = None,
    rpm: float | None = None,
    cilindros: int = 4,
    tempos: int = 4,
    pulsos_por_faisca: float = 1.0,
) -> dict:
    """Converte frequência do sinal de ignição em rpm (ou o inverso).

    Padrão do Gol AP: 4 cilindros, 4 tempos -> 2 faíscas por volta. Com um
    distribuidor e uma bobina, sai 1 pulso por faísca (pulsos_por_faisca=1).
    """
    if (frequencia_hz is None) == (rpm is None):
        raise ErroFerramenta("informe frequencia_hz OU rpm")
    _positivo(frequencia_hz=frequencia_hz, rpm=rpm, pulsos_por_faisca=pulsos_por_faisca)
    fpv = faiscas_por_volta(cilindros, tempos)
    pulsos_por_volta = fpv * pulsos_por_faisca
    if rpm is None:
        rpm = frequencia_hz * 60 / pulsos_por_volta
    else:
        frequencia_hz = rpm * pulsos_por_volta / 60
    return {
        "resultado": {"rpm": _r(rpm), "frequencia_hz": _r(frequencia_hz), "pulsos_por_volta": _r(pulsos_por_volta),
                      "periodo_ms": _r(1000 / frequencia_hz)},
        "formula": "rpm = f × 60 / pulsos_por_volta; pulsos_por_volta = cilindros / (tempos / 2) × pulsos_por_faisca",
        "notas": [f"Considerado: {cilindros} cilindros, {tempos} tempos, {pulsos_por_faisca} pulso(s) por faísca."],
    }


_RE_PNEU = re.compile(r"^\s*(\d{3})\s*/\s*(\d{2})\s*Z?R?\s*(\d{2})\s*$", re.IGNORECASE)


def diametro_pneu_mm(medida: str) -> float:
    """'175/70 R13' -> diâmetro externo nominal em mm (pneu sem carga)."""
    m = _RE_PNEU.match(medida.replace("-", " "))
    if not m:
        raise ErroFerramenta(f"medida de pneu não reconhecida: {medida!r} (formato: 175/70 R13)")
    largura, perfil, aro = map(int, m.groups())
    return aro * 25.4 + 2 * largura * perfil / 100


def velocidade_por_rotacao(
    rpm: float,
    relacao_marcha: float,
    relacao_diferencial: float,
    medida_pneu: str | None = None,
    diametro_pneu_mm_: float | None = None,
) -> dict:
    if (medida_pneu is None) == (diametro_pneu_mm_ is None):
        raise ErroFerramenta("informe medida_pneu (ex.: '175/70 R13') OU diametro_pneu_mm")
    _positivo(rpm=rpm, relacao_marcha=relacao_marcha, relacao_diferencial=relacao_diferencial)
    d = diametro_pneu_mm(medida_pneu) if medida_pneu else diametro_pneu_mm_
    circ_m = math.pi * d / 1000
    rpm_roda = rpm / (relacao_marcha * relacao_diferencial)
    kmh = rpm_roda * circ_m * 60 / 1000
    return {
        "resultado": {"velocidade_kmh": _r(kmh), "rpm_roda": _r(rpm_roda), "diametro_pneu_mm": _r(d),
                      "circunferencia_m": _r(circ_m)},
        "formula": "v = rpm / (i_marcha × i_dif) × π × D × 60 / 1000; D = aro×25,4 + 2×largura×perfil/100",
        "notas": [
            "Diâmetro NOMINAL do pneu sem carga: com o peso do carro e o desgaste, o raio efetivo é menor e a velocidade real fica um pouco abaixo.",
            "Não considera patinagem nem embreagem patinando.",
        ],
    }


def lambda_afr(
    combustivel: str,
    lambda_: float | None = None,
    afr: float | None = None,
    afr_estequiometrico: float | None = None,
    fonte_estequiometrico: str | None = None,
    tabela: dict | None = None,
) -> dict:
    """Converte lambda <-> AFR. A estequiometria NUNCA tem valor padrão: vem
    do dados_ref/combustiveis.yaml (confirmado, com fonte) ou é informada na
    chamada junto com a fonte."""
    if (lambda_ is None) == (afr is None):
        raise ErroFerramenta("informe lambda OU afr")
    _positivo(lambda_=lambda_, afr=afr)
    origem = None
    if afr_estequiometrico is not None:
        if not fonte_estequiometrico:
            raise ErroFerramenta("afr_estequiometrico informado sem fonte_estequiometrico: diga de onde veio o valor")
        origem = fonte_estequiometrico
    else:
        info = (tabela or {}).get(combustivel)
        if info is None:
            raise ErroFerramenta(f"combustível '{combustivel}' não está em dados_ref/combustiveis.yaml ({sorted(tabela or {})})")
        if info.get("afr_estequiometrico") is None or info.get("status") != "confirmado":
            raise ErroFerramenta(
                f"a relação estequiométrica de '{combustivel}' ainda não foi confirmada com fonte "
                "(dados_ref/combustiveis.yaml). Busque o valor num livro da base e informe afr_estequiometrico com a fonte."
            )
        afr_estequiometrico = float(info["afr_estequiometrico"])
        origem = info.get("fonte")
    if lambda_ is None:
        lambda_ = afr / afr_estequiometrico
    else:
        afr = lambda_ * afr_estequiometrico
    leitura = "estequiométrica" if abs(lambda_ - 1) < 0.005 else ("rica" if lambda_ < 1 else "pobre")
    return {
        "resultado": {"lambda": _r(lambda_), "afr": _r(afr), "afr_estequiometrico": afr_estequiometrico, "mistura": leitura},
        "formula": "λ = AFR / AFR_esteq",
        "notas": [f"AFR estequiométrico de {combustivel}: {afr_estequiometrico} (fonte: {origem})."],
    }
