from types import SimpleNamespace

from engenheiro.avaliacao import casa_fonte, comparar


def _c(arquivo="veiculo/m.pdf", ini=10, fim=11, secao="Motor > Cabeçote"):
    return SimpleNamespace(trecho=SimpleNamespace(arquivo=arquivo, pagina_inicio=ini, pagina_fim=fim, secao=secao))


def test_casa_fonte():
    assert casa_fonte(_c(), {"arquivo": "veiculo/m.pdf"})
    assert casa_fonte(_c(), {"arquivo": "veiculo/m.pdf", "paginas_pdf": [11], "secao_contem": "cabeçote"})
    assert not casa_fonte(_c(), {"arquivo": "veiculo/m.pdf", "paginas_pdf": [12]})
    assert not casa_fonte(_c(), {"arquivo": "outro.pdf"})
    assert not casa_fonte(_c(), {"arquivo": "veiculo/m.pdf", "secao_contem": "Ignição"})


def test_comparar_mostra_o_que_piorou():
    antes = {"execucao": "A", "metricas": {"acerto@6": 1.0}, "itens": [{"id": "x", "acertou": True}, {"id": "y", "acertou": False}]}
    agora = {"execucao": "B", "metricas": {"acerto@6": 0.5}, "itens": [{"id": "x", "acertou": False}, {"id": "y", "acertou": True}]}
    c = comparar(agora, antes)
    assert c["pioraram"] == ["x"] and c["melhoraram"] == ["y"] and c["delta"]["acerto@6"] == -0.5
