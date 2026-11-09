"""Formatação de citações no formato [Livro, p. X].

Detalhe que importa para a correção: o número de página que o Docling dá é o
da folha do PDF, não o número impresso no livro (que costuma ser diferente
por causa de capa, sumário, prefácio em romanos...). Se a citação mostrasse
"p. 67" e o livro impresso tivesse aquilo na p. 45, você iria procurar no
lugar errado. Então:

- com `deslocamento_paginas` informado no arquivo .yaml ao lado do PDF:
  mostramos a página impressa;
- sem ele: mostramos "p. 67 do PDF", deixando explícito de onde vem o número.
"""

from __future__ import annotations


def _pagina(p_pdf: int, deslocamento: int | None) -> int:
    return p_pdf - deslocamento if deslocamento is not None else p_pdf


def formatar_paginas(inicio: int, fim: int, deslocamento: int | None) -> str:
    a, b = _pagina(inicio, deslocamento), _pagina(fim, deslocamento)
    faixa = f"pp. {a}–{b}" if b != a else f"p. {a}"
    if deslocamento is None:
        faixa += " do PDF"
    return faixa


def formatar_citacao(citacao: str, inicio: int, fim: int, deslocamento: int | None, sem_paginas: bool = False) -> str:
    """Ex.: [Denton, p. 45], [Denton, pp. 45–46], [Denton, p. 67 do PDF].

    `sem_paginas` serve para notas de texto (caderno de bordo), que não têm página.
    """
    if sem_paginas:
        return f"[{citacao}]"
    return f"[{citacao}, {formatar_paginas(inicio, fim, deslocamento)}]"


def citacao_de_trecho(t) -> str:
    """Aceita um TrechoArmazenado (ou qualquer objeto com os mesmos campos)."""
    sem_paginas = t.arquivo.lower().endswith((".md", ".txt"))
    return formatar_citacao(t.citacao, t.pagina_inicio, t.pagina_fim, t.deslocamento_paginas, sem_paginas)
