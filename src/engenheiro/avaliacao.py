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
    antes = {i["id"]: i["acertou"] for i in anterior["itens"]}
    melhoraram = [i["id"] for i in atual["itens"] if i["acertou"] and antes.get(i["id"]) is False]
    pioraram = [i["id"] for i in atual["itens"] if not i["acertou"] and antes.get(i["id"]) is True]
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
