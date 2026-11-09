"""Verificação de pinos do ESP32 contra a tabela dados_ref/esp32_pinos.yaml."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from .base import ErroFerramenta

USOS = ["entrada_digital", "saida_digital", "analogico", "i2c", "pwm", "uart", "spi"]

# Como cada gravidade se aplica a cada uso.
_APLICA = {
    "proibido": lambda uso, wifi: True,
    "erro_se_saida": lambda uso, wifi: uso in ("saida_digital", "pwm", "i2c", "uart", "spi"),
    "alerta_se_entrada_digital": lambda uso, wifi: uso in ("entrada_digital", "i2c"),
    "alerta": lambda uso, wifi: True,
    "alerta_se_analogico": lambda uso, wifi: uso == "analogico" and wifi,
    "alerta_se_saida": lambda uso, wifi: uso in ("saida_digital", "pwm"),
    "info": lambda uso, wifi: True,
}
_BLOQUEIA = {"proibido", "erro_se_saida"}


@lru_cache(maxsize=4)
def carregar_tabela(caminho: str) -> dict:
    return yaml.safe_load(Path(caminho).read_text(encoding="utf-8"))


def _normalizar_pino(p) -> int:
    """Aceita 34, '34', 'GPIO34', 'G34', 'IO34', 'SP', 'SN', 'TXD'..."""
    if isinstance(p, int):
        return p
    t = str(p).strip().upper()
    apelidos = {"SP": 36, "VP": 36, "SENSOR_VP": 36, "SN": 39, "VN": 39, "SENSOR_VN": 39, "TXD": 1, "TX": 1,
                "RXD": 3, "RX": 3, "CLK": 6, "SD0": 7, "SD1": 8, "SD2": 9, "SD3": 10, "CMD": 11}
    if t in apelidos:
        return apelidos[t]
    m = re.fullmatch(r"(?:GPIO|IO|G|D)?(\d{1,2})", t)
    if not m:
        raise ErroFerramenta(f"pino não reconhecido: {p!r}")
    return int(m.group(1))


def verificar_pinos(pinos: list, uso: str, wifi_ativo: bool = True, caminho_tabela: str = "") -> dict:
    if uso not in USOS:
        raise ErroFerramenta(f"uso deve ser um de {USOS}")
    tab = carregar_tabela(caminho_tabela)
    por_gpio = {p["gpio"]: p for p in tab["pinos"]}
    restr = tab["restricoes"]
    relatorio = []
    algum_bloqueio = False
    for bruto in pinos:
        g = _normalizar_pino(bruto)
        p = por_gpio.get(g)
        if p is None:
            relatorio.append({"pino": bruto, "gpio": g, "ok": False, "pode_usar": False,
                              "alertas": [{"gravidade": "proibido", "texto": "GPIO inexistente ou não exposto nesta placa."}]})
            algum_bloqueio = True
            continue
        alertas = []
        for nome in p.get("restricoes", []):
            r = restr[nome]
            if _APLICA[r["gravidade"]](uso, wifi_ativo):
                alertas.append({"restricao": nome, "gravidade": r["gravidade"], "texto": r["texto"],
                                "fonte": r["fonte"], "status": r["status"]})
        if uso == "analogico" and not p.get("adc"):
            alertas.append({"restricao": "sem_adc", "gravidade": "erro_se_saida",
                            "texto": "Este pino não tem conversor analógico (ADC).", "fonte": "tabela de pinos", "status": tab["status"]})
        if p.get("detalhe"):
            alertas.append({"restricao": "detalhe", "gravidade": "info", "texto": p["detalhe"],
                            "fonte": "ESP32 Series Datasheet, Strapping Pins", "status": tab["status"]})
        bloqueia = any(a["gravidade"] in _BLOQUEIA for a in alertas)
        algum_bloqueio |= bloqueia
        relatorio.append({"pino": bruto, "gpio": g, "serigrafia": p["serigrafia"], "adc": p.get("adc"),
                          "ok": not bloqueia and not alertas, "pode_usar": not bloqueia, "alertas": alertas})

    sugestoes = []
    if uso == "analogico":
        # Pinos analógicos sem nenhuma restrição aplicável a esse uso com Wi-Fi.
        for p in tab["pinos"]:
            if p.get("adc", "").startswith("ADC1") and all(
                not _APLICA[restr[n]["gravidade"]](uso, wifi_ativo) for n in p["restricoes"]
            ):
                sugestoes.append(f"GPIO{p['gpio']} ({p['serigrafia']}, {p['adc']})")
    return {
        "resultado": {"pinos": relatorio, "algum_bloqueio": algum_bloqueio, "sugestoes_livres": sugestoes},
        "formula": "consulta à tabela dados_ref/esp32_pinos.yaml",
        "notas": [f"Status da tabela: {tab['status']} (restrições ainda não conferidas contra o datasheet indexado)."
                  if tab["status"] != "confirmado" else "Tabela conferida contra o datasheet."],
    }
