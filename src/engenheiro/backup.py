"""Backup dos seus dados.

Padrão (pequeno, rodar sempre): o que só existe na sua máquina e não dá para
recriar:
  - data/usuario/            perfil do carro (com histórico), inventário,
                             avaliações, arquivos personalizados
  - caderno de bordo         data/biblioteca/caderno_de_bordo/
  - conversas                data/conversas/
  - config.yaml

Completo (`completo=True`, grande): acrescenta os livros, o índice, o cache
de extração (a parte que levou noites para processar), figuras e rastros.

Restaurar: `tar -xzf <arquivo> -C <pasta do projeto>`.
"""

from __future__ import annotations

import tarfile
from datetime import datetime
from pathlib import Path

from engenheiro.config import Config


def _itens(cfg: Config, completo: bool) -> list[Path]:
    biblioteca = cfg.caminho(cfg.caminhos.biblioteca)
    rastros = cfg.caminho(cfg.caminhos.rastros)
    itens = [cfg.pasta_usuario, biblioteca / "caderno_de_bordo", rastros.parent / "conversas", cfg.raiz / "config.yaml"]
    if completo:
        itens += [biblioteca, cfg.caminho(cfg.caminhos.indice), cfg.caminho(cfg.caminhos.cache),
                  cfg.caminho(cfg.caminhos.figuras), rastros]
    vistos, saida = set(), []
    for p in itens:
        p = p.resolve()
        if p.exists() and p not in vistos:
            vistos.add(p)
            saida.append(p)
    return saida


def criar_backup(cfg: Config, destino: Path | None = None, completo: bool = False) -> tuple[Path, int, list[str]]:
    """Devolve (arquivo, número de arquivos guardados, avisos)."""
    destino = destino or cfg.caminho(Path("data/backups"))
    destino.mkdir(parents=True, exist_ok=True)
    nome = f"hefesto-{'completo' if completo else 'dados'}-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    arquivo = destino / nome
    raiz = cfg.raiz.resolve()
    avisos = []
    pasta_backups = destino.resolve()

    def filtro(info: tarfile.TarInfo):
        # Nunca põe backups antigos dentro do novo (cresceria sem fim).
        caminho = (raiz / info.name).resolve()
        return None if pasta_backups in caminho.parents or caminho == pasta_backups else info

    with tarfile.open(arquivo, "w:gz") as tar:
        for p in _itens(cfg, completo):
            nome_arq = p.relative_to(raiz) if raiz in p.parents else p.name
            tar.add(p, arcname=str(nome_arq), filter=filtro)

    # Confere o arquivo gerado (um backup que não abre não é backup).
    with tarfile.open(arquivo, "r:gz") as tar:
        n = sum(1 for m in tar.getmembers() if m.isfile())

    cfg_yaml = cfg.raiz / "config.yaml"
    def _tem_token(linha: str) -> bool:
        linha = linha.split("#", 1)[0].strip()   # ignora comentário no fim da linha
        return linha.startswith("token:") and linha.split(":", 1)[1].strip() not in ('""', "''", "")

    if cfg_yaml.exists() and any(_tem_token(x) for x in cfg_yaml.read_text(encoding="utf-8").splitlines()):
        avisos.append("O config.yaml tem um token escrito nele e foi para o backup: guarde o arquivo em lugar seguro "
                      "(ou mova o token para a variável HEFESTO_API_TOKEN).")
    return arquivo, n, avisos
