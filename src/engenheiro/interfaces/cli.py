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
    "ferramenta.chamada": lambda d: f"ferramenta {d['id']} {d['nome']}" + (f": ERRO {d['erro']}" if d["erro"] else ""),
    "web.busca": lambda d: f"web: {d['resultados']} resultados ({d['motivo']})",
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


@app.command()
def inventario(
    arquivo: Path = typer.Option(Path("inventario/componentes.yaml"), "--arquivo", help="Arquivo do inventário"),
    pendencias: bool = typer.Option(False, "--pendencias", help="Mostra só o que falta confirmar/contar"),
    validar: bool = typer.Option(False, "--validar", help="Só valida o arquivo"),
    projeto: Optional[str] = typer.Option(None, "--projeto", help="Filtra por projeto (hefesto, divine_machinery)"),
):
    """Lista os componentes que você tem (inventario/componentes.yaml)."""
    from engenheiro import inventario as inv

    try:
        dados = inv.carregar(arquivo)
    except inv.InventarioInvalido as e:
        con.print(Text(str(e), style="red"))
        raise typer.Exit(1)
    if validar:
        con.print(f"[green]Inventário válido:[/] {len(dados.itens)} itens.")
        return
    itens = [c for c in dados.itens if not projeto or projeto in c.projetos]
    if pendencias:
        for c in itens:
            if not c.tem_pendencia:
                continue
            con.print(Text(f"{c.nome} [{c.id}]", style="bold"))
            if c.quantidade is None:
                con.print("  • contar quantos são")
            for e in c.especificacoes:
                if e.status != "confirmado":
                    con.print(Text(f"  • {e.item} ({e.status}): {e.valor or '?'}  ← {e.fonte or ''}"))
            for p in c.pendencias:
                con.print(Text(f"  • {p}"))
        return
    t = Table(title="Inventário")
    for col in ("id", "componente", "categoria", "qtd", "projetos", "a confirmar"):
        t.add_column(col)
    for c in sorted(itens, key=lambda c: (c.categoria, c.nome)):
        faltam = sum(e.status != "confirmado" for e in c.especificacoes) + len(c.pendencias)
        t.add_row(c.id, Text(c.nome), c.categoria, "?" if c.quantidade is None else str(c.quantidade),
                  ", ".join(c.projetos), str(faltam) if faltam else "")
    con.print(t)
    if dados.faltando_sugerido:
        con.print("\n[bold]Faltando (sugestão, prioridade):[/]")
        for f in dados.faltando_sugerido:
            con.print(Text(f"  • [{f.get('prioridade', '?')}] {f['item']}: {f.get('motivo', '')}"))


# ---------------------------------------------------------------- fase 3
@app.command()
def anotar(
    texto: str = typer.Argument(..., help="O que você fez, mediu ou decidiu"),
    titulo: Optional[str] = typer.Option(None, "--titulo", "-t"),
    tag: Optional[list[str]] = typer.Option(None, "--tag", help="Repetível: --tag bateria --tag medicao"),
    config: Optional[Path] = OpcConfig,
    embedder_falso: bool = OpcFalso,
):
    """Grava no caderno de bordo (com data e hora) e indexa na hora."""
    cfg = carregar_config(config)
    bco = fabrica.banco(cfg)
    cli = fabrica.cliente_ollama(cfg)
    emb = fabrica.embedder(cfg, embedder_falso) if (embedder_falso or cli.disponivel()) else None
    a = fabrica.caderno(cfg, bco, emb).registrar(texto, titulo, tag)
    con.print(f"Anotado em {escape(a.arquivo)}: {escape(a.citacao)} {escape(a.titulo)}")
    if emb is None:
        con.print("[dim]Ollama fora: a anotação já está na busca por palavra-chave; o embedding sai na próxima indexação.[/]")


@app.command("caderno")
def ver_caderno(
    termo: str = typer.Argument("", help="Palavras a procurar (vazio = mais recentes)"),
    limite: int = typer.Option(10, "-n"),
    config: Optional[Path] = OpcConfig,
):
    """Busca no caderno de bordo."""
    cfg = carregar_config(config)
    for a in fabrica.caderno(cfg).buscar(termo, limite):
        con.print(Text(f"{a.citacao} {a.titulo}", style="bold"))
        con.print(Text(a.texto + (f"\n  tags: {', '.join(a.tags)}" if a.tags else "")))
        con.print()


perfil_app = typer.Typer(help="Perfil do veículo (perfil_veiculo.yaml)")
app.add_typer(perfil_app, name="perfil")


@perfil_app.callback(invoke_without_command=True)
def perfil_mostrar(ctx: typer.Context, config: Optional[Path] = OpcConfig):
    """Mostra o perfil como ele entra no prompt."""
    if ctx.invoked_subcommand is None:
        con.print(Text(fabrica.perfil(carregar_config(config)).para_prompt()))


@perfil_app.command("definir")
def perfil_definir(
    campo: str = typer.Argument(..., help="grupo.campo, ex.: carburador.modelo"),
    valor: str = typer.Argument(..., help="Valor (números viram número; listas: '[3.45, 1.94]')"),
    status: str = typer.Option(..., "--status", help="confirmado | suposicao | a_confirmar"),
    fonte: Optional[str] = typer.Option(None, "--fonte", help="De onde veio (obrigatório se confirmado)"),
    observacao: Optional[str] = typer.Option(None, "--obs"),
    config: Optional[Path] = OpcConfig,
):
    """Atualiza um campo do perfil e registra no histórico."""
    import yaml as _yaml

    from engenheiro.perfil import PerfilInvalido

    try:
        v = _yaml.safe_load(valor)   # "4" -> 4, "[1, 2]" -> lista, texto continua texto
    except _yaml.YAMLError:
        v = valor
    try:
        novo = fabrica.perfil(carregar_config(config)).definir(campo, v, status, fonte, observacao)
    except PerfilInvalido as e:
        con.print(Text(str(e), style="red"))
        raise typer.Exit(1)
    con.print(Text(f"{campo} = {novo}"))


@app.command()
def ferramenta(
    nome: Optional[str] = typer.Argument(None, help="Nome da ferramenta (vazio = lista)"),
    args: Optional[list[str]] = typer.Argument(None, help="argumentos chave=valor, ex.: tensao_v=12 corrente_a=2"),
    config: Optional[Path] = OpcConfig,
):
    """Roda uma ferramenta de cálculo direto, sem LLM. Ex.:
    engenheiro ferramenta divisor_tensao vin_v=14.4 r1_ohm=47000 r2_ohm=10000 vout_max_permitido_v=3.3"""
    import yaml as _yaml

    cfg = carregar_config(config)
    reg = fabrica.registro_ferramentas(cfg, Barramento(), fabrica.caderno(cfg), fabrica.perfil(cfg))
    if not nome:
        for f in reg.ferramentas.values():
            props = ", ".join(f.parametros.get("properties", {}))
            con.print(Text(f"{f.nome}({props})", style="bold"))
            con.print(Text(f"  {f.descricao}"))
        return
    argumentos = {}
    for a in args or []:
        chave, _, valor = a.partition("=")
        argumentos[chave] = _yaml.safe_load(valor) if valor else None
    ch = reg.executar(nome, argumentos)
    if ch.erro:
        con.print(Text(f"Erro: {ch.erro}", style="red"))
        raise typer.Exit(1)
    typer.echo(json.dumps(ch.saida, ensure_ascii=False, indent=2, default=str))


# ---------------------------------------------------------------- conversa
@app.command()
def conversar(
    nova: bool = typer.Option(False, "--nova", help="Começa uma conversa nova (padrão: continua a última)"),
    config: Optional[Path] = OpcConfig,
    indice: Optional[Path] = OpcIndice,
    sem_rerank: bool = typer.Option(False, "--sem-rerank"),
    mostrar_passos: bool = typer.Option(True, "--passos/--sem-passos"),
    embedder_falso: bool = OpcFalso,
):
    """Conversa contínua com o Hefesto (memória, modo guiado, aprende com confirmação).

    Comandos dentro da conversa: /sair, /nova, /perfil, /rastro, /ajuda
    """
    cfg = carregar_config(config)
    bus = Barramento()
    if mostrar_passos:
        bus.assinar(_mostrar_passo)
    conv = fabrica.conversador(cfg, fabrica.banco(cfg, indice), bus, nova, embedder_falso, False if sem_rerank else None)
    nome = conv.eng.persona.nome
    if conv.eng.llm is None:
        con.print(f"[yellow]Ollama inacessível em {cfg.ollama.url}: {nome} só consegue apontar trechos, sem conversar.[/]")
    retomada = bool(conv.sessao.turnos)
    con.print(f"[bold]{escape(nome)}[/] [dim]({'continuando' if retomada else 'nova'} conversa {conv.sessao.id}; /ajuda para comandos)[/]")
    ultimo_rastro = None
    while True:
        try:
            fala = con.input("[bold green]Você:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            con.print()
            break
        if not fala:
            continue
        if fala.startswith("/"):
            cmd_ = fala.split()[0].lower()
            if cmd_ in ("/sair", "/q"):
                break
            if cmd_ == "/nova":
                from engenheiro.conversa import Sessao

                conv.sessao = Sessao.nova()
                con.print(f"[dim]Nova conversa {conv.sessao.id}.[/]")
            elif cmd_ == "/perfil":
                con.print(Text(conv.perfil.para_prompt()))
            elif cmd_ == "/rastro":
                con.print(f"[dim]engenheiro rastro {ultimo_rastro}[/]" if ultimo_rastro else "[dim]Sem rastro ainda.[/]")
            else:
                con.print("[dim]/sair, /nova (conversa nova), /perfil (o que ele sabe do carro), /rastro (auditar a última resposta)[/]")
            continue
        resp = conv.turno(fala)
        ultimo_rastro = resp.rastro_id or ultimo_rastro
        con.print(Panel(Text(resp.texto), title=escape(nome), title_align="left", border_style="cyan"))


# ---------------------------------------------------------------- voz
@app.command()
def voz(
    botao: bool = typer.Option(False, "--botao", help="Ativação só pelo Enter (botão de falar)"),
    dirigindo: bool = typer.Option(False, "--dirigindo", help="Começa no modo dirigindo"),
    sem_mumbling: bool = typer.Option(False, "--sem-mumbling"),
    nova: bool = typer.Option(False, "--nova", help="Conversa nova"),
    config: Optional[Path] = OpcConfig,
    indice: Optional[Path] = OpcIndice,
):
    """Conversa por voz: diga "Hefesto, ..." (ou aperte Enter com --botao)."""
    cfg = carregar_config(config)
    if sem_mumbling:
        cfg.voz.mumbling = False
    bus = Barramento()
    conv = fabrica.conversador(cfg, fabrica.banco(cfg, indice), bus, nova)

    def mostrar(quem: str, texto: str) -> None:
        estilos = {"voce": ("Você", "green"), "hefesto": (conv.eng.persona.nome, "cyan"), "alerta": ("ALERTA", "red")}
        nome, cor = estilos[quem]
        con.print(Panel(Text(texto), title=escape(nome), title_align="left", border_style=cor))

    con.print("[dim]Carregando voz e transcrição (a primeira vez baixa os modelos)...[/]")
    loop = fabrica.loop_voz(cfg, conv, "botao" if botao else None, dirigindo, mostrar)
    if conv.eng.llm is None:
        con.print(f"[yellow]Ollama inacessível em {cfg.ollama.url}: ele vai ouvir, mas só consegue apontar trechos.[/]")
    dica = "aperte Enter e fale" if botao else f'diga "{cfg.voz.ativacao.palavra}, ..."'
    con.print(f"[bold]{escape(conv.eng.persona.nome)}[/] ouvindo: {dica}. Ctrl+C para sair. "
              '[dim]Comandos de voz: "modo dirigindo", "parei", "nova conversa".[/]')
    try:
        loop.rodar()
    except KeyboardInterrupt:
        con.print()


voz_app = typer.Typer(help="Testes de áudio para montar a garagem")
app.add_typer(voz_app, name="audio")


@voz_app.command("falar")
def audio_falar(texto: str = typer.Argument("Olá, eu sou o Hefesto. A tensão medida foi de 12,6 V."),
                config: Optional[Path] = OpcConfig):
    """Testa o alto-falante e a voz."""
    from engenheiro.voz.audio import AltoFalanteSD
    from engenheiro.voz.stt_tts import Sintetizador

    cfg = carregar_config(config)
    sint, alto = Sintetizador(cfg.caminho(cfg.voz.piper_voz), cfg.voz.velocidade_fala), AltoFalanteSD()
    for audio, taxa in sint.frases(texto):
        alto.tocar(audio, taxa, cfg.voz.volume)


@voz_app.command("ouvir")
def audio_ouvir(config: Optional[Path] = OpcConfig):
    """Testa o microfone: fale uma frase e veja a transcrição."""
    from engenheiro.voz.ativacao import detectar_palavra
    from engenheiro.voz.audio import MicrofoneSD
    from engenheiro.voz.stt_tts import Transcritor
    from engenheiro.voz.vad import Recortador

    cfg = carregar_config(config)
    v = cfg.voz
    stt = Transcritor(v.whisper_modelo, v.dispositivo, v.whisper_compute_type)
    mic = MicrofoneSD()
    con.print("Fale agora (ex.: \"Hefesto, onde fica a bobina?\")...")
    fala = Recortador(v.agressividade_vad, v.silencio_fim_fala_ms, v.duracao_max_fala_s).proxima_fala(mic.quadros(), timeout_s=15)
    mic.fechar()
    if not fala:
        con.print("[yellow]Não ouvi nada em 15 s. Confira o microfone padrão do sistema e a agressividade_vad.[/]")
        raise typer.Exit(1)
    texto = stt.transcrever(fala)
    ativou, resto = detectar_palavra(texto, v.ativacao.palavra)
    con.print(Text(f"Ouvi: {texto}\nPalavra de ativação: {'sim' if ativou else 'não'}; pergunta: {resto if ativou else '-'}"))


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
