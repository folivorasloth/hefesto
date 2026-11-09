"""Avisos de segurança determinísticos.

O LLM pode esquecer um aviso; este módulo não esquece. Ele lê
dados_ref/seguranca.yaml e devolve os avisos dos temas cujos gatilhos
aparecem na pergunta ou na resposta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from engenheiro.recuperacao.reescrita import normalizar


@dataclass
class AvisoTema:
    tema: str
    gatilho: str
    avisos: list[str]


class Seguranca:
    def __init__(self, temas: dict[str, dict]) -> None:
        self.temas = temas

    @classmethod
    def carregar(cls, caminho: Path) -> "Seguranca":
        if not caminho.exists():
            # Sem o arquivo, o sistema fica sem avisos: isso tem que ser
            # barulhento, não silencioso.
            raise FileNotFoundError(f"Arquivo de avisos de segurança não encontrado: {caminho}")
        return cls((yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}).get("temas", {}))

    def avisos_para(self, *textos: str) -> list[AvisoTema]:
        alvo = " " + normalizar(" ".join(textos)) + " "
        saida = []
        for nome, tema in self.temas.items():
            for g in tema.get("gatilhos", []):
                # Início de palavra: "bateria" casa com "baterias".
                if re.search(rf"(?<!\w){re.escape(normalizar(g))}", alvo):
                    saida.append(AvisoTema(nome, g, tema.get("avisos", [])))
                    break
        return saida
