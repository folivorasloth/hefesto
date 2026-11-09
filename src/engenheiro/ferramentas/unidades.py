"""Conversão de unidades com pint (nada de fator de conversão "de cabeça")."""

from __future__ import annotations

from functools import lru_cache

from .base import ErroFerramenta
from .eletrica import _r

# Apelidos comuns em português/oficina que o pint não conhece.
_APELIDOS = {
    "kgf.m": "kilogram_force * meter", "kgfm": "kilogram_force * meter", "kgf·m": "kilogram_force * meter",
    # ("nm" fica de fora: é nanômetro.)
    "n.m": "newton * meter", "n·m": "newton * meter", "n-m": "newton * meter",
    "lbf.ft": "pound_force * foot", "lb.ft": "pound_force * foot", "ft.lb": "foot * pound_force",
    "kgf/cm2": "kilogram_force / centimeter ** 2", "kgf/cm²": "kilogram_force / centimeter ** 2",
    "psi": "psi", "bar": "bar", "kpa": "kilopascal",
    "km/h": "kilometer / hour", "kmh": "kilometer / hour", "mph": "mile / hour",
    # Só com o símbolo de grau: "C" é coulomb e "F" é farad no pint.
    "°c": "degC", "ºc": "degC", "°f": "degF", "ºf": "degF",
    "pol": "inch", "polegada": "inch", "polegadas": "inch", "\"": "inch",
    "cv": "metric_horsepower", "hp": "horsepower",
    "ohm": "ohm", "ω": "ohm", "kohm": "kiloohm", "kω": "kiloohm",
}


@lru_cache(maxsize=1)
def _ureg():
    import pint

    return pint.UnitRegistry()


def _unidade(u: str):
    return _APELIDOS.get(u.strip().lower(), u.strip())


def converter_unidade(valor: float, de: str, para: str) -> dict:
    ureg = _ureg()
    try:
        q = ureg.Quantity(valor, _unidade(de)).to(_unidade(para))
    except Exception as e:  # noqa: BLE001 - erro do pint vira mensagem clara
        raise ErroFerramenta(f"não consegui converter {valor} {de} para {para}: {e}") from e
    return {
        "resultado": {"valor": _r(q.magnitude), "unidade": para, "entrada": f"{valor} {de}"},
        "formula": f"pint: {de} -> {para}",
        "notas": [],
    }
