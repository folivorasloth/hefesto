"""Acesso ao índice SQLite (metadados + FTS5 + sqlite-vec).

Escolhi SQLite em vez de Qdrant porque:
- o bge-m3 pelo Ollama só devolve o vetor denso, então o BM25 teria que ser
  feito por fora de qualquer jeito;
- é um arquivo só: dá para copiar, fazer backup e inspecionar com `sqlite3`;
- para algumas dezenas de livros (dezenas de milhares de trechos), a busca
  vetorial exata do sqlite-vec responde em milissegundos.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

import sqlite_vec

from engenheiro.ingest.modelos import Trecho


class IndiceIncompativel(RuntimeError):
    """O índice foi criado com outro modelo de embeddings."""


@dataclass
class TrechoArmazenado:
    id: int
    colecao: str
    texto: str
    secao: str
    pagina_inicio: int
    pagina_fim: int
    idioma: str | None
    tipos: list[str]
    origens: list[str]
    oversize: bool
    figuras: list[str]
    # Do documento:
    arquivo: str
    livro: str
    citacao: str
    deslocamento_paginas: int | None


@dataclass
class DadosDocumento:
    caminho: str
    colecao: str
    sha256: str
    impressao_digital: str
    livro: str
    citacao: str
    autor: str | None = None
    edicao: str | None = None
    idioma: str | None = None
    deslocamento_paginas: int | None = None
    n_paginas: int | None = None
    paginas_ocr: list[int] | None = None


class Banco:
    def __init__(self, caminho: Path | str) -> None:
        self.caminho = Path(caminho)
        if str(caminho) != ":memory:":
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: no modo voz, a resposta é montada numa thread
        # de trabalho (para o mumbling poder falar ao mesmo tempo). O acesso
        # continua serializado: só um turno roda por vez, e a thread principal
        # não toca no banco enquanto ele roda.
        self.con = sqlite3.connect(str(caminho), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.enable_load_extension(True)
        sqlite_vec.load(self.con)
        self.con.enable_load_extension(False)
        esquema = resources.files("engenheiro.store").joinpath("esquema.sql").read_text(encoding="utf-8")
        self.con.executescript(esquema)

    def fechar(self) -> None:
        self.con.close()

    # ---------------------------------------------------------------- meta
    def _meta(self, chave: str) -> str | None:
        r = self.con.execute("SELECT valor FROM meta WHERE chave = ?", (chave,)).fetchone()
        return r["valor"] if r else None

    def _definir_meta(self, chave: str, valor: str) -> None:
        self.con.execute("INSERT OR REPLACE INTO meta(chave, valor) VALUES (?, ?)", (chave, valor))

    @property
    def embedder(self) -> str | None:
        return self._meta("embedder")

    @property
    def tem_tabela_vetorial(self) -> bool:
        return self._meta("dimensao") is not None

    def preparar_vetores(self, nome_embedder: str, dimensao: int) -> None:
        """Cria a tabela vetorial na primeira vez; depois, garante compatibilidade.

        Misturar vetores de modelos diferentes produz similaridades sem sentido
        (e silenciosamente erradas). Por isso a recusa é dura.
        """
        atual = self.embedder
        if atual is None:
            # `colecao` é partition key: a busca filtrada por coleção não
            # precisa varrer os vetores das outras coleções.
            self.con.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS trechos_vec USING vec0("
                f"trecho_id INTEGER PRIMARY KEY, colecao TEXT PARTITION KEY, "
                f"embedding FLOAT[{dimensao}] distance_metric=cosine)"
            )
            self._definir_meta("embedder", nome_embedder)
            self._definir_meta("dimensao", str(dimensao))
            self.con.commit()
        elif atual != nome_embedder or int(self._meta("dimensao") or 0) != dimensao:
            raise IndiceIncompativel(
                f"O índice usa o embedder '{atual}' (dim {self._meta('dimensao')}), "
                f"mas foi pedido '{nome_embedder}' (dim {dimensao}). "
                "Apague o arquivo do índice e reindexe, ou volte ao modelo anterior."
            )

    # ---------------------------------------------------------- documentos
    def documento(self, caminho: str) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM documentos WHERE caminho = ?", (caminho,)).fetchone()

    def caminhos_documentos(self) -> list[str]:
        return [r["caminho"] for r in self.con.execute("SELECT caminho FROM documentos")]

    def remover_documento(self, caminho: str) -> None:
        doc = self.documento(caminho)
        if doc is None:
            return
        ids = [r["id"] for r in self.con.execute("SELECT id FROM trechos WHERE documento_id = ?", (doc["id"],))]
        self._remover_trechos(ids)
        self.con.execute("DELETE FROM documentos WHERE id = ?", (doc["id"],))
        self.con.commit()

    def _remover_trechos(self, ids: list[int]) -> None:
        # FTS e vec0 não participam do ON DELETE CASCADE: limpeza manual.
        for i in ids:
            self.con.execute("DELETE FROM trechos_fts WHERE rowid = ?", (i,))
            if self.tem_tabela_vetorial:
                self.con.execute("DELETE FROM trechos_vec WHERE trecho_id = ?", (i,))
        self.con.executemany("DELETE FROM trechos WHERE id = ?", [(i,) for i in ids])

    def substituir_documento(self, dados: DadosDocumento, trechos: list[Trecho], idiomas: list[str]) -> int:
        """Remove a versão antiga (se houver) e grava a nova, numa transação só."""
        with self.con:
            antigo = self.documento(dados.caminho)
            if antigo is not None:
                ids = [r["id"] for r in self.con.execute("SELECT id FROM trechos WHERE documento_id = ?", (antigo["id"],))]
                self._remover_trechos(ids)
                self.con.execute("DELETE FROM documentos WHERE id = ?", (antigo["id"],))
            cur = self.con.execute(
                "INSERT INTO documentos(caminho, colecao, sha256, impressao_digital, livro, citacao, autor, "
                "edicao, idioma, deslocamento_paginas, n_paginas, paginas_ocr, indexado_em) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    dados.caminho, dados.colecao, dados.sha256, dados.impressao_digital, dados.livro,
                    dados.citacao, dados.autor, dados.edicao, dados.idioma, dados.deslocamento_paginas,
                    dados.n_paginas, json.dumps(dados.paginas_ocr or []),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
            doc_id = cur.lastrowid
            for ordem, (t, idioma) in enumerate(zip(trechos, idiomas)):
                c = self.con.execute(
                    "INSERT INTO trechos(documento_id, ordem, colecao, texto, secao, pagina_inicio, pagina_fim, "
                    "idioma, tipos, origens, oversize, figuras) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        doc_id, ordem, dados.colecao, t.texto, t.secao, t.pagina_inicio, t.pagina_fim, idioma,
                        json.dumps(t.tipos), json.dumps(t.origens), int(t.oversize), json.dumps(t.figuras),
                    ),
                )
                self.con.execute(
                    "INSERT INTO trechos_fts(rowid, texto, secao) VALUES (?, ?, ?)", (c.lastrowid, t.texto, t.secao)
                )
        return doc_id

    # ------------------------------------------------------------ vetores
    def trechos_sem_embedding(self, limite: int = 10_000) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT id, colecao, texto, secao FROM trechos WHERE tem_embedding = 0 ORDER BY id LIMIT ?", (limite,)
        ).fetchall()

    def salvar_embeddings(self, itens: list[tuple[int, str, list[float]]]) -> None:
        with self.con:
            for trecho_id, colecao, vetor in itens:
                self.con.execute(
                    "INSERT OR REPLACE INTO trechos_vec(trecho_id, colecao, embedding) VALUES (?, ?, ?)",
                    (trecho_id, colecao, sqlite_vec.serialize_float32(vetor)),
                )
                self.con.execute("UPDATE trechos SET tem_embedding = 1 WHERE id = ?", (trecho_id,))

    # ------------------------------------------------------------ leitura
    def obter_trechos(self, ids: list[int]) -> dict[int, TrechoArmazenado]:
        if not ids:
            return {}
        marcas = ",".join("?" * len(ids))
        linhas = self.con.execute(
            f"SELECT t.*, d.caminho AS arquivo, d.livro, d.citacao, d.deslocamento_paginas "
            f"FROM trechos t JOIN documentos d ON d.id = t.documento_id WHERE t.id IN ({marcas})",
            ids,
        ).fetchall()
        return {
            r["id"]: TrechoArmazenado(
                id=r["id"], colecao=r["colecao"], texto=r["texto"], secao=r["secao"],
                pagina_inicio=r["pagina_inicio"], pagina_fim=r["pagina_fim"], idioma=r["idioma"],
                tipos=json.loads(r["tipos"]), origens=json.loads(r["origens"]), oversize=bool(r["oversize"]),
                figuras=json.loads(r["figuras"]), arquivo=r["arquivo"], livro=r["livro"], citacao=r["citacao"],
                deslocamento_paginas=r["deslocamento_paginas"],
            )
            for r in linhas
        }

    def estatisticas(self) -> dict:
        q = lambda sql: self.con.execute(sql).fetchone()[0]  # noqa: E731
        por_colecao = {
            r["colecao"]: {"documentos": r["n"]}
            for r in self.con.execute("SELECT colecao, COUNT(*) n FROM documentos GROUP BY colecao")
        }
        for r in self.con.execute(
            "SELECT colecao, COUNT(*) n, SUM(tem_embedding = 0) p FROM trechos GROUP BY colecao"
        ):
            por_colecao.setdefault(r["colecao"], {}).update(trechos=r["n"], sem_embedding=r["p"])
        return {
            "documentos": q("SELECT COUNT(*) FROM documentos"),
            "trechos": q("SELECT COUNT(*) FROM trechos"),
            "sem_embedding": q("SELECT COUNT(*) FROM trechos WHERE tem_embedding = 0"),
            "embedder": self.embedder,
            "por_colecao": por_colecao,
        }
