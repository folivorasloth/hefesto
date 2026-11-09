"""A CLI precisa mostrar a citação: o Rich trata [colchetes] como marcação,
e uma versão anterior apagava "[Livro, p. X]" da tela sem erro nenhum."""

from typer.testing import CliRunner

from engenheiro.ingest.modelos import Trecho
from engenheiro.interfaces.cli import app
from engenheiro.store.db import Banco, DadosDocumento


def test_buscar_mostra_citacao_e_pagina(tmp_path):
    indice = tmp_path / "i.sqlite"
    b = Banco(indice)
    d = DadosDocumento("veiculo/m.pdf", "veiculo", "s", "d", "Manual", "Manual Gol", deslocamento_paginas=2)
    b.substituir_documento(d, [Trecho("torque do cabeçote 17,3", ["Motor"], 7, 7, ["paragrafo"], ["texto"])], ["pt"])
    b.fechar()
    r = CliRunner().invoke(
        app, ["buscar", "--indice", str(indice), "--sem-rerank", "--config", str(tmp_path / "x.yaml"), "torque"],
        env={"COLUMNS": "200"},
    )
    assert r.exit_code == 0, r.output
    assert "[Manual Gol, p. 5]" in r.output


def test_buscar_sem_resultado_diz_que_nao_encontrou(tmp_path):
    indice = tmp_path / "i.sqlite"
    Banco(indice).fechar()
    r = CliRunner().invoke(app, ["buscar", "--indice", str(indice), "--sem-rerank", "torque"])
    assert r.exit_code == 2 and "Nada encontrado" in r.output
