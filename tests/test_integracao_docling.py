"""Critério de aceite da fase 1, com o Docling de verdade sobre o corpus fictício.

Lento (minutos na primeira vez, porque baixa os modelos de layout). Rode com:
    pytest -m docling
Usa o embedder FALSO (sem Ollama) e sem reranker: aqui testamos extração,
corte, metadados e a busca por palavra-chave/fusão. A qualidade semântica
real (bge-m3 + reranker) é medida no eval, na sua máquina.
"""

import shutil
from pathlib import Path

import pytest

from engenheiro.config import Config
from engenheiro.dev.corpus_teste import gerar_corpus
from engenheiro.dev.embedder_falso import EmbedderFalso
from engenheiro.ingest.extrator import ExtratorPDF, ExtratorTexto
from engenheiro.ingest.indexador import Indexador
from engenheiro.recuperacao.pipeline import Recuperador
from engenheiro.recuperacao.reescrita import Glossario
from engenheiro.store.db import Banco

pytestmark = [
    pytest.mark.docling,
    pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract não instalado"),
]


@pytest.fixture(scope="module")
def indice(tmp_path_factory):
    raiz = tmp_path_factory.mktemp("integ")
    bib = raiz / "biblioteca"
    gerar_corpus(bib)
    cfg = Config(raiz=raiz)
    banco = Banco(raiz / "indice.sqlite")
    ext = ExtratorPDF(pasta_figuras=raiz / "figuras")
    rel = Indexador(cfg, banco, ext, ExtratorTexto(), EmbedderFalso(), biblioteca=bib).indexar()
    assert not rel.erros, rel.erros
    glossario = Glossario.carregar(Path(__file__).parents[1] / "dados_ref" / "glossario.yaml")
    return cfg, banco, Recuperador(cfg, banco, glossario, EmbedderFalso(), None)


def _todos(banco):
    ids = [r[0] for r in banco.con.execute("SELECT id FROM trechos")]
    return list(banco.obter_trechos(ids).values())


def test_tabela_inteira_num_trecho(indice):
    _, banco, _ = indice
    tabs = [t for t in _todos(banco) if "tabela" in t.tipos]
    assert len(tabs) == 1
    assert "17,3" in tabs[0].texto and "+ 93 graus" in tabs[0].texto
    assert tabs[0].secao.endswith("1.1 Torques de aperto do cabeçote")


def test_procedimento_inteiro_com_aviso_apesar_da_quebra_de_pagina(indice):
    _, banco, _ = indice
    procs = [t for t in _todos(banco) if "procedimento" in t.tipos]
    assert len(procs) == 1
    p = procs[0]
    assert p.texto.count("Detalhe fictício adicional.") >= 60  # os 10 passos
    assert "ATENÇÃO" in p.texto and "aviso" in p.tipos
    assert p.pagina_inicio == 1 and p.pagina_fim == 2


def test_rodape_de_pagina_nao_entra(indice):
    _, banco, _ = indice
    assert not any("pág. 1" in t.texto for t in _todos(banco))


def test_pdf_escaneado_vira_ocr_e_e_marcado(indice):
    _, banco, _ = indice
    esc = [t for t in _todos(banco) if t.arquivo.startswith("carburacao_etanol/")]
    assert esc and all(t.origens == ["ocr"] for t in esc)
    assert any("1,37" in t.texto for t in esc)


def test_idioma_detectado(indice):
    _, banco, _ = indice
    # Só as seções 3.1/3.2: o corpus fictício põe enchimento em português no fim.
    en = [t for t in _todos(banco) if t.secao.endswith(("3.1 Hall effect sensor in the distributor", "3.2 Checking the ignition coil"))]
    assert len(en) == 2 and all(t.idioma == "en" for t in en)
    pt = [t for t in _todos(banco) if t.secao.endswith("1.1 Torques de aperto do cabeçote")]
    assert pt and all(t.idioma == "pt" for t in pt)


@pytest.mark.parametrize(
    "pergunta, secao_esperada",
    [
        ("qual o torque de aperto do cabeçote?", "1.1 Torques de aperto do cabeçote"),
        ("como regular a marcha lenta?", "1.2 Regulagem da marcha lenta"),
        ("código de peça do relé 030-905-205", "2.1 Peças de reposição"),
        ("posso usar o GPIO34 com pull-up?", "4 Entradas analógicas"),
        ("como funciona o sensor hall do distribuidor?", "3.1 Hall effect sensor in the distributor"),
        ("resistência do primário da bobina", "3.2 Checking the ignition coil"),
        ("diâmetro do giclê principal", "Apostila Ficticia de Carburacao"),
    ],
)
def test_recupera_secao_certa(indice, pergunta, secao_esperada):
    _, _, rec = indice
    res = rec.buscar(pergunta, final=3)
    secoes = [c.trecho.secao for c in res.finais]
    assert any(s.endswith(secao_esperada) for s in secoes), secoes
