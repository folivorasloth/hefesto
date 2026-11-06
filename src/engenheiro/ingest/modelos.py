"""Estruturas de dados da ingestão.

O extrator (Docling) converte o PDF numa lista de `Bloco`, um formato nosso,
simples e neutro. O chunker só conhece `Bloco`. Isso tem duas vantagens:
- o chunker é testável sem o Docling (que é lento e baixa modelos);
- se um dia trocarmos o Docling pelo Marker, só o extrator muda.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

TipoBloco = Literal["titulo", "paragrafo", "item_lista", "tabela", "figura"]

# De onde veio o texto. Importa para a confiança: texto nativo do PDF é o mais
# confiável; OCR pode trocar "1,37" por "1,87"; descrição de figura feita por
# modelo de visão é uma interpretação, não uma transcrição.
Origem = Literal["texto", "ocr", "visao"]


@dataclass
class Bloco:
    tipo: TipoBloco
    texto: str
    pagina: int                      # página física do PDF (1 = primeira folha)
    nivel: int = 0                   # só para títulos: 1 = capítulo, 2 = seção...
    origem: Origem = "texto"
    figura_ref: str | None = None    # caminho da imagem salva, se for figura


@dataclass
class DocumentoExtraido:
    blocos: list[Bloco]
    n_paginas: int
    paginas_ocr: list[int] = field(default_factory=list)
    titulo_pdf: str | None = None

    def para_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def de_dict(cls, d: dict) -> "DocumentoExtraido":
        return cls(
            blocos=[Bloco(**b) for b in d["blocos"]],
            n_paginas=d["n_paginas"],
            paginas_ocr=d.get("paginas_ocr", []),
            titulo_pdf=d.get("titulo_pdf"),
        )


@dataclass
class Trecho:
    texto: str
    caminho_titulos: list[str]
    pagina_inicio: int
    pagina_fim: int
    tipos: list[str]                 # tipos de unidade presentes: tabela, procedimento, aviso...
    origens: list[str]               # texto / ocr / visao
    oversize: bool = False           # unidade atômica maior que o máximo, mantida inteira
    figuras: list[str] = field(default_factory=list)

    @property
    def secao(self) -> str:
        return " > ".join(self.caminho_titulos)

    def texto_para_indexar(self) -> str:
        # O caminho de títulos entra no texto que vira embedding: um parágrafo
        # solto como "aperte em espiral" só faz sentido sabendo que está em
        # "Motor > Torques do cabeçote".
        return f"{self.secao}\n\n{self.texto}" if self.caminho_titulos else self.texto
