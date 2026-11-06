"""Pipeline de recuperação: pergunta -> trechos mais relevantes, com rastro.

Etapas:
1. variantes da pergunta (original, expandida pelo glossário, termos em inglês);
2. roteamento para as coleções (sempre com veiculo e caderno_de_bordo);
3. para cada variante: BM25 e busca vetorial -> listas ranqueadas;
4. fusão RRF de todas as listas -> candidatos;
5. reranker (cross-encoder) nos melhores candidatos -> finais.

Cada etapa publica um evento com os números reais, e o resultado guarda o
score de cada trecho em cada etapa, para auditoria.

Degradação explícita: sem Ollama, a busca vetorial é pulada; sem reranker,
vale a ordem do RRF. Nos dois casos o resultado traz um aviso, nunca silêncio.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from engenheiro.config import Config
from engenheiro.eventos import Barramento
from engenheiro.llm.ollama import Embedder, OllamaIndisponivel
from engenheiro.store.busca_hibrida import Acerto, buscar_bm25, buscar_vetor, fundir_rrf
from engenheiro.store.db import Banco, IndiceIncompativel, TrechoArmazenado

from .reescrita import Glossario, Roteamento, Variante, gerar_variantes, rotear
from .reranker import Reranker


@dataclass
class Candidato:
    trecho: TrechoArmazenado
    rrf: float
    posicao_rrf: int
    # Posição e score em cada lista: {"bm25:original": {"posicao": 1, "score": 7.3}, ...}
    listas: dict[str, dict] = field(default_factory=dict)
    rerank: float | None = None
    posicao_final: int | None = None


@dataclass
class ResultadoBusca:
    pergunta: str
    variantes: list[Variante]
    roteamento: Roteamento
    candidatos: list[Candidato]      # todos os que entraram no reranking, em ordem de RRF
    finais: list[Candidato]          # os que sobraram, em ordem final
    avisos: list[str] = field(default_factory=list)

    def para_dict(self) -> dict:
        def cand(c: Candidato) -> dict:
            d = asdict(c)
            d["trecho"] = asdict(c.trecho)
            return d

        return {
            "pergunta": self.pergunta,
            "variantes": [asdict(v) for v in self.variantes],
            "roteamento": asdict(self.roteamento),
            "candidatos": [cand(c) for c in self.candidatos],
            "finais": [c.trecho.id for c in self.finais],
            "avisos": self.avisos,
        }


class Recuperador:
    def __init__(
        self,
        config: Config,
        banco: Banco,
        glossario: Glossario,
        embedder: Embedder | None,
        reranker: Reranker | None,
        barramento: Barramento | None = None,
    ) -> None:
        self.cfg = config
        self.banco = banco
        self.glossario = glossario
        self.embedder = embedder
        self.reranker = reranker
        self.bus = barramento or Barramento()

    def buscar(self, pergunta: str, final: int | None = None, colecoes: list[str] | None = None) -> ResultadoBusca:
        cb = self.cfg.busca
        final = final or cb.final
        avisos: list[str] = []

        variantes = gerar_variantes(pergunta, self.glossario)
        self.bus.publicar("busca.variantes", variantes=[asdict(v) for v in variantes])

        if colecoes:
            rota = Roteamento(colecoes, "coleções escolhidas manualmente")
        else:
            rota = rotear(pergunta, self.glossario, self.cfg.colecoes, self.cfg.colecoes_sempre, cb.roteamento)
        self.bus.publicar("busca.roteamento", colecoes=rota.colecoes, motivo=rota.motivo, termos=rota.termos)

        listas: dict[str, list[Acerto]] = {}
        for v in variantes:
            listas[f"bm25:{v.tipo}"] = buscar_bm25(self.banco, v.texto, rota.colecoes, cb.candidatos_por_lista)
        self.bus.publicar("busca.bm25", acertos={k: len(a) for k, a in listas.items()})

        listas.update(self._buscar_vetores(variantes, rota.colecoes, cb.candidatos_por_lista, avisos))

        fundidos = fundir_rrf(listas, cb.rrf_k)[: cb.candidatos_rerank]
        trechos = self.banco.obter_trechos([i for i, _ in fundidos])
        candidatos: list[Candidato] = []
        for pos, (tid, score) in enumerate(fundidos, start=1):
            c = Candidato(trechos[tid], score, pos)
            for nome, acertos in listas.items():
                for a in acertos:
                    if a.trecho_id == tid:
                        c.listas[nome] = {"posicao": a.posicao, "score": round(a.score, 4)}
            candidatos.append(c)
        self.bus.publicar("busca.fusao", candidatos=len(candidatos), listas=list(listas))

        finais = self._reordenar(pergunta, candidatos, final, avisos)
        self.bus.publicar(
            "busca.final",
            trechos=[{"id": c.trecho.id, "livro": c.trecho.citacao, "rerank": c.rerank} for c in finais],
        )
        return ResultadoBusca(pergunta, variantes, rota, candidatos, finais, avisos)

    def _buscar_vetores(self, variantes, colecoes, n, avisos) -> dict[str, list[Acerto]]:
        if self.embedder is None:
            avisos.append("Sem embedder: busca só por palavra-chave.")
            return {}
        if not self.banco.tem_tabela_vetorial:
            avisos.append("Índice ainda sem embeddings: busca só por palavra-chave.")
            return {}
        try:
            # Checagem de compatibilidade: vetor de outro modelo daria similaridades sem sentido.
            if self.banco.embedder != self.embedder.nome:
                raise IndiceIncompativel(f"índice usa '{self.banco.embedder}', consulta usaria '{self.embedder.nome}'")
            vetores = self.embedder.embed([v.texto for v in variantes])
        except (OllamaIndisponivel, IndiceIncompativel) as e:
            avisos.append(f"Busca vetorial desativada nesta consulta: {e}")
            self.bus.publicar("busca.vetor_indisponivel", motivo=str(e))
            return {}
        saida = {f"vetor:{v.tipo}": buscar_vetor(self.banco, vec, colecoes, n) for v, vec in zip(variantes, vetores)}
        self.bus.publicar("busca.vetor", acertos={k: len(a) for k, a in saida.items()})
        sem_embedding = self.banco.con.execute("SELECT COUNT(*) FROM trechos WHERE tem_embedding = 0").fetchone()[0]
        if sem_embedding:
            avisos.append(f"{sem_embedding} trechos ainda sem embedding: só aparecem pela palavra-chave.")
        return saida

    def _reordenar(self, pergunta, candidatos, final, avisos) -> list[Candidato]:
        if not candidatos:
            return []
        if self.reranker is None:
            avisos.append("Reranker desligado: ordem final = ordem da fusão RRF.")
            escolhidos = candidatos[:final]
        else:
            textos = [f"{c.trecho.secao}\n{c.trecho.texto}" for c in candidatos]
            try:
                scores = self.reranker.pontuar(pergunta, textos)
            except Exception as e:  # noqa: BLE001 - reranker com defeito não pode zerar a busca
                avisos.append(f"Reranker falhou ({e!r}); usando a ordem da fusão RRF.")
                self.bus.publicar("busca.rerank_falhou", erro=repr(e))
                escolhidos = candidatos[:final]
            else:
                for c, s in zip(candidatos, scores):
                    c.rerank = round(s, 4)
                self.bus.publicar("busca.rerank", avaliados=len(candidatos))
                escolhidos = sorted(candidatos, key=lambda c: c.rerank, reverse=True)[:final]
        for i, c in enumerate(escolhidos, start=1):
            c.posicao_final = i
        return escolhidos
