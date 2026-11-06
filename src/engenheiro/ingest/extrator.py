"""Extração de documentos para a lista de `Bloco`.

- PDF: Docling (layout, tabelas, hierarquia de títulos, OCR via Tesseract).
- Markdown/texto: leitor simples (usado no caderno de bordo e em notas suas).

O Docling é importado só dentro do extrator de PDF, porque ele puxa torch e é
lento para carregar. Quem só faz busca não paga esse custo.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable

from .modelos import Bloco, DocumentoExtraido

log = logging.getLogger(__name__)

# Versão da lógica de extração. Mudou o código de forma que altera a saída?
# Incremente: o cache de extração é invalidado e tudo é reextraído.
VERSAO_EXTRATOR = "1"

# Função opcional que descreve uma figura: (imagem PIL, legenda) -> texto.
DescritorFigura = Callable[[object, str], str]


def paginas_sem_texto(caminho: Path, limiar: int) -> list[int]:
    """Páginas cuja camada de texto nativa tem menos de `limiar` caracteres.

    Usado para marcar a origem "ocr": o Docling roda o OCR por conta própria,
    mas não diz de qual página o texto veio do OCR. Olhar a camada de texto
    do PDF resolve isso de forma direta e verificável.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(caminho))
    try:
        vazias = []
        for i in range(len(pdf)):
            tp = pdf[i].get_textpage()
            if len(tp.get_text_range().strip()) < limiar:
                vazias.append(i + 1)
        return vazias
    finally:
        pdf.close()


class ExtratorPDF:
    def __init__(
        self,
        ocr_ativo: bool = True,
        idiomas_ocr: list[str] | None = None,
        limiar_ocr: int = 30,
        pasta_figuras: Path | None = None,
        descritor_figura: DescritorFigura | None = None,
    ) -> None:
        self.ocr_ativo = ocr_ativo
        self.idiomas_ocr = idiomas_ocr or ["por", "eng"]
        self.limiar_ocr = limiar_ocr
        self.pasta_figuras = pasta_figuras
        self.descritor_figura = descritor_figura
        self._conversor = None

    def impressao_digital(self) -> str:
        """Identifica a configuração que afeta a saída (entra na chave do cache)."""
        return (
            f"pdf-v{VERSAO_EXTRATOR}|ocr={self.ocr_ativo}:{','.join(self.idiomas_ocr)}"
            f"|visao={self.descritor_figura is not None}"
        )

    def _obter_conversor(self):
        if self._conversor is None:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import (
                HeadingHierarchyOptions,
                PdfPipelineOptions,
                TesseractCliOcrOptions,
            )
            from docling.document_converter import DocumentConverter, PdfFormatOption

            opcoes = PdfPipelineOptions(
                do_ocr=self.ocr_ativo,
                do_table_structure=True,
                generate_picture_images=self.pasta_figuras is not None,
                images_scale=2.0,
                # Tesseract em vez do RapidOCR padrão: roda 100% local, tem
                # pacote de português no apt e não baixa modelos de terceiros.
                ocr_options=TesseractCliOcrOptions(lang=self.idiomas_ocr),
                # Sem isto, o Docling põe todo título no nível 1 e perdemos
                # a hierarquia capítulo > seção > subseção.
                heading_hierarchy_options=HeadingHierarchyOptions(enabled=True),
            )
            self._conversor = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opcoes)}
            )
        return self._conversor

    def extrair(self, caminho: Path, id_figuras: str = "doc") -> DocumentoExtraido:
        from docling_core.types.doc import DocItemLabel, PictureItem, TableItem

        resultado = self._obter_conversor().convert(str(caminho))
        doc = resultado.document
        paginas_ocr = paginas_sem_texto(caminho, self.limiar_ocr) if self.ocr_ativo else []

        # Legendas de tabela/figura aparecem também como itens soltos; guardamos
        # quais são para não duplicá-las como parágrafos.
        refs_legendas: set[str] = set()
        for item, _ in doc.iterate_items():
            for ref in getattr(item, "captions", []) or []:
                refs_legendas.add(ref.cref)

        blocos: list[Bloco] = []
        n_fig = 0
        for item, _ in doc.iterate_items():
            if not item.prov:
                continue
            pagina = item.prov[0].page_no
            origem = "ocr" if pagina in paginas_ocr else "texto"
            rotulo = item.label

            if rotulo in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER):
                nivel = getattr(item, "level", 1) if rotulo == DocItemLabel.SECTION_HEADER else 1
                blocos.append(Bloco("titulo", item.text, pagina, nivel=nivel, origem=origem))
            elif rotulo == DocItemLabel.DOCUMENT_INDEX:
                # Sumário: casa com quase toda busca por palavra-chave e não
                # contém informação técnica. Fica de fora de propósito.
                continue
            elif rotulo == DocItemLabel.CAPTION and item.self_ref in refs_legendas:
                continue
            elif isinstance(item, TableItem):
                legenda = item.caption_text(doc)
                md = item.export_to_markdown(doc=doc)
                texto = f"{legenda}\n{md}" if legenda else md
                blocos.append(Bloco("tabela", texto, pagina, origem=origem))
            elif isinstance(item, PictureItem):
                n_fig += 1
                blocos.append(self._bloco_figura(item, doc, pagina, n_fig, id_figuras))
            elif rotulo == DocItemLabel.LIST_ITEM:
                blocos.append(Bloco("item_lista", item.text, pagina, origem=origem))
            elif getattr(item, "text", "").strip():
                blocos.append(Bloco("paragrafo", item.text, pagina, origem=origem))

        titulo = None
        try:
            titulo = doc.name or None
        except AttributeError:
            pass
        return DocumentoExtraido(blocos, doc.num_pages(), paginas_ocr, titulo)

    def _bloco_figura(self, item, doc, pagina: int, n: int, id_figuras: str) -> Bloco:
        legenda = item.caption_text(doc) or ""
        ref = None
        imagem = None
        if self.pasta_figuras is not None:
            try:
                imagem = item.get_image(doc)
            except Exception:  # noqa: BLE001 - figura sem imagem não deve parar a ingestão
                imagem = None
            if imagem is not None:
                destino = self.pasta_figuras / id_figuras / f"p{pagina:04d}_fig{n:03d}.png"
                destino.parent.mkdir(parents=True, exist_ok=True)
                imagem.save(destino)
                ref = str(destino)

        partes = [f"[Figura {n}, página {pagina}]"]
        if legenda:
            partes.append(f"Legenda: {legenda}")
        origem = "texto"
        if self.descritor_figura is not None and imagem is not None:
            try:
                descricao = self.descritor_figura(imagem, legenda)
                # O aviso vai no próprio texto indexado: quem ler o trecho
                # (você ou o LLM) sabe que aquilo é interpretação de um modelo.
                partes.append(
                    "Descrição gerada automaticamente por modelo de visão (NÃO VERIFICADA): "
                    + descricao.strip()
                )
                origem = "visao"
            except Exception as e:  # noqa: BLE001
                log.warning("Falha ao descrever figura %s na p. %s: %s", n, pagina, e)
        return Bloco("figura", "\n".join(partes), pagina, origem=origem, figura_ref=ref)


_RE_TITULO_MD = re.compile(r"^(#{1,6})\s+(.*)$")


class ExtratorTexto:
    """Markdown ou texto puro. Títulos `#` viram seções; cada parágrafo
    (separado por linha em branco) vira um bloco. Arquivos de texto não têm
    página: tudo fica na "página" 1."""

    def impressao_digital(self) -> str:
        return f"texto-v{VERSAO_EXTRATOR}"

    def extrair(self, caminho: Path, id_figuras: str = "doc") -> DocumentoExtraido:
        texto = caminho.read_text(encoding="utf-8")
        blocos: list[Bloco] = []
        for paragrafo in re.split(r"\n\s*\n", texto):
            paragrafo = paragrafo.strip()
            if not paragrafo:
                continue
            m = _RE_TITULO_MD.match(paragrafo)
            if m and "\n" not in paragrafo:
                blocos.append(Bloco("titulo", m.group(2).strip(), 1, nivel=len(m.group(1))))
            elif re.match(r"^\s*([-*]|\d+[.)])\s", paragrafo):
                # Lista: um bloco por item, para o chunker reconhecer procedimentos.
                for linha in paragrafo.splitlines():
                    linha = re.sub(r"^\s*[-*]\s+", "", linha).strip()
                    if linha:
                        blocos.append(Bloco("item_lista", linha, 1))
            else:
                blocos.append(Bloco("paragrafo", paragrafo, 1))
        return DocumentoExtraido(blocos, n_paginas=1)
