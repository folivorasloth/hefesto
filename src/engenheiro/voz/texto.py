"""Prepara texto para ser falado pelo Piper.

O sintetizador lê "12,6 V" como "doze vírgula seis vê" e "GPIO34" como uma
sopa de letras. Aqui as unidades viram palavras e os símbolos somem. É só
apresentação: o texto da tela e o rastro continuam com a notação técnica.
"""

from __future__ import annotations

import re

# Unidade depois de número -> por extenso. Ordem importa (kΩ antes de Ω).
_UNIDADES = [
    (r"kΩ|kohms?", "quilo-ohms"), (r"MΩ", "mega-ohms"), (r"Ω|ohms?", "ohms"),
    (r"mA", "miliampères"), (r"A", "ampères"), (r"mV", "milivolts"), (r"kV", "quilovolts"), (r"V", "volts"),
    (r"kW", "quilowatts"), (r"W", "watts"), (r"N\s*[·.]?\s*m", "newton-metro"), (r"kgf\s*[·.]?\s*m", "quilograma-força metro"),
    (r"mm²|mm2", "milímetros quadrados"), (r"mm", "milímetros"), (r"cm", "centímetros"), (r"km/h", "quilômetros por hora"),
    (r"rpm", "rotações por minuto"), (r"Hz", "hertz"), (r"kHz", "quilo-hertz"), (r"ms", "milissegundos"),
    (r"µF|uF", "microfarads"), (r"nF", "nanofarads"), (r"°C", "graus Celsius"), (r"%", "por cento"),
    (r"psi", "psi"), (r"bar", "bar"), (r"Ah", "ampère-hora"),
]
_RE_UNIDADE = [(re.compile(rf"(\d)\s*(?:{u})(?![\w²])"), f"\\1 {nome}") for u, nome in _UNIDADES]
_RE_GPIO = re.compile(r"\bGPIO\s?(\d+)\b", re.I)
_RE_PINO_G = re.compile(r"\bG(\d{1,2})\b")


def normalizar_para_fala(texto: str) -> str:
    t = texto
    t = re.sub(r"[•➜⚠]", " ", t)
    t = t.replace("[", "").replace("]", "")
    t = _RE_GPIO.sub(r"G P I O \1", t)
    t = _RE_PINO_G.sub(r"pino G \1", t)
    for rx, sub in _RE_UNIDADE:
        t = rx.sub(sub, t)
    t = t.replace("λ", "lambda").replace("≤", "menor ou igual a").replace("≥", "maior ou igual a")
    t = t.replace("×", " vezes ").replace("±", " mais ou menos ")
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"(\.\s*){2,}", ". ", t)
    return t.strip()


def dividir_em_frases(texto: str, max_chars: int = 220) -> list[str]:
    """Frases curtas: o áudio começa a sair antes de sintetizar tudo, e dá
    para interromper entre uma frase e outra."""
    frases = [f.strip() for f in re.split(r"(?<=[.!?;:])\s+", texto) if f.strip()]
    saida: list[str] = []
    for f in frases:
        while len(f) > max_chars:
            corte = f.rfind(",", 0, max_chars)
            corte = corte if corte > 40 else max_chars
            saida.append(f[: corte + 1].strip())
            f = f[corte + 1:].strip()
        if f:
            saida.append(f)
    return saida
