"""Busca por palavra-chave (BM25/FTS5), busca vetorial e fusão RRF."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import sqlite_vec

from .db import Banco

# Palavras sem valor de busca. Lista curta de propósito: num texto técnico,
# palavras como "não", "sem" e "antes" podem importar, então não entram aqui.
_STOPWORDS = set(
    """
    a o as os um uma uns umas de do da dos das no na nos nas em por para pra com
    e ou que qual quais como onde quando se eu me meu minha voce você isso isto esse essa
    ele ela eles elas ao aos à às é ser está estao estão tem ter há
    the an of to in on for and or is are be with how what which do does can my
    """.split()
)

_RE_TOKEN = re.compile(r"[\w]+(?:[-./][\w]+)*", re.UNICODE)


def _sem_acento(t: str) -> str:
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c))


def termos_tecnicos(texto: str) -> list[str]:
    """Termos que parecem códigos exatos: misturam letras e dígitos (GPIO34,
    LM2596, AT-90) ou são números com separadores (030-905-205)."""
    out = []
    for tok in _RE_TOKEN.findall(texto):
        tem_digito = any(c.isdigit() for c in tok)
        tem_letra = any(c.isalpha() for c in tok)
        if (tem_digito and tem_letra) or (tem_digito and re.search(r"[-./]", tok)):
            out.append(tok)
    return out


def consulta_fts(texto: str) -> str | None:
    """Converte texto livre numa expressão MATCH do FTS5.

    - cada termo vira uma string entre aspas (evita que "AND"/"NOT"/"-" na
      pergunta sejam interpretados como operadores do FTS5);
    - termos com hífen/ponto viram frase: "030-905-205" -> "030 905 205",
      que o FTS5 casa com os três tokens adjacentes;
    - termos são unidos por OR: o BM25 dá mais peso a quem tem os termos raros
      (como um código de peça), sem exigir que todas as palavras apareçam.
    """
    partes: list[str] = []
    vistos: set[str] = set()
    for tok in _RE_TOKEN.findall(texto):
        norm = _sem_acento(tok.lower())
        if norm in _STOPWORDS or (len(norm) < 2 and not norm.isdigit()):
            continue
        frase = " ".join(re.split(r"[-./]", norm))
        if frase in vistos:
            continue
        vistos.add(frase)
        partes.append('"' + frase.replace('"', "") + '"')
    return " OR ".join(partes) if partes else None


@dataclass
class Acerto:
    trecho_id: int
    posicao: int        # 1 = melhor
    score: float        # BM25 (maior = melhor) ou similaridade de cosseno


def buscar_bm25(banco: Banco, texto: str, colecoes: list[str], n: int) -> list[Acerto]:
    expr = consulta_fts(texto)
    if not expr or not colecoes:
        return []
    marcas = ",".join("?" * len(colecoes))
    # bm25() do FTS5 devolve valores negativos (mais negativo = melhor).
    # Peso 2.0 na coluna `secao`: termo no título da seção é sinal forte.
    linhas = banco.con.execute(
        f"SELECT f.rowid AS id, bm25(trechos_fts, 1.0, 2.0) AS s FROM trechos_fts f "
        f"JOIN trechos t ON t.id = f.rowid "
        f"WHERE trechos_fts MATCH ? AND t.colecao IN ({marcas}) ORDER BY s LIMIT ?",
        [expr, *colecoes, n],
    ).fetchall()
    return [Acerto(r["id"], i + 1, -r["s"]) for i, r in enumerate(linhas)]


def buscar_vetor(banco: Banco, vetor: list[float], colecoes: list[str], n: int) -> list[Acerto]:
    if not banco.tem_tabela_vetorial or not colecoes:
        return []
    marcas = ",".join("?" * len(colecoes))
    linhas = banco.con.execute(
        f"SELECT trecho_id, distance FROM trechos_vec WHERE embedding MATCH ? AND k = ? "
        f"AND colecao IN ({marcas}) ORDER BY distance",
        [sqlite_vec.serialize_float32(vetor), n, *colecoes],
    ).fetchall()
    # distância de cosseno = 1 - similaridade
    return [Acerto(r["trecho_id"], i + 1, 1.0 - r["distance"]) for i, r in enumerate(linhas)]


def fundir_rrf(listas: dict[str, list[Acerto]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: score = soma de 1/(k + posição) em cada lista.

    Por que RRF e não somar scores: BM25 e cosseno estão em escalas
    incomparáveis. RRF usa só a posição, então não precisa de calibração e
    é fácil de explicar no rastro.
    """
    total: dict[int, float] = {}
    for acertos in listas.values():
        for a in acertos:
            total[a.trecho_id] = total.get(a.trecho_id, 0.0) + 1.0 / (k + a.posicao)
    return sorted(total.items(), key=lambda x: x[1], reverse=True)
