"""Avaliação automatizada.

Fase 1 (modo "recuperacao"): a fonte certa apareceu nos trechos finais?
  - acerto@k: fração das perguntas respondíveis em que algum trecho final casa
    com uma fonte esperada;
  - MRR: média de 1/posição do primeiro trecho certo (premia achar em 1º lugar);
  - para as perguntas "fora da base", registra o maior score do reranker. Na
    fase 2 isso calibra o limiar do "não encontrei": compare esse número com o
    score dos acertos reais.

As métricas de resposta (fatos-chave, citações válidas, "não sei" correto)
entram na fase 4, no mesmo relatório.

O relatório (JSON + Markdown) guarda a configuração usada e é comparado com a
execução anterior do mesmo arquivo de perguntas, mostrando o que melhorou e
o que piorou, pergunta por pergunta.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engenheiro.config import Config
from engenheiro.recuperacao.pipeline import Candidato, Recuperador


@dataclass
class Pergunta:
    id: str
    pergunta: str
    fontes_esperadas: list[dict] = field(default_factory=list)
    fatos_chave: list[str] = field(default_factory=list)
    deve_dizer_nao_sei: bool = False
    critica: bool = False
    ativa: bool = True


def carregar_perguntas(caminho: Path) -> list[Pergunta]:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    campos = Pergunta.__dataclass_fields__
    perguntas = [Pergunta(**{k: v for k, v in p.items() if k in campos}) for p in dados.get("perguntas", [])]
    ids = [p.id for p in perguntas]
    duplicados = {i for i in ids if ids.count(i) > 1}
    if duplicados:
        raise ValueError(f"ids duplicados em {caminho}: {sorted(duplicados)}")
    return [p for p in perguntas if p.ativa]


def casa_fonte(c: Candidato, fonte: dict) -> bool:
    t = c.trecho
    if t.arquivo != fonte["arquivo"]:
        return False
    paginas = fonte.get("paginas_pdf")
    if paginas and not any(t.pagina_inicio <= p <= t.pagina_fim for p in paginas):
        return False
    trecho_secao = fonte.get("secao_contem")
    if trecho_secao and trecho_secao.lower() not in t.secao.lower():
        return False
    return True


def avaliar_recuperacao(rec: Recuperador, perguntas: list[Pergunta], k: int) -> dict:
    itens = []
    for p in perguntas:
        t0 = time.time()
        res = rec.buscar(p.pergunta, final=k)
        dur = time.time() - t0
        posicao = None
        score_acerto = None
        for c in res.finais:
            if any(casa_fonte(c, f) for f in p.fontes_esperadas):
                posicao, score_acerto = c.posicao_final, c.rerank
                break
        # Mesmo se não estiver nos finais, vale saber se chegou a ser candidato
        # (problema do reranker) ou se nem foi recuperado (problema da busca).
        entre_candidatos = any(any(casa_fonte(c, f) for f in p.fontes_esperadas) for c in res.candidatos)
        itens.append(
            {
                "id": p.id,
                "pergunta": p.pergunta,
                "deve_dizer_nao_sei": p.deve_dizer_nao_sei,
                "critica": p.critica,
                "acertou": posicao is not None,
                "posicao": posicao,
                "entre_candidatos": entre_candidatos,
                "score_rerank_acerto": score_acerto,
                "score_rerank_maximo": max((c.rerank for c in res.finais if c.rerank is not None), default=None),
                "finais": [
                    {"arquivo": c.trecho.arquivo, "paginas": [c.trecho.pagina_inicio, c.trecho.pagina_fim],
                     "secao": c.trecho.secao, "rerank": c.rerank}
                    for c in res.finais
                ],
                "avisos": res.avisos,
                "segundos": round(dur, 2),
            }
        )

    respondiveis = [i for i in itens if not i["deve_dizer_nao_sei"]]
    fora = [i for i in itens if i["deve_dizer_nao_sei"]]
    n = len(respondiveis) or 1
    metricas = {
        "perguntas": len(itens),
        "respondiveis": len(respondiveis),
        "fora_da_base": len(fora),
        f"acerto@{k}": round(sum(i["acertou"] for i in respondiveis) / n, 4),
        "mrr": round(sum(1 / i["posicao"] for i in respondiveis if i["posicao"]) / n, 4),
        "acerto_criticas": _fracao([i["acertou"] for i in respondiveis if i["critica"]]),
        "fonte_recuperada_mas_cortada_no_rerank": sum(
            1 for i in respondiveis if not i["acertou"] and i["entre_candidatos"]
        ),
        "score_rerank_min_dos_acertos": _min([i["score_rerank_acerto"] for i in respondiveis]),
        "score_rerank_max_fora_da_base": _max([i["score_rerank_maximo"] for i in fora]),
    }
    return {"metricas": metricas, "itens": itens}


def _normalizar_fato(t: str) -> str:
    from engenheiro.recuperacao.reescrita import normalizar

    # "17,3 N·m" e "17.3 N.m" contam como o mesmo fato.
    t = normalizar(t).replace("·", ".").replace(",", ".")
    return " ".join(t.split())


def fato_presente(fato: str, texto: str) -> bool:
    """O fato esperado aparece na resposta?

    1. texto igual (sem acento, maiúsculas, vírgula/ponto decimal); ou
    2. se o fato tem número: cada número aparece na resposta com a MESMA
       grandeza (usa a checagem de unidades do verificador: "0,15 A" = "150 mA")
       e as palavras de conteúdo (4+ letras) do fato também aparecem.
    """
    from engenheiro.recuperacao.reescrita import normalizar
    from engenheiro.verificador.numeros import extrair_numeros, numeros_sem_origem

    if _normalizar_fato(fato) in _normalizar_fato(texto):
        return True
    if not extrair_numeros(fato):
        return False
    if numeros_sem_origem(fato, [texto]):
        return False
    palavras = [w for w in normalizar(fato).split() if len(w) >= 4 and not any(c.isdigit() for c in w)]
    alvo = normalizar(texto)
    return all(w in alvo for w in palavras)


def _p(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def avaliar_respostas(eng, perguntas: list[Pergunta], pasta_rastros: Path, conversa: bool = False) -> dict:
    """Roda o assistente completo e mede honestidade, fonte e utilidade.

    - nao_sei_correto: nas perguntas fora da base, ele disse que não encontrou?
    - falso_nao_sei: nas respondíveis, ele disse que não encontrou (mas estava lá)?
    - fonte_aprovada: das afirmações exibidas como "fonte", quantas o
      verificador aprovou. Por construção deve ser 1.0; se não for, há defeito.
    - citacao_na_fonte_esperada: das afirmações "fonte" que citam trecho de
      livro, quantas citam um trecho de uma das fontes esperadas (só nas
      perguntas que têm fontes_esperadas). Mede se ele cita o lugar CERTO.
    - fatos_chave: fração dos fatos esperados presentes (com unidade).
    - geral_violacoes: afirmações de "conhecimento geral" removidas por trazer
      valor/instrução sem fonte (o modelo tentou burlar a regra).
    - tempo: média, mediana e máximo por resposta (útil para decidir GPU).
    `conversa=True` avalia pelo modo conversa (modelo rápido em orientação).
    """
    from engenheiro import rastro as mod_rastro

    itens = []
    for p in perguntas:
        t0 = time.time()
        resp = eng.responder(p.pergunta, conversa=conversa)
        dur = time.time() - t0
        r = mod_rastro.carregar(pasta_rastros, resp.rastro_id)
        afs = (r.get("verificacao") or {}).get("afirmacoes", [])
        exibidas_fonte = [a for a in afs if a["tipo"] == "fonte" and a["status"] != "removida"]
        # trecho_id -> arquivo, a partir dos candidatos guardados no rastro
        arquivos = {c["trecho"]["id"]: c["trecho"]["arquivo"] for c in (r.get("busca") or {}).get("candidatos", [])}
        t_para_trecho = {c["id"]: c.get("trecho_id") for c in (r.get("geracao") or {}).get("contexto", [])}
        esperados = {f["arquivo"] for f in p.fontes_esperadas}
        citam_livro = [a for a in exibidas_fonte if any(t.startswith("T") for t in a["trechos"])]
        na_esperada = sum(
            any(arquivos.get(t_para_trecho.get(t)) in esperados for t in a["trechos"] if t.startswith("T"))
            for a in citam_livro
        )
        fatos = [f for f in p.fatos_chave if fato_presente(f, resp.texto)]
        itens.append({
            "id": p.id,
            "pergunta": p.pergunta,
            "deve_dizer_nao_sei": p.deve_dizer_nao_sei,
            "critica": p.critica,
            "modelo": (r.get("escolha_modelo") or {}).get("nivel"),
            "cerebro": (r.get("cerebro") or {}).get("nome"),
            "modelo_forte": (r.get("cerebro") or {}).get("forte"),
            "encontrou": resp.encontrou,
            "sem_llm": bool(r.get("sem_llm")),
            "fontes_exibidas": len(exibidas_fonte),
            "fontes_aprovadas": sum(a["veredito"] == "suporta" for a in exibidas_fonte),
            "citam_livro": len(citam_livro) if esperados else 0,
            "citam_fonte_esperada": na_esperada if esperados else 0,
            "removidas": sum(a["status"] == "removida" for a in afs),
            "rebaixadas": sum(a["status"] == "rebaixada" for a in afs),
            "geral_violacoes": sum(a["tipo"] == "geral" and a["status"] == "removida" for a in afs),
            "inferencias_criticas_sem_base": sum(
                a["tipo"] == "inferencia" and a["critica"] and not a["trechos"] and a["status"] != "removida" for a in afs
            ),
            "ferramentas": [c["nome"] for c in (r.get("ferramentas") or {}).get("chamadas", [])],
            "problemas_criticos": resp.problemas_criticos,
            "fatos_encontrados": fatos,
            "fatos_esperados": p.fatos_chave,
            "rastro": resp.rastro_id,
            "segundos": round(dur, 1),
        })

    resp_ = [i for i in itens if not i["deve_dizer_nao_sei"]]
    fora = [i for i in itens if i["deve_dizer_nao_sei"]]
    total_fontes = sum(i["fontes_exibidas"] for i in itens)
    total_livro = sum(i["citam_livro"] for i in itens)
    total_fatos = sum(len(i["fatos_esperados"]) for i in resp_)
    tempos = [i["segundos"] for i in itens]
    metricas = {
        "perguntas": len(itens),
        "sem_llm": sum(i["sem_llm"] for i in itens),
        "nao_sei_correto": _fracao([not i["encontrou"] for i in fora]),
        "falso_nao_sei": _fracao([not i["encontrou"] for i in resp_]),
        "fonte_aprovada": round(sum(i["fontes_aprovadas"] for i in itens) / total_fontes, 4) if total_fontes else None,
        "citacao_na_fonte_esperada": round(sum(i["citam_fonte_esperada"] for i in itens) / total_livro, 4) if total_livro else None,
        "fatos_chave": round(sum(len(i["fatos_encontrados"]) for i in resp_) / total_fatos, 4) if total_fatos else None,
        "fatos_chave_criticas": _fracao([f in i["fatos_encontrados"] for i in resp_ if i["critica"] for f in i["fatos_esperados"]]),
        "afirmacoes_removidas": sum(i["removidas"] for i in itens),
        "afirmacoes_rebaixadas": sum(i["rebaixadas"] for i in itens),
        "geral_violacoes": sum(i["geral_violacoes"] for i in itens),
        "inferencias_criticas_sem_base": sum(i["inferencias_criticas_sem_base"] for i in itens),
        "respostas_com_problema_critico": sum(bool(i["problemas_criticos"]) for i in itens),
        "segundos_medio": round(sum(tempos) / len(tempos), 1) if tempos else None,
        "segundos_mediana": _p(tempos, 0.5),
        "segundos_max": max(tempos) if tempos else None,
    }
    return {"metricas": metricas, "itens": itens}


# ------------------------------------------------------------------ cenários de conversa
@dataclass
class Cenario:
    id: str
    turnos: list[dict]       # [{"fala": ..., "contem": [...], "nao_contem": [...], "propostas": n, "pergunta_de_volta": bool}]
    ativo: bool = True


def carregar_cenarios(caminho: Path) -> list[Cenario]:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    return [Cenario(c["id"], c.get("turnos", []), c.get("ativo", True)) for c in dados.get("cenarios", []) if c.get("ativo", True)]


def avaliar_cenarios(criar_conversador, cenarios: list[Cenario]) -> dict:
    """Conversa de vários turnos (modo JARVIS). Cada turno pode exigir:
    - contem / nao_contem: trechos de texto (sem acento) na resposta;
    - propostas: quantas anotações ele deve propor;
    - pergunta_de_volta: se ele deve terminar perguntando algo (modo guiado).
    `criar_conversador()` devolve um Conversador NOVO (sessão limpa)."""
    from engenheiro.recuperacao.reescrita import normalizar

    itens = []
    for c in cenarios:
        conv = criar_conversador()
        falhas: list[str] = []
        tempos = []
        for n, t in enumerate(c.turnos, 1):
            t0 = time.time()
            r = conv.turno(t["fala"])
            tempos.append(time.time() - t0)
            alvo = normalizar(r.texto)
            for x in t.get("contem", []):
                if normalizar(x) not in alvo:
                    falhas.append(f"turno {n}: faltou '{x}'")
            for x in t.get("nao_contem", []):
                if normalizar(x) in alvo:
                    falhas.append(f"turno {n}: não deveria ter '{x}'")
            if "propostas" in t and len(r.propostas) != t["propostas"]:
                falhas.append(f"turno {n}: {len(r.propostas)} propostas (esperado {t['propostas']})")
            if t.get("pergunta_de_volta") is True and not r.espera_resposta:
                falhas.append(f"turno {n}: não terminou com pergunta")
        itens.append({"id": c.id, "ok": not falhas, "falhas": falhas, "turnos": len(c.turnos),
                      "segundos_por_turno": round(sum(tempos) / len(tempos), 1) if tempos else None})
    return {"metricas": {"cenarios": len(itens), "cenarios_ok": _fracao([i["ok"] for i in itens])}, "itens": itens}


def _fracao(v: list[bool]) -> float | None:
    return round(sum(v) / len(v), 4) if v else None


def _min(v):
    v = [x for x in v if x is not None]
    return min(v) if v else None


def _max(v):
    v = [x for x in v if x is not None]
    return max(v) if v else None


def resumo_config(cfg: Config, extra: dict) -> dict:
    return {
        "modelos": cfg.ollama.modelos.model_dump(),
        "cerebros": [{"nome": c.nome, "url": c.url, "modelos": c.modelos} for c in cfg.ollama.cerebros],
        "corte": cfg.ingestao.corte.model_dump(),
        "busca": cfg.busca.model_dump(),
        **extra,
    }


def _anterior(pasta: Path, nome_perguntas: str, modo: str) -> dict | None:
    candidatos = sorted(pasta.glob(f"*-{modo}-{nome_perguntas}.json"))
    return json.loads(candidatos[-1].read_text(encoding="utf-8")) if candidatos else None


def comparar(atual: dict, anterior: dict | None) -> dict:
    if not anterior:
        return {}
    delta = {}
    for k, v in atual["metricas"].items():
        a = anterior["metricas"].get(k)
        if isinstance(v, (int, float)) and isinstance(a, (int, float)):
            delta[k] = round(v - a, 4)
    def ok(i: dict) -> bool:
        if "ok" in i:                      # cenário de conversa
            return i["ok"]
        if "acertou" in i:                 # recuperação
            return i["acertou"]
        # resposta: certo = disse "não sei" quando devia, ou respondeu quando devia
        return (not i["encontrou"]) if i["deve_dizer_nao_sei"] else i["encontrou"]

    antes = {i["id"]: ok(i) for i in anterior["itens"]}
    melhoraram = [i["id"] for i in atual["itens"] if ok(i) and antes.get(i["id"]) is False]
    pioraram = [i["id"] for i in atual["itens"] if not ok(i) and antes.get(i["id"]) is True]
    return {"execucao_anterior": anterior["execucao"], "delta": delta, "melhoraram": melhoraram, "pioraram": pioraram}


def gravar_relatorio(pasta: Path, perguntas: Path, modo: str, resultado: dict, config: dict) -> tuple[Path, Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    execucao = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    nome = perguntas.stem
    relatorio = {"execucao": execucao, "modo": modo, "perguntas": str(perguntas), "config": config, **resultado}
    relatorio["comparacao"] = comparar(relatorio, _anterior(pasta, nome, modo))
    base = pasta / f"{execucao}-{modo}-{nome}"
    j = base.with_suffix(".json")
    j.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    m = base.with_suffix(".md")
    m.write_text(_markdown(relatorio), encoding="utf-8")
    return j, m


def _markdown(r: dict) -> str:
    linhas = [f"# Avaliação ({r['modo']}): {r['execucao']}", "", f"Perguntas: `{r['perguntas']}`", "", "## Métricas", ""]
    delta = r.get("comparacao", {}).get("delta", {})
    linhas += ["| métrica | valor | Δ vs anterior |", "|---|---|---|"]
    for k, v in r["metricas"].items():
        d = delta.get(k)
        linhas.append(f"| {k} | {v} | {'' if d is None else f'{d:+}'} |")
    comp = r.get("comparacao") or {}
    if comp:
        linhas += ["", f"Comparado com {comp['execucao_anterior']}.",
                   f"- Melhoraram: {', '.join(comp['melhoraram']) or 'nenhuma'}",
                   f"- **Pioraram: {', '.join(comp['pioraram']) or 'nenhuma'}**"]
    modo_base = r["modo"].split("-")[0]   # "completo-ryzen" -> "completo"
    if modo_base == "cenarios":
        linhas += ["", "## Por cenário", "", "| id | ok | turnos | s/turno | falhas |", "|---|---|---|---|---|"]
        for i in r["itens"]:
            linhas.append(f"| {i['id']} | {'sim' if i['ok'] else '**não**'} | {i['turnos']} | {i['segundos_por_turno']} | "
                          f"{'; '.join(i['falhas']) or '—'} |")
        return "\n".join(linhas) + "\n"
    if modo_base in ("resposta", "conversa", "completo"):
        linhas += ["", "## Por pergunta", "",
                   "| id | esperado | encontrou | modelo | fontes ok | fonte certa | removidas | fatos | críticos | s | rastro |",
                   "|---|---|---|---|---|---|---|---|---|---|---|"]
        for i in r["itens"]:
            esperado = "não sei" if i["deve_dizer_nao_sei"] else "resposta"
            rec = i.get("recuperacao")
            certa = f"{i['citam_fonte_esperada']}/{i['citam_livro']}" if i.get("citam_livro") else "—"
            if rec is not None:
                certa += f" (busca: {'sim' if rec['acertou'] else 'não'})"
            linhas.append(
                f"| {i['id']} | {esperado} | {'sim' if i['encontrou'] else 'não'} | "
                f"{i.get('modelo') or '—'}{(' · ' + i['cerebro'] + ' ' + (i.get('modelo_forte') or '')) if i.get('cerebro') else ''} | "
                f"{i['fontes_aprovadas']}/{i['fontes_exibidas']} | {certa} | {i['removidas']} | "
                f"{len(i['fatos_encontrados'])}/{len(i['fatos_esperados'])} | {len(i['problemas_criticos'])} | "
                f"{i['segundos']} | `{i['rastro']}` |"
            )
        return "\n".join(linhas) + "\n"
    linhas += ["", "## Por pergunta", "", "| id | acertou | posição | rerank | 1º trecho |", "|---|---|---|---|---|"]
    for i in r["itens"]:
        primeiro = i["finais"][0] if i["finais"] else None
        desc = f"{primeiro['arquivo']} p.{primeiro['paginas'][0]} ({primeiro['secao']})" if primeiro else "—"
        if i["deve_dizer_nao_sei"]:
            ok = "fora da base"
        else:
            ok = "sim" if i["acertou"] else ("cortado no rerank" if i["entre_candidatos"] else "**não**")
        linhas.append(f"| {i['id']} | {ok} | {i['posicao'] or '—'} | {i['score_rerank_maximo'] or '—'} | {desc} |")
    return "\n".join(linhas) + "\n"


def avaliar_completo(eng, perguntas: list[Pergunta], pasta_rastros: Path, k: int) -> dict:
    """Recuperação + respostas no mesmo relatório (métricas com prefixo)."""
    rec = avaliar_recuperacao(eng.rec, perguntas, k)
    resp = avaliar_respostas(eng, perguntas, pasta_rastros)
    por_id = {i["id"]: i for i in rec["itens"]}
    for i in resp["itens"]:
        r = por_id.get(i["id"])
        if r and not r["deve_dizer_nao_sei"]:
            i["recuperacao"] = {"acertou": r["acertou"], "posicao": r["posicao"]}
    metricas = {**{f"busca.{k_}": v for k_, v in rec["metricas"].items()},
                **{f"resposta.{k_}": v for k_, v in resp["metricas"].items()}}
    return {"metricas": metricas, "itens": resp["itens"]}


def comparar_relatorios(a: dict, b: dict) -> dict:
    """Compara dois relatórios (ex.: o mesmo conjunto de perguntas com o 8B e
    com o 14B). Devolve as métricas lado a lado e as perguntas que um acertou
    e o outro não."""
    def ok(i: dict) -> bool:
        if "ok" in i:
            return i["ok"]
        if "acertou" in i:
            return i["acertou"]
        return (not i["encontrou"]) if i["deve_dizer_nao_sei"] else i["encontrou"]

    metricas = []
    for k in dict.fromkeys(list(a["metricas"]) + list(b["metricas"])):
        va, vb = a["metricas"].get(k), b["metricas"].get(k)
        delta = round(vb - va, 4) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
        metricas.append({"metrica": k, "a": va, "b": vb, "delta": delta})
    ia = {i["id"]: ok(i) for i in a["itens"]}
    ib = {i["id"]: ok(i) for i in b["itens"]}
    comuns = sorted(set(ia) & set(ib))
    return {
        "metricas": metricas,
        "so_a_acertou": [i for i in comuns if ia[i] and not ib[i]],
        "so_b_acertou": [i for i in comuns if ib[i] and not ia[i]],
        "perguntas_em_comum": len(comuns),
    }
