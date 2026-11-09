"""Caderno de bordo: o que você fez, mediu e decidiu, com data.

Formato: um arquivo Markdown por dia em data/biblioteca/caderno_de_bordo/,
com uma seção por anotação:

    ## 2026-11-07 14:32 · Medição da bateria
    Medi 12,6 V com o motor desligado há 1 h.
    _tags: bateria, medicao_

Por que Markdown em pasta da biblioteca: a anotação vira automaticamente
parte da coleção `caderno_de_bordo` (sempre consultada) e você pode ler e
corrigir à mão, com qualquer editor, sem depender do engenheiro.

Ao gravar, o arquivo do dia é reindexado na hora. Sem Ollama, entra só na
busca por palavra-chave e ganha embedding na próxima indexação.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

from engenheiro.recuperacao.reescrita import normalizar

COLECAO = "caderno_de_bordo"
_RE_ENTRADA = re.compile(r"^## (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) · (.*)$", re.M)


@dataclass
class Anotacao:
    data: str
    hora: str
    titulo: str
    texto: str
    tags: list[str]
    arquivo: str

    @property
    def citacao(self) -> str:
        return f"[Caderno {self.data} {self.hora}]"


class Caderno:
    def __init__(self, pasta: Path, ao_gravar: Callable[[], object] | None = None) -> None:
        self.pasta = pasta
        self.ao_gravar = ao_gravar  # normalmente: reindexar a coleção do caderno

    def registrar(self, texto: str, titulo: str | None = None, tags: list[str] | None = None,
                  quando: datetime | None = None) -> Anotacao:
        texto = texto.strip()
        if not texto:
            raise ValueError("anotação vazia")
        quando = quando or datetime.now()
        data, hora = quando.strftime("%Y-%m-%d"), quando.strftime("%H:%M")
        titulo = (titulo or texto.splitlines()[0][:60]).strip().replace("\n", " ")
        tags = [t.strip() for t in (tags or []) if t.strip()]
        self.pasta.mkdir(parents=True, exist_ok=True)
        arq = self.pasta / f"{data}.md"
        ficha = arq.with_suffix(".yaml")
        if not ficha.exists():
            ficha.write_text(yaml.safe_dump({"titulo": f"Caderno de bordo {data}", "citacao": f"Caderno {data}",
                                             "idioma": "pt"}, allow_unicode=True), encoding="utf-8")
        bloco = f"## {data} {hora} · {titulo}\n\n{texto}\n"
        if tags:
            bloco += f"\n_tags: {', '.join(tags)}_\n"
        with arq.open("a", encoding="utf-8") as f:
            if arq.stat().st_size:
                f.write("\n")
            f.write(bloco)
        if self.ao_gravar:
            self.ao_gravar()
        return Anotacao(data, hora, titulo, texto, tags, arq.name)

    def todas(self) -> list[Anotacao]:
        saida = []
        for arq in sorted(self.pasta.glob("*.md")):
            conteudo = arq.read_text(encoding="utf-8")
            marcas = list(_RE_ENTRADA.finditer(conteudo))
            for i, m in enumerate(marcas):
                fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(conteudo)
                corpo = conteudo[m.end():fim].strip()
                tags = []
                mt = re.search(r"^_tags: (.*)_$", corpo, re.M)
                if mt:
                    tags = [t.strip() for t in mt.group(1).split(",")]
                    corpo = corpo[: mt.start()].strip()
                saida.append(Anotacao(m.group(1), m.group(2), m.group(3).strip(), corpo, tags, arq.name))
        return saida

    def buscar(self, termo: str = "", limite: int = 10) -> list[Anotacao]:
        """Todas as palavras do termo precisam aparecer (sem acento, sem
        maiúsculas). Mais recentes primeiro."""
        palavras = normalizar(termo).split()
        achadas = [a for a in self.todas()
                   if all(p in normalizar(f"{a.titulo} {a.texto} {' '.join(a.tags)}") for p in palavras)]
        return sorted(achadas, key=lambda a: (a.data, a.hora), reverse=True)[:limite]
