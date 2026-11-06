"""Orquestrador: pergunta -> resposta verificada + rastro.

    escolha do modelo (regras)
      └─ conversa ............ modelo rápido, sem busca, proibido dar dado técnico
      └─ técnica
           tradução EN (rápido) ─► busca híbrida ─► reranker (PT e EN, fica o maior)
           ─► limiar de relevância ─► geração estruturada (forte)
           ─► verificador (código + forte) ─► avisos de segurança (código)
           ─► montagem do texto (código converte T1 em [Livro, p. X])

Sem LLM (notebook desligado) ele NÃO responde de memória nem improvisa: diz
que está sem o modelo e mostra onde, na base, estão os trechos relevantes.
"""

from __future__ import annotations

import json

import httpx
from dataclasses import asdict, dataclass, field

from engenheiro import rastro
from engenheiro.config import Config
from engenheiro.eventos import Barramento
from engenheiro.geracao import esquemas, gerador, prompts
from engenheiro.geracao.montagem import montar_texto
from engenheiro.llm import selecao
from engenheiro.llm.ollama import LLM, OllamaIndisponivel, RespostaInvalida
from engenheiro.persona import Persona
from engenheiro.recuperacao.pipeline import Recuperador
from engenheiro.recuperacao.reescrita import Variante
from engenheiro.seguranca import Seguranca
from engenheiro.verificador.verificador import verificar


@dataclass
class RespostaFinal:
    texto: str
    rastro_id: str
    modo: str
    encontrou: bool
    problemas_criticos: list[str] = field(default_factory=list)


class Engenheiro:
    def __init__(
        self,
        cfg: Config,
        recuperador: Recuperador,
        llm: LLM | None,
        persona: Persona,
        seguranca: Seguranca,
        barramento: Barramento | None = None,
        perfil_txt: str = "",
    ) -> None:
        self.cfg = cfg
        self.rec = recuperador
        self.llm = llm
        self.persona = persona
        self.seg = seguranca
        self.bus = barramento or recuperador.bus
        self.perfil_txt = perfil_txt

    @property
    def _modelos(self):
        return self.cfg.ollama.modelos

    def _opcoes(self) -> dict:
        g = self.cfg.geracao
        return {"temperature": g.temperatura, "num_ctx": g.num_ctx}

    # ------------------------------------------------------------------
    def responder(self, pergunta: str) -> RespostaFinal:
        rid = rastro.novo_id()
        self.bus.eventos.clear()
        r: dict = {"pergunta": pergunta, "nome": self.persona.nome}
        self.bus.publicar("pergunta.recebida", pergunta=pergunta)

        escolha = selecao.escolher(pergunta)
        r["escolha_modelo"] = asdict(escolha)
        self.bus.publicar("modelo.escolhido", **asdict(escolha))

        if escolha.modo == "conversa":
            return self._conversa(pergunta, rid, r)
        return self._tecnica(pergunta, rid, r)

    # ------------------------------------------------------------------
    def _conversa(self, pergunta: str, rid: str, r: dict) -> RespostaFinal:
        texto = "Estou sem o modelo de linguagem agora, mas sigo aqui. Pode mandar sua pergunta técnica."
        if self.llm is not None:
            try:
                msgs = [
                    {"role": "system", "content": self.persona.para_prompt() + "\n\n" + prompts.CONVERSA},
                    {"role": "user", "content": pergunta},
                ]
                resp = self.llm.chat(self._modelos.rapido, msgs, opcoes={"temperature": 0.3}, pensar=self.cfg.geracao.pensar)
                texto = resp["conteudo"].strip()
                r["conversa"] = {"modelo": self._modelos.rapido, "mensagens": msgs, "bruto": resp["conteudo"]}
            except Exception as e:  # noqa: BLE001
                r["conversa"] = {"erro": repr(e)}
        r["resposta_final"] = texto
        self._salvar(rid, r)
        return RespostaFinal(texto, rid, "conversa", encontrou=True)

    def _traduzir(self, pergunta: str, r: dict, avisos: list[str]) -> str | None:
        if self.llm is None or not self.cfg.busca.rerank_com_traducao:
            return None
        msgs = [{"role": "system", "content": prompts.TRADUCAO}, {"role": "user", "content": pergunta}]
        try:
            resp = self.llm.chat(self._modelos.rapido, msgs, formato=esquemas.TRADUCAO, opcoes={"temperature": 0},
                                 pensar=self.cfg.geracao.pensar)
            en = json.loads(resp["conteudo"]).get("consulta_en", "").strip()
        except Exception as e:  # noqa: BLE001 - sem tradução a busca continua, com aviso
            avisos.append(f"Tradução da pergunta falhou ({e!r}); busca só com as variantes do glossário.")
            r["traducao"] = {"erro": repr(e)}
            return None
        r["traducao"] = {"modelo": self._modelos.rapido, "consulta_en": en}
        self.bus.publicar("busca.traducao", consulta_en=en)
        return en or None

    def _tecnica(self, pergunta: str, rid: str, r: dict) -> RespostaFinal:
        avisos: list[str] = []
        en = self._traduzir(pergunta, r, avisos)
        extras = [Variante("llm_ingles", en)] if en else []
        consultas = {"original": pergunta, **({"llm_ingles": en} if en else {})}

        res = self.rec.buscar(pergunta, variantes_extra=extras, consultas_rerank=consultas)
        avisos += res.avisos
        limiar = self.cfg.busca.limiar_relevancia
        if self.rec.reranker is not None and all(c.rerank is not None for c in res.finais):
            relevantes = [c for c in res.finais if c.rerank >= limiar]
            descartados = [c for c in res.finais if c.rerank < limiar]
        else:
            relevantes, descartados = list(res.finais), []
            avisos.append("Sem score do reranker: não foi possível filtrar trechos irrelevantes pelo limiar.")
        r["busca"] = {
            **res.para_dict(),
            "limiar_relevancia": limiar,
            "relevantes": [c.trecho.id for c in relevantes],
            "descartados_pelo_limiar": [{"id": c.trecho.id, "rerank": c.rerank} for c in descartados],
        }
        self.bus.publicar("busca.relevantes", quantidade=len(relevantes), descartados=len(descartados))

        # Avisos de segurança olham a pergunta E os trechos relevantes: "regular
        # a marcha lenta" não cita combustível, mas o procedimento recuperado sim.
        textos_trechos = " ".join(c.trecho.texto for c in relevantes)
        seg = self.seg.avisos_para(pergunta, textos_trechos)

        if self.llm is None:
            return self._sem_llm(pergunta, rid, r, relevantes, seg, avisos)

        try:
            ger = gerador.gerar(
                self.llm, self._modelos.forte, pergunta, relevantes, self.persona.para_prompt(), self.perfil_txt,
                num_ctx=self.cfg.geracao.num_ctx, temperatura=self.cfg.geracao.temperatura,
                pensar=self.cfg.geracao.pensar, max_trechos=self.cfg.geracao.max_trechos_contexto,
            )
        except (OllamaIndisponivel, RespostaInvalida, httpx.HTTPStatusError) as e:
            # HTTPStatusError: ex. modelo não instalado (ollama pull <modelo>).
            avisos.append(f"Falha na geração com {self._modelos.forte}: {e}")
            return self._sem_llm(pergunta, rid, r, relevantes, seg, avisos)
        avisos += ger.avisos
        self.bus.publicar("geracao.concluida", afirmacoes=len(ger.afirmacoes), encontrou=ger.encontrou)

        self.bus.publicar("verificacao.iniciada", afirmacoes=len(ger.afirmacoes))
        ver = verificar(ger, pergunta, self.llm, self._modelos.forte, self._opcoes(), self.cfg.geracao.pensar,
                        ativo=self.cfg.verificador.ativo)
        self.bus.publicar(
            "verificacao.concluida",
            executada=ver.executada,
            removidas=sum(a.status == "removida" for a in ger.afirmacoes),
            rebaixadas=sum(a.status == "rebaixada" for a in ger.afirmacoes),
            criticos=len(ver.problemas_criticos),
        )

        vivas = " ".join(a.texto for a in ger.afirmacoes if a.status != "removida")
        usados = " ".join(t.trecho.texto for t in ger.contexto)
        seg = self.seg.avisos_para(pergunta, vivas, " ".join(ger.sugestoes), usados)
        texto = montar_texto(ger, ver, seg, avisos)
        encontrou = ger.encontrou and any(a.tipo == "fonte" and a.status != "removida" for a in ger.afirmacoes)

        r["geracao"] = {
            "modelo": ger.modelo,
            "mensagens": ger.mensagens,
            "bruto": ger.bruto,
            "metricas": ger.metricas,
            "contexto": [{"id": t.id, "trecho_id": t.trecho.id, "citacao": t.citacao, "rerank": t.candidato.rerank}
                         for t in ger.contexto],
        }
        r["verificacao"] = {
            "executada": ver.executada,
            "motivo_nao_executada": ver.motivo_nao_executada,
            "mensagens": ver.mensagens,
            "bruto": ver.bruto,
            "afirmacoes": [asdict(a) for a in ger.afirmacoes],
            "problemas_criticos": ver.problemas_criticos,
            "numeros_suspeitos_extras": ver.numeros_suspeitos_extras,
        }
        r["seguranca"] = [t.tema for t in seg]
        r["avisos"] = avisos
        r["resposta_final"] = texto
        self._salvar(rid, r)
        return RespostaFinal(texto, rid, "tecnico", encontrou, ver.problemas_criticos)

    def _sem_llm(self, pergunta, rid, r, relevantes, seg, avisos) -> RespostaFinal:
        if relevantes:
            lista = "\n".join(
                f"• {gerador.TrechoContexto('', c).citacao}: {c.trecho.secao or '(sem seção)'}" for c in relevantes
            )
            miolo = (
                "Estou sem o modelo de linguagem agora (notebook do LLM desligado ou fora da rede), então não vou "
                "montar uma resposta. Não respondo de memória. Os trechos mais relevantes que achei na base são:\n" + lista
            )
            encontrou = True
        else:
            miolo = "Não encontrei isso nas fontes. (O modelo de linguagem também está indisponível agora.)"
            encontrou = False
        texto = montar_texto(None, None, seg, avisos, nao_encontrei_padrao=miolo)
        r["sem_llm"] = True
        r["seguranca"] = [t.tema for t in seg]
        r["avisos"] = avisos
        r["resposta_final"] = texto
        self._salvar(rid, r)
        return RespostaFinal(texto, rid, "tecnico", encontrou)

    def _salvar(self, rid: str, r: dict) -> None:
        destino = rastro.salvar(self.cfg.caminho(self.cfg.caminhos.rastros), rid, r, self.bus)
        self.bus.publicar("rastro.salvo", caminho=str(destino))
