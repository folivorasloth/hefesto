"""Reescrita da pergunta em variantes de busca, e roteamento por coleção.

Fase 1: só a camada determinística (glossário). A fase 2 acrescenta uma
variante gerada pelo modelo rápido (tradução livre para o inglês), que entra
como mais uma lista na fusão RRF. Se o LLM estiver desligado, a busca segue
com as variantes do glossário.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


@dataclass
class EntradaGlossario:
    pt: list[str]
    en: list[str]
    colecoes: list[str]


@dataclass
class Glossario:
    entradas: list[EntradaGlossario]

    @classmethod
    def carregar(cls, caminho: Path) -> "Glossario":
        if not caminho.exists():
            return cls([])
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        return cls([EntradaGlossario(e.get("pt", []), e.get("en", []), e.get("colecoes", [])) for e in dados.get("termos", [])])

    def encontrar(self, texto: str) -> list[tuple[str, EntradaGlossario]]:
        """Devolve (forma encontrada, entrada) para cada termo presente no texto."""
        alvo = f" {normalizar(texto)} "
        achados = []
        for e in self.entradas:
            for forma in e.pt + e.en:
                f = normalizar(forma)
                if re.search(rf"(?<![\w]){re.escape(f)}(?![\w])", alvo):
                    achados.append((forma, e))
                    break
        return achados


@dataclass
class Variante:
    tipo: str      # "original", "expandida", "ingles", "llm_ingles" (fase 2)
    texto: str


@dataclass
class Roteamento:
    colecoes: list[str]
    motivo: str
    termos: list[str] = field(default_factory=list)


def gerar_variantes(pergunta: str, glossario: Glossario) -> list[Variante]:
    achados = glossario.encontrar(pergunta)
    variantes = [Variante("original", pergunta)]
    if not achados:
        return variantes
    sinonimos_pt = [s for _, e in achados for s in e.pt]
    termos_en = [s for _, e in achados for s in e.en]
    expandida = " ".join(dict.fromkeys([pergunta, *sinonimos_pt, *termos_en]))
    variantes.append(Variante("expandida", expandida))
    if termos_en:
        variantes.append(Variante("ingles", " ".join(dict.fromkeys(termos_en))))
    return variantes


def rotear(pergunta: str, glossario: Glossario, todas: list[str], sempre: list[str], modo: str) -> Roteamento:
    sempre = [c for c in sempre if c in todas]
    if modo == "todas":
        return Roteamento(list(todas), "config: roteamento = todas")
    achados = glossario.encontrar(pergunta)
    escolhidas = {c for _, e in achados for c in e.colecoes if c in todas}
    if not escolhidas:
        # Sem pista nenhuma: é melhor buscar em tudo do que adivinhar e perder
        # a fonte certa. Custa só um pouco mais de tempo.
        return Roteamento(list(todas), "nenhum termo do glossário reconhecido: buscando em todas")
    ordem = [c for c in todas if c in escolhidas or c in sempre]
    return Roteamento(ordem, "termos do glossário + coleções sempre incluídas", [f for f, _ in achados])
