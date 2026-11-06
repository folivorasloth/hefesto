"""Geração da resposta estruturada a partir dos trechos recuperados."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from engenheiro.citacoes import citacao_de_trecho
from engenheiro.llm.ollama import LLM, RespostaInvalida
from engenheiro.recuperacao.pipeline import Candidato

from . import esquemas, prompts

# Estimativa grosseira de tokens por caractere. Português técnico com números
# fica perto de 3 a 4 caracteres por token; usamos 3 para errar a favor de
# sobrar espaço (truncar o prompt é pior do que mandar um trecho a menos).
_CARACTERES_POR_TOKEN = 3.0
_RESERVA_SAIDA_TOKENS = 2048


@dataclass
class TrechoContexto:
    id: str                 # "T1", "T2"...
    candidato: Candidato

    @property
    def trecho(self):
        return self.candidato.trecho

    @property
    def citacao(self) -> str:
        return citacao_de_trecho(self.trecho)

    def para_prompt(self) -> str:
        t = self.trecho
        marcas = []
        if "ocr" in t.origens:
            marcas.append("OCR (pode ter erro de leitura)")
        if "visao" in t.origens:
            marcas.append("contém descrição de figura por IA (não verificada)")
        cab = f"[{self.id}] Fonte: {self.citacao} | Seção: {t.secao or '-'} | Idioma: {t.idioma}"
        if marcas:
            cab += " | " + "; ".join(marcas)
        return f"{cab}\n{t.texto}"


@dataclass
class Afirmacao:
    id: str                          # "A1"...
    texto: str
    tipo: str                        # "fonte" | "inferencia" (pode ser rebaixada)
    trechos: list[str]
    critica: bool
    tipo_original: str = ""
    veredito: str | None = None      # suporta | parcial | nao_suporta | nao_verificado
    justificativa: str | None = None
    numeros_suspeitos: list[str] = field(default_factory=list)
    status: str = "mantida"          # mantida | rebaixada | removida
    notas: list[str] = field(default_factory=list)


@dataclass
class RespostaGerada:
    encontrou: bool
    afirmacoes: list[Afirmacao]
    falta: str
    sugestoes: list[str]
    contexto: list[TrechoContexto]
    mensagens: list[dict]            # o prompt exato, para o rastro
    bruto: str                       # a saída exata do modelo, para o rastro
    modelo: str
    metricas: dict
    avisos: list[str] = field(default_factory=list)


def montar_contexto(candidatos: list[Candidato], num_ctx: int, tamanho_fixo: int, maximo: int) -> tuple[list[TrechoContexto], list[str]]:
    """Escolhe os trechos que cabem na janela, do maior score para o menor."""
    avisos = []
    orcamento = int(num_ctx * _CARACTERES_POR_TOKEN) - tamanho_fixo - int(_RESERVA_SAIDA_TOKENS * _CARACTERES_POR_TOKEN)
    escolhidos: list[TrechoContexto] = []
    usado = 0
    for c in candidatos[:maximo]:
        candidato_ctx = TrechoContexto(f"T{len(escolhidos) + 1}", c)
        tam = len(candidato_ctx.para_prompt()) + 2
        if usado + tam > orcamento:
            avisos.append(
                f"Trecho {candidato_ctx.citacao} ficou fora do contexto por falta de espaço "
                f"(num_ctx={num_ctx}). Aumente geracao.num_ctx se tiver RAM."
            )
            continue
        escolhidos.append(candidato_ctx)
        usado += tam
    return escolhidos, avisos


def _mensagens(persona_txt: str, perfil_txt: str, pergunta: str, contexto: list[TrechoContexto]) -> list[dict]:
    sistema = "\n\n".join(p for p in [persona_txt, perfil_txt, prompts.REGRAS_RESPOSTA] if p)
    if contexto:
        corpo = "TRECHOS RECUPERADOS DA BASE:\n\n" + "\n\n".join(t.para_prompt() for t in contexto)
    else:
        corpo = prompts.SEM_FONTES
    return [
        {"role": "system", "content": sistema},
        {"role": "user", "content": f"{corpo}\n\nPERGUNTA DO USUÁRIO:\n{pergunta}"},
    ]


def gerar(
    llm: LLM,
    modelo: str,
    pergunta: str,
    candidatos: list[Candidato],
    persona_txt: str,
    perfil_txt: str = "",
    num_ctx: int = 12288,
    temperatura: float = 0.0,
    pensar: bool | None = None,
    max_trechos: int = 8,
) -> RespostaGerada:
    fixo = len(_mensagens(persona_txt, perfil_txt, pergunta, [])[0]["content"]) + len(pergunta) + 200
    contexto, avisos = montar_contexto(candidatos, num_ctx, fixo, max_trechos)
    mensagens = _mensagens(persona_txt, perfil_txt, pergunta, contexto)
    r = llm.chat(modelo, mensagens, formato=esquemas.RESPOSTA,
                 opcoes={"temperature": temperatura, "num_ctx": num_ctx}, pensar=pensar)

    prompt_tokens = (r.get("metricas") or {}).get("prompt_eval_count")
    if prompt_tokens and prompt_tokens >= num_ctx - 8:
        # Sinal de que o Ollama cortou o começo do prompt (onde estão as regras!).
        avisos.append(f"O prompt pode ter sido truncado ({prompt_tokens} tokens para num_ctx={num_ctx}).")

    try:
        d = json.loads(r["conteudo"])
    except json.JSONDecodeError as e:
        raise RespostaInvalida(f"O modelo não devolveu JSON válido: {e}; início: {r['conteudo'][:200]!r}") from e

    afirmacoes = []
    for i, a in enumerate(d.get("afirmacoes") or [], start=1):
        tipo = a.get("tipo") if a.get("tipo") in ("fonte", "inferencia") else "inferencia"
        afirmacoes.append(
            Afirmacao(
                id=f"A{i}",
                texto=str(a.get("texto", "")).strip(),
                tipo=tipo,
                tipo_original=tipo,
                trechos=[str(t).strip().upper() for t in a.get("trechos") or []],
                critica=bool(a.get("critica")),
            )
        )
    return RespostaGerada(
        encontrou=bool(d.get("encontrou")),
        afirmacoes=[a for a in afirmacoes if a.texto],
        falta=str(d.get("falta") or "").strip(),
        sugestoes=[str(s).strip() for s in d.get("sugestoes") or [] if str(s).strip()],
        contexto=contexto,
        mensagens=mensagens,
        bruto=r["conteudo"],
        modelo=modelo,
        metricas=r.get("metricas") or {},
        avisos=avisos,
    )
