"""Indexação incremental da biblioteca.

Estrutura esperada:

    data/biblioteca/
        veiculo/
            manual_gol.pdf
            manual_gol.yaml      <- opcional: título, nome curto, deslocamento de página
        ignicao/
            ...

Três níveis de cache, do mais caro para o mais barato:
1. Extração (Docling + OCR + visão): chave = sha256 do PDF + config do extrator.
   É o que leva minutos por livro; nunca repete sem necessidade.
2. Trechos: refeitos se mudar o .yaml do livro ou a config de corte.
3. Embeddings: só para trechos marcados como pendentes. Se o Ollama estiver
   desligado, o texto entra no índice mesmo assim (a busca por palavra-chave
   já funciona) e os vetores são gerados numa próxima execução.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from engenheiro.config import Config
from engenheiro.eventos import Barramento
from engenheiro.llm.ollama import Embedder, OllamaIndisponivel
from engenheiro.store.db import Banco, DadosDocumento

from . import chunker, idioma
from .modelos import DocumentoExtraido

log = logging.getLogger(__name__)

EXTENSOES_PDF = {".pdf"}
EXTENSOES_TEXTO = {".md", ".txt"}


@dataclass
class RelatorioIndexacao:
    processados: list[str] = field(default_factory=list)
    inalterados: list[str] = field(default_factory=list)
    removidos: list[str] = field(default_factory=list)
    erros: dict[str, str] = field(default_factory=dict)
    pastas_desconhecidas: list[str] = field(default_factory=list)
    embeddings_gerados: int = 0
    embeddings_pendentes: int = 0
    avisos: list[str] = field(default_factory=list)


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def ler_ficha(caminho_doc: Path) -> dict:
    """Lê o .yaml opcional ao lado do documento (a "ficha" do livro)."""
    ficha = caminho_doc.with_suffix(".yaml")
    if ficha.exists():
        return yaml.safe_load(ficha.read_text(encoding="utf-8")) or {}
    return {}


class Indexador:
    def __init__(
        self,
        config: Config,
        banco: Banco,
        extrator_pdf,                     # ExtratorPDF ou um falso nos testes
        extrator_texto,
        embedder: Embedder | None,
        barramento: Barramento | None = None,
        biblioteca: Path | None = None,
    ) -> None:
        self.cfg = config
        self.banco = banco
        self.extrator_pdf = extrator_pdf
        self.extrator_texto = extrator_texto
        self.embedder = embedder
        self.bus = barramento or Barramento()
        self.biblioteca = biblioteca or config.caminho(config.caminhos.biblioteca)
        self.pasta_cache = config.caminho(config.caminhos.cache)

    # ------------------------------------------------------------------
    def _arquivos(self, colecoes: list[str] | None, rel: RelatorioIndexacao) -> list[tuple[str, Path]]:
        saida = []
        if not self.biblioteca.exists():
            rel.avisos.append(f"Pasta da biblioteca não existe: {self.biblioteca}")
            return saida
        for pasta in sorted(p for p in self.biblioteca.iterdir() if p.is_dir()):
            if pasta.name not in self.cfg.colecoes:
                rel.pastas_desconhecidas.append(pasta.name)
                continue
            if colecoes and pasta.name not in colecoes:
                continue
            for arq in sorted(pasta.rglob("*")):
                if arq.suffix.lower() in EXTENSOES_PDF | EXTENSOES_TEXTO and arq.is_file():
                    # Um .yaml é ficha de livro; um .md com o mesmo nome de um PDF não é.
                    saida.append((pasta.name, arq))
        return saida

    def _impressao_digital(self, sha: str, ficha: dict, extrator) -> str:
        corte = self.cfg.ingestao.corte
        base = json.dumps(
            {
                "sha": sha,
                "ficha": ficha,
                "extrator": extrator.impressao_digital(),
                "corte": [corte.max_caracteres, corte.sobreposicao_caracteres],
                "chunker": chunker.__name__ + ":v1",
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(base.encode()).hexdigest()

    def _extrair_com_cache(self, arq: Path, sha: str, extrator) -> DocumentoExtraido:
        chave = hashlib.sha256(f"{sha}|{extrator.impressao_digital()}".encode()).hexdigest()[:32]
        cache = self.pasta_cache / f"{chave}.json"
        if cache.exists():
            self.bus.publicar("ingestao.cache_extracao", arquivo=arq.name)
            return DocumentoExtraido.de_dict(json.loads(cache.read_text(encoding="utf-8")))
        self.bus.publicar("ingestao.extraindo", arquivo=arq.name)
        doc = extrator.extrair(arq, id_figuras=sha[:12])
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(doc.para_dict(), ensure_ascii=False), encoding="utf-8")
        return doc

    # ------------------------------------------------------------------
    def indexar(self, colecoes: list[str] | None = None, forcar: bool = False) -> RelatorioIndexacao:
        rel = RelatorioIndexacao()
        encontrados: set[str] = set()

        for colecao, arq in self._arquivos(colecoes, rel):
            rel_path = str(arq.relative_to(self.biblioteca))
            encontrados.add(rel_path)
            try:
                self._indexar_arquivo(colecao, arq, rel_path, forcar, rel)
            except Exception as e:  # noqa: BLE001 - um PDF ruim não para a noite inteira
                log.exception("Falha ao indexar %s", rel_path)
                rel.erros[rel_path] = repr(e)
                self.bus.publicar("ingestao.erro", arquivo=rel_path, erro=repr(e))

        # Arquivo apagado da biblioteca sai do índice (só nas coleções varridas).
        for caminho in self.banco.caminhos_documentos():
            colecao = caminho.split("/", 1)[0]
            if caminho not in encontrados and (not colecoes or colecao in colecoes):
                self.banco.remover_documento(caminho)
                rel.removidos.append(caminho)

        self._gerar_embeddings(rel)
        return rel

    def _indexar_arquivo(self, colecao: str, arq: Path, rel_path: str, forcar: bool, rel: RelatorioIndexacao) -> None:
        extrator = self.extrator_pdf if arq.suffix.lower() in EXTENSOES_PDF else self.extrator_texto
        sha = sha256_arquivo(arq)
        ficha = ler_ficha(arq)
        digital = self._impressao_digital(sha, ficha, extrator)
        existente = self.banco.documento(rel_path)
        if existente is not None and existente["impressao_digital"] == digital and not forcar:
            rel.inalterados.append(rel_path)
            return

        doc = self._extrair_com_cache(arq, sha, extrator)
        corte = self.cfg.ingestao.corte
        trechos = chunker.dividir(doc.blocos, corte.max_caracteres, corte.sobreposicao_caracteres)
        idiomas = [idioma.detectar(t.texto) for t in trechos]
        idioma_doc = ficha.get("idioma") or (Counter(idiomas).most_common(1)[0][0] if idiomas else None)

        livro = ficha.get("titulo") or doc.titulo_pdf or arq.stem
        dados = DadosDocumento(
            caminho=rel_path,
            colecao=colecao,
            sha256=sha,
            impressao_digital=digital,
            livro=livro,
            citacao=ficha.get("citacao") or livro,
            autor=ficha.get("autor"),
            edicao=str(ficha["edicao"]) if ficha.get("edicao") is not None else None,
            idioma=idioma_doc,
            deslocamento_paginas=ficha.get("deslocamento_paginas"),
            n_paginas=doc.n_paginas,
            paginas_ocr=doc.paginas_ocr,
        )
        self.banco.substituir_documento(dados, trechos, idiomas)
        rel.processados.append(rel_path)
        if "citacao" not in ficha:
            rel.avisos.append(f"{rel_path}: sem ficha .yaml com 'citacao'; usando '{dados.citacao}'.")
        if dados.deslocamento_paginas is None and arq.suffix.lower() in EXTENSOES_PDF:
            rel.avisos.append(f"{rel_path}: sem 'deslocamento_paginas'; citações mostrarão a página do PDF.")
        self.bus.publicar(
            "ingestao.documento",
            arquivo=rel_path,
            trechos=len(trechos),
            oversize=sum(t.oversize for t in trechos),
            paginas_ocr=len(doc.paginas_ocr),
        )

    def _gerar_embeddings(self, rel: RelatorioIndexacao) -> None:
        pendentes = self.banco.trechos_sem_embedding()
        if not pendentes:
            return
        if self.embedder is None:
            rel.embeddings_pendentes = len(pendentes)
            rel.avisos.append("Sem embedder configurado: trechos ficam só na busca por palavra-chave.")
            return
        lote = self.cfg.ingestao.embeddings_lote
        primeiro = True
        for i in range(0, len(pendentes), lote):
            grupo = pendentes[i : i + lote]
            textos = [f"{r['secao']}\n\n{r['texto']}" if r["secao"] else r["texto"] for r in grupo]
            try:
                vetores = self.embedder.embed(textos)
            except OllamaIndisponivel as e:
                rel.embeddings_pendentes = len(pendentes) - i
                rel.avisos.append(f"Ollama indisponível; {rel.embeddings_pendentes} trechos sem embedding ({e}).")
                return
            if primeiro:
                self.banco.preparar_vetores(self.embedder.nome, len(vetores[0]))
                primeiro = False
            self.banco.salvar_embeddings([(r["id"], r["colecao"], v) for r, v in zip(grupo, vetores)])
            rel.embeddings_gerados += len(grupo)
            self.bus.publicar("ingestao.embeddings", feitos=rel.embeddings_gerados, total=len(pendentes))
