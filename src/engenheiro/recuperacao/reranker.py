"""Reranker (cross-encoder) que reordena os candidatos da busca híbrida.

O Ollama não tem endpoint de reranking estável, então o bge-reranker-v2-m3
roda aqui mesmo via sentence-transformers, em CPU. Para ~25 candidatos isso
leva alguns segundos, dentro da latência aceita.

O cross-encoder lê pergunta e trecho juntos, o que o torna muito mais preciso
que a similaridade de embeddings, e ele é multilíngue: compara uma pergunta
em português com um trecho em inglês diretamente.
"""

from __future__ import annotations

import math
from typing import Protocol


class Reranker(Protocol):
    nome: str

    def pontuar(self, pergunta: str, textos: list[str]) -> list[float]: ...


class RerankerCrossEncoder:
    def __init__(self, modelo: str, max_tokens: int = 1024, dispositivo: str = "cpu") -> None:
        self.modelo_nome = modelo
        self.max_tokens = max_tokens
        self.dispositivo = dispositivo
        self.nome = f"cross-encoder:{modelo}"
        self._modelo = None

    def _carregar(self):
        if self._modelo is None:
            import os

            # Sem barras de progresso no log do serviço.
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
            from engenheiro.dependencias import exigir

            exigir("sentence_transformers", "reranker", "O reranker")
            from sentence_transformers import CrossEncoder

            self._modelo = CrossEncoder(self.modelo_nome, max_length=self.max_tokens, device=self.dispositivo)
        return self._modelo

    def pontuar(self, pergunta: str, textos: list[str]) -> list[float]:
        if not textos:
            return []
        import torch

        # Pedimos os logits crus (Identity) e aplicamos a sigmoide nós mesmos.
        # Motivo: o sentence-transformers já aplica uma sigmoide por padrão, e
        # uma versão anterior deste código aplicava outra por cima, espremendo
        # todos os scores entre 0,50 e 0,73. A ordem não mudava, mas o score
        # perdia o sentido, e ele é a base do limiar de "não encontrei".
        brutos = self._carregar().predict(
            [(pergunta, t) for t in textos],
            batch_size=8,
            show_progress_bar=False,
            activation_fn=torch.nn.Identity(),
        )
        return [1.0 / (1.0 + math.exp(-float(s))) for s in brutos]
