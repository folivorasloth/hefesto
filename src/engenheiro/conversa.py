"""Conversa contínua com memória: o modo "JARVIS".

O que este módulo acrescenta ao assistente de pergunta e resposta:

1. SESSÃO: os turnos ficam guardados (data/conversas/<id>.json) e a conversa
   continua de onde parou, mesmo depois de fechar o programa.
2. REESCRITA: "e se tiver 3 fios?" vira "o conector do distribuidor do Gol tem
   3 fios; o que isso indica sobre a ignição?" antes da busca. Sem isso, a
   busca não sabe do que "isso" está falando.
3. APRENDIZADO COM CONFIRMAÇÃO: quando você conta algo que viu ou mediu, ele
   PROPÕE anotar no perfil do carro ou no caderno de bordo, e só grava se você
   disser "sim". Proteções contra fato inventado:
     - o trecho da sua fala que sustenta o fato tem que existir literalmente no
       que você disse (senão a proposta é descartada pelo código);
     - se o valor proposto não é o que você disse (é uma interpretação, ex.:
       "3 fios" -> "sensor Hall"), ele entra como SUPOSIÇÃO, nunca como
       confirmado.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from engenheiro.recuperacao.reescrita import normalizar

# ------------------------------------------------------------------ prompts
PROMPT_REESCRITA = """\
Reescreva a ÚLTIMA fala do usuário como uma pergunta completa e autônoma, usando o histórico
só para resolver referências ("isso", "ele", "lá", "e se...", respostas a uma pergunta sua).
Inclua o assunto (peça, sistema do carro) e o que o usuário observou, se for o caso.
Não responda nada. Se a fala já for autônoma, devolva igual. Português do Brasil.
"""

PROMPT_FATOS = """\
Extraia da FALA DO USUÁRIO apenas fatos que ele mesmo OBSERVOU ou MEDIU (no carro ou na
bancada). Não interprete, não deduza, não complete com conhecimento seu.
Para cada fato:
- campo: um dos campos do perfil listados abaixo, se couber; senão "observacoes.<nome_curto>"
- valor: exatamente como o usuário disse
- tipo: "observacao" (algo que ele viu) ou "medicao" (um número que ele mediu)
- trecho_da_fala: cópia LITERAL do pedaço da fala que diz isso
Se não houver fato observado ou medido, devolva a lista vazia.
"""

ESQUEMA_REESCRITA = {"type": "object", "properties": {"pergunta": {"type": "string"}}, "required": ["pergunta"]}
ESQUEMA_FATOS = {
    "type": "object",
    "properties": {"fatos": {"type": "array", "items": {"type": "object", "properties": {
        "campo": {"type": "string"}, "valor": {"type": "string"},
        "tipo": {"type": "string", "enum": ["observacao", "medicao"]}, "trecho_da_fala": {"type": "string"}},
        "required": ["campo", "valor", "tipo", "trecho_da_fala"]}}},
    "required": ["fatos"],
}

_RE_ATIVACAO = re.compile(r"^\s*(?:(?:ei|ola|oi|o|ô)[\s,]+)?{nome}[\s,!:.\-]*", re.IGNORECASE)
# "Sim" grava fato no perfil como CONFIRMADO, então só vale quando é
# inequívoco: uma ou mais palavras de confirmação e, logo depois, o fim da
# fala ou uma pontuação. "isso não está certo", "claro que não" e "pode ser o
# distribuidor?" começam com as mesmas palavras e NÃO são confirmação.
_PALAVRA_SIM = (r"(?:sim|s|pode|confirma|confirmo|confirmado|isso|isso mesmo|ok|beleza|blz|anota|anotar|grava|gravar"
                r"|manda|claro|correto|certo|exato|perfeito)")
_RE_SIM = re.compile(rf"^\s*{_PALAVRA_SIM}(?:[\s,]+{_PALAVRA_SIM})*\s*(?:$|[,.!;:]+\s*)", re.I)
# Depois do "sim", um resto que discorda ou ressalva anula a confirmação.
_RE_RESSALVA = re.compile(r"^(?:mas|porem|so que|na verdade|quer dizer)\b|\b(?:nao|nunca|nem|errado|errada|incorreto|incorreta)\b", re.I)
_RE_NAO = re.compile(r"^\s*(nao|n|negativo|deixa|deixa pra la|cancela|nem|melhor nao)\b[\s,.!]*", re.I)
_RE_SLUG = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")


# ------------------------------------------------------------------ dados
@dataclass
class Turno:
    papel: str                 # "usuario" | "hefesto"
    texto: str
    quando: str
    rastro_id: str | None = None


@dataclass
class Proposta:
    tipo: str                  # "perfil" | "caderno"
    campo: str
    valor: str
    status: str                # "confirmado" | "suposicao"
    fonte: str
    trecho_da_fala: str

    def descricao(self) -> str:
        if self.tipo == "caderno":
            return f"anotar no caderno de bordo: \"{self.trecho_da_fala}\""
        marca = "como CONFIRMADO (você viu)" if self.status == "confirmado" else "como SUPOSIÇÃO (interpretação minha)"
        return f"perfil {self.campo} = {self.valor} {marca}"


@dataclass
class Sessao:
    id: str
    turnos: list[Turno] = field(default_factory=list)
    pendentes: list[Proposta] = field(default_factory=list)
    temas_avisados: list[str] = field(default_factory=list)     # segurança já dita por completo
    observacoes_dadas: list[str] = field(default_factory=list)  # avisos do sistema já mostrados

    @classmethod
    def nova(cls) -> "Sessao":
        return cls(datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4])

    def salvar(self, pasta: Path) -> Path:
        pasta.mkdir(parents=True, exist_ok=True)
        p = pasta / f"{self.id}.json"
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    @classmethod
    def carregar(cls, caminho: Path) -> "Sessao":
        d = json.loads(caminho.read_text(encoding="utf-8"))
        return cls(d["id"], [Turno(**t) for t in d["turnos"]], [Proposta(**p) for p in d.get("pendentes", [])],
                   d.get("temas_avisados", []), d.get("observacoes_dadas", []))

    @classmethod
    def ultima(cls, pasta: Path) -> "Sessao | None":
        arquivos = sorted(pasta.glob("*.json")) if pasta.exists() else []
        return cls.carregar(arquivos[-1]) if arquivos else None

    def historico_txt(self, max_turnos: int = 6, max_chars: int = 600) -> str:
        if not self.turnos:
            return ""
        linhas = []
        for t in self.turnos[-max_turnos:]:
            texto = t.texto
            if t.papel == "hefesto":
                # Só o miolo da resposta: avisos de segurança e do sistema não ajudam a entender o contexto.
                # E o que o verificador removeu não volta para o modelo como se fosse contexto.
                texto = re.split(r"\n\n(?:Segurança|Observações do sistema|Removidas pelo verificador)", texto)[0]
            if len(texto) > max_chars:
                texto = texto[:max_chars] + " […]"
            linhas.append(f"{'Usuário' if t.papel == 'usuario' else 'Você (assistente)'}: {texto}")
        return "CONVERSA ATÉ AQUI (só para contexto; fatos técnicos continuam precisando de fonte):\n" + "\n".join(linhas)


@dataclass
class RespostaTurno:
    texto: str
    rastro_id: str | None = None
    propostas: list[Proposta] = field(default_factory=list)
    aplicadas: list[str] = field(default_factory=list)
    fala: str = ""                    # o que ele diz em voz alta
    espera_resposta: bool = False     # terminou com pergunta: ouvir sem palavra de ativação
    problemas_criticos: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ funções puras (testáveis)
def remover_ativacao(fala: str, nome: str = "Hefesto") -> str:
    """'Hefesto, como...' -> 'como...'. Serve para texto digitado e, na fase de
    voz, para a transcrição que começa com a palavra de ativação."""
    padrao = re.compile(_RE_ATIVACAO.pattern.format(nome=re.escape(normalizar(nome))), re.IGNORECASE)
    m = padrao.match(normalizar(fala))
    return fala[m.end():].strip() if m and m.end() else fala.strip()


def interpretar_confirmacao(fala: str) -> tuple[str | None, str]:
    """('sim'|'nao'|None, resto da fala). 'sim, e agora vejo um fio verde'
    confirma E continua a conversa com 'e agora vejo um fio verde'."""
    n = normalizar(fala)
    for decisao, rx in (("sim", _RE_SIM), ("nao", _RE_NAO)):
        m = rx.match(n)
        if m:
            if decisao == "sim" and _RE_RESSALVA.search(n[m.end():].strip()):
                return None, fala  # "certo, mas...", "sim, só que não é esse": na dúvida, não anota
            return decisao, fala[m.end():].strip()
    return None, fala


def validar_fato(fato: dict, fala: str, campos_perfil: set[str], quando: str, id_sessao: str) -> Proposta | None:
    """Converte um fato extraído pelo modelo numa proposta, ou None se não
    passar nas proteções."""
    trecho = str(fato.get("trecho_da_fala", "")).strip()
    valor = str(fato.get("valor", "")).strip()
    if not trecho or not valor:
        return None
    fala_n = normalizar(fala)
    if normalizar(trecho) not in fala_n:
        return None  # o modelo "citou" algo que você não disse
    tipo_fato = fato.get("tipo")
    if tipo_fato == "medicao":
        return Proposta("caderno", "caderno", valor, "confirmado", f"medição relatada por você em {quando}", trecho)
    campo = str(fato.get("campo", "")).strip().lower()
    if campo not in campos_perfil:
        nome = re.sub(r"[^a-z0-9_]+", "_", normalizar(campo.split(".")[-1] or "nota")).strip("_") or "nota"
        campo = f"observacoes.{nome}"
    if not _RE_SLUG.match(campo):
        return None
    # Todas as palavras/números do valor estão na sua fala? Então é o que você
    # disse (confirmado por observação). Senão, é interpretação: suposição.
    tokens = [t for t in re.findall(r"\w+", normalizar(valor)) if len(t) > 1 or t.isdigit()]
    literal = all(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", fala_n) for t in tokens)
    if literal:
        return Proposta("perfil", campo, valor, "confirmado", f"observado por você em {quando} (conversa {id_sessao})", trecho)
    return Proposta("perfil", campo, valor, "suposicao", f"interpretação a partir da sua fala em {quando}: \"{trecho}\"", trecho)


# ------------------------------------------------------------------ orquestração
class Conversador:
    def __init__(self, engenheiro, perfil, caderno, pasta_sessoes: Path, sessao: Sessao | None = None,
                 max_turnos_historico: int = 6) -> None:
        self.eng = engenheiro
        self.perfil = perfil
        self.caderno = caderno
        self.pasta = pasta_sessoes
        self.sessao = sessao or Sessao.nova()
        self.max_turnos = max_turnos_historico

    @property
    def llm(self):
        return self.eng.llm

    def nova_conversa(self) -> str:
        self.sessao = Sessao.nova()
        return self.sessao.id

    def _rapido(self, sistema: str, usuario: str, esquema: dict) -> dict | None:
        if self.llm is None:
            return None
        try:
            r = self.llm.chat(self.eng.modelos.rapido,
                              [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                              formato=esquema, opcoes={"temperature": 0}, pensar=self.eng.cfg.geracao.pensar)
            return json.loads(r["conteudo"])
        except Exception:  # noqa: BLE001 - reescrita/extração são opcionais; sem elas a conversa segue
            return None

    def _reescrever(self, fala: str, hist: str) -> str:
        if not hist:
            return fala
        d = self._rapido(PROMPT_REESCRITA, f"{hist}\n\nÚLTIMA FALA DO USUÁRIO:\n{fala}", ESQUEMA_REESCRITA)
        p = (d or {}).get("pergunta", "").strip()
        return p or fala

    def _extrair_propostas(self, fala: str) -> list[Proposta]:
        # Perguntas puras não trazem fato observado; poupa uma chamada ao modelo.
        if fala.rstrip().endswith("?") or self.llm is None:
            return []
        campos = {k for k, _ in self.perfil_campos()}
        lista = "\n".join(f"- {k}" for k in sorted(campos))
        d = self._rapido(PROMPT_FATOS + f"\nCAMPOS DO PERFIL:\n{lista}", f"FALA DO USUÁRIO:\n{fala}", ESQUEMA_FATOS)
        quando = datetime.now().strftime("%Y-%m-%d")
        propostas = []
        for f in (d or {}).get("fatos", []):
            p = validar_fato(f, fala, campos, quando, self.sessao.id)
            if p and all((p.campo, p.valor) != (q.campo, q.valor) for q in propostas):
                propostas.append(p)
        return propostas

    def perfil_campos(self):
        from engenheiro.perfil import _campos

        return _campos(self.perfil.dados)

    def _aplicar(self, propostas: list[Proposta]) -> list[str]:
        feitas = []
        for p in propostas:
            if p.tipo == "caderno":
                a = self.caderno.registrar(p.trecho_da_fala, tags=["conversa"])
                feitas.append(f"anotado no caderno {a.citacao}")
            else:
                antes = (self.perfil.campo(p.campo) or {}).get("valor")
                self.perfil.definir(p.campo, p.valor, p.status, p.fonte, observacao=f"dito por você: \"{p.trecho_da_fala}\"")
                feitas.append(f"perfil {p.campo} = {p.valor} ({p.status})" + (f", antes: {antes}" if antes not in (None, "") else ""))
        # O perfil mudou: a próxima resposta já precisa saber.
        self.eng.perfil_txt = self.perfil.para_prompt()
        self.eng.perfil_valores = self.perfil.valores_confirmados()
        return feitas

    def turno(self, fala: str) -> RespostaTurno:
        agora = datetime.now().isoformat(timespec="seconds")
        fala = remover_ativacao(fala, self.eng.persona.nome)
        fala_bruta = fala
        prefixo: list[str] = []
        aplicadas: list[str] = []

        if self.sessao.pendentes:
            decisao, resto = interpretar_confirmacao(fala)
            if decisao == "sim":
                aplicadas = self._aplicar(self.sessao.pendentes)
                prefixo.append("Anotado: " + "; ".join(aplicadas) + ".")
            elif decisao == "nao":
                prefixo.append("Certo, não anotei.")
            else:
                prefixo.append("(Deixei de lado as anotações que eu tinha sugerido.)")
            self.sessao.pendentes = []
            if decisao is not None:
                fala = resto
            if not fala:
                # Era só "sim"/"não": responde sem chamar o modelo.
                texto = " ".join(prefixo)
                self.sessao.turnos.append(Turno("usuario", fala_bruta, agora))
                self.sessao.turnos.append(Turno("hefesto", texto, agora))
                self.sessao.salvar(self.pasta)
                return RespostaTurno(texto, aplicadas=aplicadas, fala=texto)

        # Histórico ANTES da fala atual: no primeiro turno não há o que reescrever
        # (e não se gasta uma chamada ao modelo à toa).
        hist = self.sessao.historico_txt(self.max_turnos)
        pergunta = self._reescrever(fala, hist)
        self.sessao.turnos.append(Turno("usuario", fala, agora))
        resp = self.eng.responder(pergunta, conversa=True, historico_txt=hist,
                                  extra_rastro={"sessao": self.sessao.id, "fala_original": fala, "pergunta_reescrita": pergunta},
                                  temas_ja_avisados=set(self.sessao.temas_avisados),
                                  observacoes_ja_dadas=set(self.sessao.observacoes_dadas),
                                  # Origem de números: o que VOCÊ disse nesta conversa, nunca a reescrita do modelo.
                                  falas_usuario=[t.texto for t in self.sessao.turnos if t.papel == "usuario"])
        self.sessao.temas_avisados = sorted(set(self.sessao.temas_avisados) | set(resp.temas_seguranca))
        self.sessao.observacoes_dadas = list(dict.fromkeys(self.sessao.observacoes_dadas + resp.observacoes))
        propostas = self._extrair_propostas(fala)
        partes = prefixo + [resp.texto]
        if propostas:
            linhas = "\n".join(f"  {i}. {p.descricao()}" for i, p in enumerate(propostas, 1))
            partes.append(f"Quer que eu registre isso? (sim / não)\n{linhas}")
            self.sessao.pendentes = propostas
        texto = "\n\n".join(partes)
        fala = " ".join(prefixo + [resp.fala or resp.texto])
        if propostas:
            fala += " Quer que eu anote " + "; e ".join(
                (f"no caderno: {p.trecho_da_fala}" if p.tipo == "caderno" else
                 f"no perfil que {p.campo.split('.')[-1].replace('_', ' ')} é {p.valor}"
                 + ("" if p.status == "confirmado" else ", como suposição"))
                for p in propostas) + "? Diga sim ou não."
        self.sessao.turnos.append(Turno("hefesto", resp.texto, datetime.now().isoformat(timespec="seconds"), resp.rastro_id))
        self.sessao.salvar(self.pasta)
        return RespostaTurno(texto, resp.rastro_id, propostas, aplicadas, fala,
                             espera_resposta=bool(propostas or resp.pergunta_ao_usuario),
                             problemas_criticos=list(resp.problemas_criticos))
