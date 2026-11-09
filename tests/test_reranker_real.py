"""Reranker de verdade (baixa ~2 GB na primeira vez). Rode com: pytest -m reranker"""

import pytest

from engenheiro.recuperacao.reranker import RerankerCrossEncoder

pytestmark = pytest.mark.reranker


@pytest.fixture(scope="module")
def rr():
    return RerankerCrossEncoder("BAAI/bge-reranker-v2-m3")


def test_prefere_o_trecho_relevante_mesmo_em_outro_idioma(rr):
    pergunta = "Como medir a resistência do primário da bobina de ignição?"
    textos = [
        "The fuel pump delivers fuel from the tank to the carburetor.",
        "Measure the primary winding resistance of the ignition coil with an ohmmeter.",
        "A correia dentada deve ser trocada no intervalo indicado pelo fabricante.",
    ]
    s = rr.pontuar(pergunta, textos)
    assert max(range(3), key=lambda i: s[i]) == 1
    assert all(0.0 <= x <= 1.0 for x in s)


def test_score_irrelevante_e_baixo(rr):
    # Regressão: sigmoide aplicada duas vezes dá sempre >= 0,5.
    s = rr.pontuar("torque do cabeçote do motor AP", ["A receita de bolo de cenoura leva três ovos."])
    assert s[0] < 0.1
