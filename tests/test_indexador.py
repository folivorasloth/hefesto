"""Indexação incremental, com um extrator falso (sem Docling)."""

from pathlib import Path

import yaml

from engenheiro.config import Config
from engenheiro.dev.embedder_falso import EmbedderFalso
from engenheiro.ingest.extrator import ExtratorTexto
from engenheiro.ingest.indexador import Indexador
from engenheiro.ingest.modelos import Bloco, DocumentoExtraido
from engenheiro.llm.ollama import OllamaIndisponivel
from engenheiro.store.db import Banco


class ExtratorFalso:
    def __init__(self):
        self.chamadas = 0

    def impressao_digital(self):
        return "falso-v1"

    def extrair(self, caminho: Path, id_figuras="doc"):
        self.chamadas += 1
        texto = caminho.read_bytes().decode(errors="ignore")
        return DocumentoExtraido(
            [Bloco("titulo", "Capítulo", 1, nivel=1), Bloco("paragrafo", texto, 2)], n_paginas=2
        )


class EmbedderDesligado:
    nome = EmbedderFalso.nome

    def embed(self, textos):
        raise OllamaIndisponivel("notebook desligado")


def _montar(tmp_path, embedder=None):
    cfg = Config(raiz=tmp_path)
    bib = tmp_path / "data" / "biblioteca"
    (bib / "veiculo").mkdir(parents=True)
    banco = Banco(tmp_path / "indice.sqlite")
    ext = ExtratorFalso()
    idx = Indexador(cfg, banco, ext, ExtratorTexto(), embedder or EmbedderFalso())
    return cfg, bib, banco, ext, idx


def test_segunda_execucao_nao_reprocessa(tmp_path):
    _, bib, banco, ext, idx = _montar(tmp_path)
    (bib / "veiculo" / "a.pdf").write_bytes(b"texto do manual sobre carburador")
    r1 = idx.indexar()
    assert r1.processados == ["veiculo/a.pdf"] and r1.embeddings_gerados == 1
    r2 = idx.indexar()
    assert r2.processados == [] and r2.inalterados == ["veiculo/a.pdf"]
    assert ext.chamadas == 1


def test_arquivo_alterado_e_reprocessado(tmp_path):
    _, bib, banco, ext, idx = _montar(tmp_path)
    arq = bib / "veiculo" / "a.pdf"
    arq.write_bytes(b"versao 1")
    idx.indexar()
    arq.write_bytes(b"versao 2")
    r = idx.indexar()
    assert r.processados == ["veiculo/a.pdf"]
    assert banco.estatisticas()["trechos"] == 1  # versão antiga foi removida


def test_ficha_alterada_reaproveita_extracao_do_cache(tmp_path):
    _, bib, banco, ext, idx = _montar(tmp_path)
    arq = bib / "veiculo" / "a.pdf"
    arq.write_bytes(b"conteudo")
    idx.indexar()
    arq.with_suffix(".yaml").write_text(yaml.safe_dump({"titulo": "Manual do Gol", "citacao": "Manual Gol", "deslocamento_paginas": 2}))
    r = idx.indexar()
    assert r.processados == ["veiculo/a.pdf"]
    assert ext.chamadas == 1  # não extraiu de novo
    doc = banco.documento("veiculo/a.pdf")
    assert doc["citacao"] == "Manual Gol" and doc["deslocamento_paginas"] == 2


def test_arquivo_apagado_sai_do_indice(tmp_path):
    _, bib, banco, ext, idx = _montar(tmp_path)
    arq = bib / "veiculo" / "a.pdf"
    arq.write_bytes(b"x")
    idx.indexar()
    arq.unlink()
    r = idx.indexar()
    assert r.removidos == ["veiculo/a.pdf"]
    assert banco.estatisticas()["trechos"] == 0


def test_ollama_desligado_deixa_pendente_e_completa_depois(tmp_path):
    cfg, bib, banco, ext, _ = _montar(tmp_path)
    (bib / "veiculo" / "a.pdf").write_bytes(b"texto")
    r = Indexador(cfg, banco, ext, ExtratorTexto(), EmbedderDesligado()).indexar()
    assert r.embeddings_pendentes == 1 and any("indisponível" in a for a in r.avisos)
    assert banco.estatisticas()["trechos"] == 1  # texto já está no índice (BM25)
    r2 = Indexador(cfg, banco, ext, ExtratorTexto(), EmbedderFalso()).indexar()
    assert r2.embeddings_gerados == 1 and banco.estatisticas()["sem_embedding"] == 0


def test_pasta_que_nao_e_colecao_e_ignorada_com_aviso(tmp_path):
    _, bib, banco, ext, idx = _montar(tmp_path)
    (bib / "aleatoria").mkdir()
    (bib / "aleatoria" / "x.pdf").write_bytes(b"x")
    r = idx.indexar()
    assert r.pastas_desconhecidas == ["aleatoria"] and r.processados == []


def test_markdown_do_caderno(tmp_path):
    cfg, bib, banco, ext, idx = _montar(tmp_path)
    (bib / "caderno_de_bordo").mkdir()
    (bib / "caderno_de_bordo" / "2026-11-06.md").write_text(
        "# Medição da bateria\n\nMedi 12,4 V com o motor desligado.\n\n1. Desliguei tudo\n2. Esperei 1 h\n3. Medi",
        encoding="utf-8",
    )
    idx.indexar()
    t = banco.obter_trechos([1])[1]
    assert t.secao == "Medição da bateria" and "procedimento" in t.tipos
