from types import SimpleNamespace

from engenheiro.citacoes import citacao_de_trecho, formatar_citacao


def test_pagina_impressa_com_deslocamento():
    assert formatar_citacao("Denton", 67, 67, 22) == "[Denton, p. 45]"


def test_faixa_de_paginas():
    assert formatar_citacao("Denton", 67, 68, 22) == "[Denton, pp. 45–46]"


def test_sem_deslocamento_deixa_claro_que_e_pagina_do_pdf():
    assert formatar_citacao("Manual Gol", 12, 12, None) == "[Manual Gol, p. 12 do PDF]"
    assert formatar_citacao("Manual Gol", 12, 13, None) == "[Manual Gol, pp. 12–13 do PDF]"


def test_deslocamento_zero_e_valido():
    # 0 significa "páginas do PDF = páginas impressas", diferente de desconhecido.
    assert formatar_citacao("X", 5, 5, 0) == "[X, p. 5]"


def test_nota_de_texto_sem_pagina():
    t = SimpleNamespace(arquivo="caderno_de_bordo/2026-11-06.md", citacao="Caderno 2026-11-06",
                        pagina_inicio=1, pagina_fim=1, deslocamento_paginas=None)
    assert citacao_de_trecho(t) == "[Caderno 2026-11-06]"
