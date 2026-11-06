"""Divide um documento extraído em trechos para indexação.

Regras (em ordem de prioridade):

1. Um trecho nunca atravessa uma fronteira de seção. Cada trecho pertence a
   exatamente um caminho de títulos, e é isso que dá metadado confiável.
2. Unidades atômicas nunca são cortadas, mesmo que passem do tamanho máximo
   (nesse caso o trecho sai marcado `oversize`):
   - tabela;
   - procedimento numerado (passos 1, 2, 3...), inclusive quando atravessa
     quebra de página;
   - figura (com legenda/descrição).
   Cortar uma tabela de torque ou um procedimento no meio é pior do que ter
   um trecho grande: a metade sem o cabeçalho ou sem o passo 1 induz a erro.
3. Avisos (ATENÇÃO, CUIDADO, WARNING...) grudam na unidade seguinte, porque
   quase sempre se referem ao procedimento logo abaixo. Um aviso solto num
   trecho e o procedimento noutro é exatamente o que não pode acontecer.
4. Parágrafos comuns são agrupados até o tamanho máximo. Só eles geram
   sobreposição entre trechos vizinhos (repetir uma tabela não ajuda em nada).

Por que detectar procedimento pelo texto: na prática o Docling nem sempre
marca a lista como numerada (no teste real, `enumerated=False` e o número
vinha dentro do texto, "1 Aqueça o motor..."), e ele ainda quebra a lista em
dois grupos na virada de página. Então olhamos a sequência 1, 2, 3... no texto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .modelos import Bloco, Trecho

# "1 Faça", "1. Faça", "1) Faça", "Passo 1: faça", "Step 1 - do".
# Exige espaço depois do número para não confundir com "1.1 Torques" (título)
# ou "12V" (valor).
_RE_PASSO = re.compile(
    # A pontuação depois do número também exige espaço: "1.5 V é..." não é passo.
    r"^\s*(?:(?:passo|etapa|step)\s+)?(\d{1,2})\s*(?:[.):\-–]\s+|\s+)(?=\S)",
    re.IGNORECASE,
)

_RE_AVISO = re.compile(
    r"^\s*(aten[çc][ãa]o|cuidado|perigo|aviso|importante|nota|"
    r"warning|caution|danger|note|important)\b",
    re.IGNORECASE,
)

_RE_FIM_FRASE = re.compile(r"(?<=[.!?;])\s+")

# Quantos blocos não numerados toleramos entre o passo N e o passo N+1
# (ex.: uma figura, uma nota ou um parágrafo de continuação do passo).
_MAX_INTERCALADOS = 3


def numero_do_passo(texto: str) -> int | None:
    m = _RE_PASSO.match(texto)
    return int(m.group(1)) if m else None


def eh_aviso(texto: str) -> bool:
    return bool(_RE_AVISO.match(texto))


@dataclass
class _Unidade:
    blocos: list[Bloco]
    tipo: str                 # "paragrafo", "tabela", "figura", "procedimento", "lista"
    atomica: bool
    tem_aviso: bool = False

    @property
    def texto(self) -> str:
        return "\n".join(b.texto for b in self.blocos)

    def __len__(self) -> int:
        return len(self.texto)


@dataclass
class _Secao:
    caminho: list[str]
    blocos: list[Bloco] = field(default_factory=list)


def _dividir_em_secoes(blocos: list[Bloco]) -> list[_Secao]:
    secoes: list[_Secao] = []
    pilha: list[str] = []
    atual = _Secao(caminho=[])
    for b in blocos:
        if b.tipo == "titulo":
            if atual.blocos:
                secoes.append(atual)
            nivel = max(1, b.nivel or 1)
            # Título de nível N substitui o de nível N e descarta os mais profundos.
            pilha = pilha[: nivel - 1] + [b.texto.strip()]
            atual = _Secao(caminho=list(pilha))
        else:
            atual.blocos.append(b)
    if atual.blocos:
        secoes.append(atual)
    return secoes


def _procedimento_a_partir(blocos: list[Bloco], i: int) -> int | None:
    """Se blocos[i] inicia um procedimento (passo 1 seguido do passo 2...),
    devolve o índice (exclusivo) do fim do procedimento. Senão, None."""
    if blocos[i].tipo not in ("paragrafo", "item_lista") or numero_do_passo(blocos[i].texto) != 1:
        return None
    esperado = 2
    fim = i + 1
    j = i + 1
    while j < len(blocos):
        # Procura o próximo passo nos próximos poucos blocos.
        achou = None
        for k in range(j, min(j + _MAX_INTERCALADOS + 1, len(blocos))):
            if blocos[k].tipo in ("paragrafo", "item_lista") and numero_do_passo(blocos[k].texto) == esperado:
                achou = k
                break
            if blocos[k].tipo == "tabela":
                break  # uma tabela no meio encerra a busca: é outro assunto
        if achou is None:
            break
        fim = achou + 1
        esperado += 1
        j = achou + 1
    # Um "1" sozinho não é procedimento (pode ser uma frase que começa com número).
    return fim if esperado > 2 else None


def _unidades_da_secao(blocos: list[Bloco]) -> list[_Unidade]:
    unidades: list[_Unidade] = []
    i = 0
    while i < len(blocos):
        b = blocos[i]
        fim_proc = _procedimento_a_partir(blocos, i)
        if fim_proc is not None:
            unidades.append(_Unidade(blocos[i:fim_proc], "procedimento", atomica=True))
            i = fim_proc
            continue
        if b.tipo in ("tabela", "figura"):
            unidades.append(_Unidade([b], b.tipo, atomica=True))
        elif b.tipo == "item_lista":
            unidades.append(_Unidade([b], "lista", atomica=False))
        else:
            unidades.append(_Unidade([b], "paragrafo", atomica=False))
        i += 1

    # Gruda cada aviso na unidade seguinte (ver regra 3 do docstring).
    resultado: list[_Unidade] = []
    pendentes: list[_Unidade] = []
    for u in unidades:
        if u.tipo == "paragrafo" and eh_aviso(u.texto):
            pendentes.append(u)
            continue
        if pendentes:
            blocos_aviso = [bl for p in pendentes for bl in p.blocos]
            u = _Unidade(blocos_aviso + u.blocos, u.tipo, atomica=True, tem_aviso=True)
            pendentes = []
        resultado.append(u)
    for p in pendentes:  # aviso no fim da seção: fica sozinho, mas inteiro
        resultado.append(_Unidade(p.blocos, "paragrafo", atomica=True, tem_aviso=True))
    return resultado


def _quebrar_paragrafo_longo(u: _Unidade, maximo: int) -> list[_Unidade]:
    """Parágrafo comum maior que o máximo é dividido por frases."""
    if u.atomica or len(u) <= maximo:
        return [u]
    b = u.blocos[0]
    frases = _RE_FIM_FRASE.split(b.texto)
    partes: list[_Unidade] = []
    atual = ""
    for f in frases:
        if atual and len(atual) + 1 + len(f) > maximo:
            partes.append(_Unidade([Bloco(b.tipo, atual, b.pagina, origem=b.origem)], u.tipo, False))
            atual = f
        else:
            atual = f"{atual} {f}".strip()
    if atual:
        partes.append(_Unidade([Bloco(b.tipo, atual, b.pagina, origem=b.origem)], u.tipo, False))
    return partes


def _cauda(texto: str, n: int) -> str:
    """Últimas frases de `texto` que cabem em n caracteres (para sobreposição)."""
    if n <= 0:
        return ""
    frases = _RE_FIM_FRASE.split(texto)
    cauda: list[str] = []
    total = 0
    for f in reversed(frases):
        if total + len(f) > n:
            break
        cauda.insert(0, f)
        total += len(f) + 1
    return " ".join(cauda)


def _montar_trecho(caminho: list[str], unidades: list[_Unidade], prefixo: str, maximo: int) -> Trecho:
    blocos = [b for u in unidades for b in u.blocos]
    partes = ([f"(…) {prefixo}"] if prefixo else []) + [u.texto for u in unidades]
    tipos = sorted({u.tipo for u in unidades} | ({"aviso"} if any(u.tem_aviso for u in unidades) else set()))
    return Trecho(
        texto="\n\n".join(partes),
        caminho_titulos=caminho,
        pagina_inicio=min(b.pagina for b in blocos),
        pagina_fim=max(b.pagina for b in blocos),
        tipos=tipos,
        origens=sorted({b.origem for b in blocos}),
        oversize=any(u.atomica and len(u) > maximo for u in unidades),
        figuras=[b.figura_ref for b in blocos if b.figura_ref],
    )


def dividir(blocos: list[Bloco], max_caracteres: int = 2400, sobreposicao: int = 300) -> list[Trecho]:
    trechos: list[Trecho] = []
    for secao in _dividir_em_secoes(blocos):
        unidades: list[_Unidade] = []
        for u in _unidades_da_secao(secao.blocos):
            unidades.extend(_quebrar_paragrafo_longo(u, max_caracteres))

        grupo: list[_Unidade] = []
        tamanho = 0
        prefixo = ""
        for u in unidades:
            if grupo and tamanho + len(u) > max_caracteres:
                trechos.append(_montar_trecho(secao.caminho, grupo, prefixo, max_caracteres))
                ultimo = grupo[-1]
                # Sobreposição só a partir de texto corrido, nunca de tabela/procedimento.
                prefixo = "" if ultimo.atomica else _cauda(ultimo.texto, sobreposicao)
                grupo, tamanho = [], len(prefixo)
            grupo.append(u)
            tamanho += len(u)
        if grupo:
            trechos.append(_montar_trecho(secao.caminho, grupo, prefixo, max_caracteres))
    return trechos
