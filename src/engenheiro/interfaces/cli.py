"""CLI de texto.

Fase 1:
    engenheiro indexar                    indexa data/biblioteca (incremental)
    engenheiro buscar "pergunta"          mostra trechos, páginas e scores
    engenheiro status                     Ollama, índice, pendências
    engenheiro corpus-teste               gera PDFs fictícios em data/teste/
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console, Group
from rich.markup import escape
from rich.text import Text
from rich.panel import Panel
from rich.table import Table

from engenheiro import fabrica, rastro
from engenheiro.citacoes import citacao_de_trecho
from engenheiro.config import carregar_config
from engenheiro.eventos import Barramento

app = typer.Typer(add_completion=False, help="Engenheiro: assistente de mecânica e elétrica com fontes.")
con = Console()

OpcConfig = typer.Option(None, "--config", "-c", help="Caminho do config.yaml")
OpcIndice = typer.Option(None, "--indice", help="Usa outro arquivo de índice (ex.: para o corpus de teste)")
OpcFalso = typer.Option(
    False, "--embedder-falso", help="Embeddings FALSOS (hash), só para testar sem Ollama. Não use num índice real."
)


@app.command()
def indexar(
    config: Optional[Path] = OpcConfig,
    colecao: Optional[list[str]] = typer.Option(None, "--colecao", help="Indexa só esta coleção (repetível)"),
    biblioteca: Optional[Path] = typer.Option(None, "--biblioteca", help="Pasta da biblioteca (padrão: do config)"),
    indice: Optional[Path] = OpcIndice,
    forcar: bool = typer.Option(False, "--forcar", help="Refaz os trechos mesmo sem mudança (a extração usa o cache)"),
    embedder_falso: bool = OpcFalso,
):
    """Indexa a biblioteca. Só processa o que mudou."""
    logging.basicConfig(level=logging.WARNING)
    cfg = carregar_config(config)
    bus = Barramento()
    bus.assinar(lambda ev: _mostrar_evento_ingestao(ev))
    bco = fabrica.banco(cfg, indice)
    emb = fabrica.embedder(cfg, embedder_falso)
    rel = fabrica.indexador(cfg, bco, emb, bus, biblioteca).indexar(colecao, forcar)

    con.print(
        f"\n[bold]Processados:[/] {len(rel.processados)}  [bold]Inalterados:[/] {len(rel.inalterados)}  "
        f"[bold]Removidos:[/] {len(rel.removidos)}  [bold]Erros:[/] {len(rel.erros)}  "
        f"[bold]Embeddings gerados:[/] {rel.embeddings_gerados}  [bold]Pendentes:[/] {rel.embeddings_pendentes}"
    )
    for p in rel.pastas_desconhecidas:
        con.print(f"[yellow]Pasta ignorada (não é uma coleção do config):[/] {p}")
    for a in rel.avisos:
        con.print(f"[yellow]Aviso:[/] {escape(a)}")
    for arq, erro in rel.erros.items():
        con.print(f"[red]Erro em {escape(arq)}:[/] {escape(erro)}")
    raise typer.Exit(1 if rel.erros else 0)


def _mostrar_evento_ingestao(ev) -> None:
    d = ev.dados
    if ev.tipo == "ingestao.extraindo":
        con.print(f"Extraindo [cyan]{d['arquivo']}[/] (Docling/OCR, pode demorar)…")
    elif ev.tipo == "ingestao.documento":
        extra = f", {d['oversize']} grandes demais mantidos inteiros" if d["oversize"] else ""
        ocr = f", {d['paginas_ocr']} páginas por OCR" if d["paginas_ocr"] else ""
        con.print(f"  → {d['arquivo']}: {d['trechos']} trechos{extra}{ocr}")
    elif ev.tipo == "ingestao.erro":
        con.print(f"[red]  → erro em {d['arquivo']}[/]")


@app.command()
def buscar(
    pergunta: str = typer.Argument(..., help="Pergunta em linguagem natural"),
    config: Optional[Path] = OpcConfig,
    indice: Optional[Path] = OpcIndice,
    final: Optional[int] = typer.Option(None, "-k", help="Quantos trechos mostrar"),
    colecao: Optional[list[str]] = typer.Option(None, "--colecao", help="Força as coleções (repetível)"),
    sem_rerank: bool = typer.Option(False, "--sem-rerank", help="Pula o reranker"),
    completo: bool = typer.Option(False, "--completo", help="Mostra o texto inteiro dos trechos"),
    candidatos: bool = typer.Option(False, "--candidatos", help="Mostra também todos os candidatos antes do rerank"),
    como_json: bool = typer.Option(False, "--json", help="Saída em JSON"),
    salvar_rastro: bool = typer.Option(False, "--rastro", help="Grava o rastro JSON em data/rastros/"),
    embedder_falso: bool = OpcFalso,
):
    """Busca trechos na base (sem LLM): mostra fonte, página, seção e scores."""
    cfg = carregar_config(config)
    bus = Barramento()
    bco = fabrica.banco(cfg, indice)
    rec = fabrica.recuperador(cfg, bco, fabrica.embedder(cfg, embedder_falso), bus, False if sem_rerank else None)
    res = rec.buscar(pergunta, final, colecao)

    if salvar_rastro:
        rid = rastro.novo_id()
        destino = rastro.salvar(cfg.caminho(cfg.caminhos.rastros), rid, {"busca": res.para_dict()}, bus)
        if not como_json:
            con.print(f"[dim]Rastro: {destino}[/]")
    if como_json:
        typer.echo(json.dumps(res.para_dict(), ensure_ascii=False, indent=2, default=str))
        return

    con.print(Text("Variantes: " + " | ".join(f"{v.tipo}: {v.texto}" for v in res.variantes), style="dim"))
    con.print(f"[dim]Coleções: {', '.join(res.roteamento.colecoes)} ({res.roteamento.motivo})[/]")
    for a in res.avisos:
        con.print(f"[yellow]Aviso:[/] {escape(a)}")
    if not res.finais:
        con.print("[bold red]Nada encontrado na base para essa pergunta.[/]")
        raise typer.Exit(2)

    if candidatos:
        t = Table(title="Candidatos (ordem RRF)", show_lines=False)
        for col in ("RRF#", "RRF", "rerank", "fonte", "seção", "listas"):
            t.add_column(col)
        for c in res.candidatos:
            listas = ", ".join(f"{k}#{v['posicao']}" for k, v in c.listas.items())
            t.add_row(str(c.posicao_rrf), f"{c.rrf:.4f}", _fmt(c.rerank), Text(citacao_de_trecho(c.trecho)), Text(c.trecho.secao), listas)
        con.print(t)

    for c in res.finais:
        tr = c.trecho
        marcas = []
        if "ocr" in tr.origens:
            marcas.append("[yellow]OCR: conferir no original[/]")
        if "visao" in tr.origens:
            marcas.append("[yellow]descrição de figura por IA: NÃO verificada[/]")
        if tr.oversize:
            marcas.append("trecho grande mantido inteiro")
        listas = "  ".join(f"{k}#{v['posicao']}" for k, v in c.listas.items())
        # Todo texto vindo do índice passa por escape(): o Rich interpreta
        # [colchetes] como marcação e apagaria a citação "[Livro, p. X]".
        cabecalho = (
            f"[bold]#{c.posicao_final}  {escape(citacao_de_trecho(tr))}[/]  [dim]{tr.colecao} · {escape(tr.arquivo)}[/]\n"
            f"[bold]{escape(tr.secao or '(sem seção)')}[/]\n"
            f"[dim]tipos={','.join(tr.tipos)} idioma={tr.idioma} trecho_id={tr.id}[/]\n"
            f"rerank={_fmt(c.rerank)}  RRF={c.rrf:.4f} (#{c.posicao_rrf})  [dim]{listas}[/]"
            + (f"\n{' · '.join(marcas)}" if marcas else "")
        )
        texto = tr.texto if completo or len(tr.texto) <= 700 else tr.texto[:700] + " […]"
        con.print(Panel(Group(cabecalho, Text(""), Text(texto)), expand=True))


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:.3f}"


@app.command()
def status(config: Optional[Path] = OpcConfig, indice: Optional[Path] = OpcIndice):
    """Mostra se o Ollama responde, quais modelos existem e o estado do índice."""
    cfg = carregar_config(config)
    cli = fabrica.cliente_ollama(cfg)
    ok = cli.disponivel()
    con.print(f"Ollama em {cfg.ollama.url}: {'[green]disponível[/]' if ok else '[red]inacessível[/]'}")
    if ok:
        instalados = cli.modelos_instalados()
        for papel, nome in cfg.ollama.modelos.model_dump().items():
            tem = any(m == nome or m.startswith(nome + ":") or m == nome + ":latest" for m in instalados)
            con.print(f"  {papel:11} {nome:20} {'[green]instalado[/]' if tem else '[red]faltando[/] (ollama pull ' + nome + ')'}")
    caminho = indice or cfg.caminho(cfg.caminhos.indice)
    if not Path(caminho).exists():
        con.print(f"Índice: [yellow]ainda não existe[/] ({caminho})")
        return
    est = fabrica.banco(cfg, indice).estatisticas()
    con.print(
        f"Índice {caminho}: {est['documentos']} documentos, {est['trechos']} trechos, "
        f"{est['sem_embedding']} sem embedding, embedder={est['embedder']}"
    )
    for col, d in sorted(est["por_colecao"].items()):
        con.print(f"  {col:20} {d.get('documentos', 0):4} docs  {d.get('trechos', 0):6} trechos  {d.get('sem_embedding', 0)} pendentes")


@app.command()
def avaliar(
    perguntas: Path = typer.Option(Path("eval/perguntas.yaml"), "--perguntas", help="Arquivo de perguntas"),
    modo: str = typer.Option("recuperacao", help="recuperacao (só busca) ou resposta (assistente completo)"),
    config: Optional[Path] = OpcConfig,
    indice: Optional[Path] = OpcIndice,
    sem_rerank: bool = typer.Option(False, "--sem-rerank"),
    saida: Path = typer.Option(Path("eval/relatorios"), "--saida", help="Pasta dos relatórios"),
    embedder_falso: bool = OpcFalso,
):
    """Roda a avaliação e grava um relatório comparável com a execução anterior."""
    from engenheiro import avaliacao

    if modo not in ("recuperacao", "resposta"):
        con.print("[red]Modos: 'recuperacao' (só busca) ou 'resposta' (assistente completo, precisa do Ollama).[/]")
        raise typer.Exit(2)
    cfg = carregar_config(config)
    lista = avaliacao.carregar_perguntas(perguntas)
    if not lista:
        con.print(f"[yellow]Nenhuma pergunta ativa em {perguntas}.[/]")
        raise typer.Exit(2)
    if modo == "resposta":
        eng = fabrica.engenheiro(cfg, fabrica.banco(cfg, indice), Barramento(), embedder_falso, False if sem_rerank else None)
        if eng.llm is None:
            con.print(f"[red]Ollama inacessível em {cfg.ollama.url}: o modo 'resposta' precisa do LLM.[/]")
            raise typer.Exit(2)
        rec = eng.rec
        res = avaliacao.avaliar_respostas(eng, lista, cfg.caminho(cfg.caminhos.rastros))
    else:
        rec = fabrica.recuperador(cfg, fabrica.banco(cfg, indice), fabrica.embedder(cfg, embedder_falso), Barramento(),
                                  False if sem_rerank else None)
        res = avaliacao.avaliar_recuperacao(rec, lista, cfg.busca.final)
    extra = {"indice": str(indice or cfg.caminho(cfg.caminhos.indice)), "embedder": rec.embedder.nome if rec.embedder else None,
             "reranker": rec.reranker.nome if rec.reranker else None}
    j, m = avaliacao.gravar_relatorio(saida, perguntas, modo, res, avaliacao.resumo_config(cfg, extra))
    for k, v in res["metricas"].items():
        con.print(f"  {k:42} {v}")
    con.print(f"\nRelatório: {m}\nJSON: {j}")


@app.command()
def perguntar(
    pergunta: str = typer.Argument(..., help="Sua pergunta"),
    config: Optional[Path] = OpcConfig,
    indice: Optional[Path] = OpcIndice,
    sem_rerank: bool = typer.Option(False, "--sem-rerank", help="Sem reranker (desliga o filtro de relevância)"),
    mostrar_passos: bool = typer.Option(True, "--passos/--sem-passos", help="Mostra cada etapa enquanto acontece"),
    embedder_falso: bool = OpcFalso,
):
    """Pergunta ao engenheiro: resposta com citações, verificada, e rastro salvo."""
    cfg = carregar_config(config)
    bus = Barramento()
    if mostrar_passos:
        bus.assinar(_mostrar_passo)
    eng = fabrica.engenheiro(cfg, fabrica.banco(cfg, indice), bus, embedder_falso, False if sem_rerank else None)
    if eng.llm is None:
        con.print(f"[yellow]Ollama inacessível em {cfg.ollama.url}: sem geração de resposta.[/]")
    resp = eng.responder(pergunta)
    con.print()
    con.print(Panel(Text(resp.texto), title=f"{escape(eng.persona.nome)}", title_align="left",
                    border_style="red" if resp.problemas_criticos else "cyan"))
    con.print(f"[dim]Rastro: engenheiro rastro {resp.rastro_id}[/]")


_FRASES_PASSO = {
    "modelo.escolhido": lambda d: f"modelo {d['nivel']} ({d['motivo']})",
    "busca.traducao": lambda d: f"tradução para busca: {d['consulta_en']}",
    "busca.roteamento": lambda d: f"coleções: {', '.join(d['colecoes'])}",
    "busca.bm25": lambda d: f"palavra-chave: {sum(d['acertos'].values())} acertos",
    "busca.vetor": lambda d: f"semântica: {sum(d['acertos'].values())} acertos",
    "busca.rerank": lambda d: f"reranker avaliou {d['avaliados']} candidatos",
    "busca.relevantes": lambda d: f"{d['quantidade']} trechos relevantes ({d['descartados']} abaixo do limiar)",
    "geracao.concluida": lambda d: f"resposta gerada com {d['afirmacoes']} afirmações",
    "verificacao.concluida": lambda d: (
        f"verificação: {d['removidas']} removidas, {d['rebaixadas']} rebaixadas, {d['criticos']} problemas críticos"
        if d["executada"] else "verificação NÃO executada"
    ),
}


def _mostrar_passo(ev) -> None:
    f = _FRASES_PASSO.get(ev.tipo)
    if f:
        con.print(f"[dim]… {escape(f(ev.dados))}[/]")


@app.command("rastro")
def ver_rastro(
    id_rastro: str = typer.Argument(..., help="Id mostrado ao fim da resposta"),
    config: Optional[Path] = OpcConfig,
    como_json: bool = typer.Option(False, "--json", help="Mostra o JSON inteiro"),
):
    """Mostra por que ele respondeu o que respondeu."""
    cfg = carregar_config(config)
    r = rastro.carregar(cfg.caminho(cfg.caminhos.rastros), id_rastro)
    if como_json:
        typer.echo(json.dumps(r, ensure_ascii=False, indent=2))
        return
    con.print(Text(f"Pergunta: {r['pergunta']}", style="bold"))
    con.print(Text(f"Modelo: {r['escolha_modelo']}"))
    if "traducao" in r:
        con.print(Text(f"Tradução: {r['traducao']}"))
    b = r.get("busca")
    if b:
        con.print(Text(f"Coleções: {', '.join(b['roteamento']['colecoes'])}  ·  limiar: {b['limiar_relevancia']}"))
        t = Table(title="Candidatos")
        for col in ("trecho", "RRF", "rerank", "por consulta", "fonte", "seção", "usado"):
            t.add_column(col)
        relevantes = set(b["relevantes"])
        for c in b["candidatos"]:
            tr = c["trecho"]
            t.add_row(str(tr["id"]), f"{c['rrf']:.4f}", _fmt(c["rerank"]), Text(json.dumps(c.get("rerank_por_consulta", {}))),
                      Text(f"{tr['citacao']} p.{tr['pagina_inicio']}"), Text(tr["secao"]), "sim" if tr["id"] in relevantes else "")
        con.print(t)
    v = r.get("verificacao")
    if v:
        t = Table(title=f"Verificação ({'executada' if v['executada'] else 'NÃO executada: ' + str(v['motivo_nao_executada'])})")
        for col in ("id", "tipo original → final", "veredito", "status", "cita", "texto", "justificativa / notas"):
            t.add_column(col)
        for a in v["afirmacoes"]:
            t.add_row(a["id"], f"{a['tipo_original']} → {a['tipo']}", str(a["veredito"]), a["status"], ",".join(a["trechos"]),
                      Text(a["texto"]), Text("; ".join(filter(None, [a.get("justificativa") or "", *a["notas"]]))))
        con.print(t)
        for p in v["problemas_criticos"]:
            con.print(Text(f"⚠ {p}", style="bold red"))
    con.print(Panel(Text(r.get("resposta_final", "")), title="Resposta final", title_align="left"))


@app.command("corpus-teste")
def corpus_teste(destino: Path = typer.Option(Path("data/teste"), help="Pasta de saída")):
    """Gera PDFs FICTÍCIOS (marcados como tal) para testar ingestão e busca."""
    from engenheiro.dev.corpus_teste import gerar_corpus

    for p in gerar_corpus(destino):
        con.print(f"gerado: {p}")
    con.print(
        "\nPara testar:\n"
        f"  engenheiro indexar --biblioteca {destino} --indice data/teste.sqlite\n"
        '  engenheiro buscar --indice data/teste.sqlite "torque do cabeçote"'
    )


if __name__ == "__main__":
    app()
