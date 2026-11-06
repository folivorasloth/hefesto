"""Embedder FALSO para testes e demonstração sem Ollama.

Não é semântico de verdade: é um "saco de palavras" com hashing. Serve para
testar o encanamento (gravar vetores, buscar por similaridade, fundir com BM25)
sem depender do notebook do LLM ligado. Nunca use num índice real: o índice
grava o nome do embedder e recusa misturar vetores de embedders diferentes.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from engenheiro.llm.ollama import normalizar

DIM_FALSA = 256


def _tokens(texto: str) -> list[str]:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.findall(r"\w+", t)


class EmbedderFalso:
    nome = f"falso:hash{DIM_FALSA}"

    def embed(self, textos: list[str]) -> list[list[float]]:
        vetores = []
        for texto in textos:
            v = [0.0] * DIM_FALSA
            for tok in _tokens(texto):
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                v[h % DIM_FALSA] += 1.0 if (h >> 8) & 1 else -1.0
            vetores.append(normalizar(v))
        return vetores
