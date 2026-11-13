"""Verificador: segunda passada sobre a resposta gerada.

Ordem das checagens (das mais baratas e confiáveis para a mais cara):

1. Citações (código): só valem ids de trechos que estavam no contexto.
   Afirmação "fonte" sem citação válida é rebaixada para inferência.
2. Criticidade (código + o que o modelo marcou): tensão, corrente, torque,
   combustível, bateria, ignição, segurança.
3. Suporte (LLM, prompt separado): cada afirmação é confrontada com os
   trechos que ela cita.
4. Números (código): número sem origem na fonte citada, na pergunta ou numa
   ferramenta é marcado como suspeito.

Regras de decisão (conservadoras, porque o custo de errar é alto):

| tipo       | veredito       | resultado                                        |
|------------|----------------|--------------------------------------------------|
| fonte      | suporta        | mantida                                          |
| fonte      | parcial        | rebaixada para inferência, com a justificativa   |
| fonte      | nao_suporta    | REMOVIDA (listada à parte, com o motivo)         |
| inferência | suporta/parcial| mantida como inferência                          |
| inferência | nao_suporta    | REMOVIDA                                         |
| qualquer   | não verificado | fonte vira inferência "não verificada"           |
| fonte      | número ausente | rebaixada; número marcado como suspeito          |
| geral      | (sem LLM)      | REMOVIDA se tiver número, valor, especificação   |
|            |                | ou instrução de mexer no carro; senão mantida    |

Qualquer problema numa afirmação crítica (removida, não verificada ou com
número suspeito) vai para `problemas_criticos`, que a resposta final mostra
no TOPO. Nada é escondido.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from engenheiro.geracao import esquemas, prompts
from engenheiro.geracao.gerador import Afirmacao, RespostaGerada
from engenheiro.llm.ollama import LLM
from engenheiro.recuperacao.reescrita import normalizar

from .numeros import numeros_sem_origem

_RE_CRITICO = re.compile(
    r"tensao|corrente|volt|\d\s*(v|a|ma|mv|ω|ohms?|w|kw)\b|amper|ohm|resistencia|potencia|"
    r"torque|n\s*[·.]?\s*m\b|kgf|aperto|pressao|\bbar\b|psi|kpa|"
    r"bateria|combustivel|etanol|alcool|gasolina|ignicao|faisca|centelha|bobina|"
    r"fusivel|curto|seguranca|perigo|risco|incendio|explos|choque"
)


# O que "conhecimento geral" (sem fonte) NUNCA pode trazer: valor, especificação
# ou instrução de mexer em algo. Só orientação de observação.
_RE_GERAL_PROIBIDO = re.compile(
    # Grandezas e especificações. "volt" com fronteira: "meia volta" não é tensão.
    r"tensao|corrente|\bvolts?\b|voltagem|amper|ohm|resistencia|potencia|torque|aperto|pressao|temperatura|"
    r"kgf|psi|\bbar\b|n\s*[·.]?\s*m\b|especifica|"
    # Instrução de mexer no carro (imperativo ou infinitivo). Substantivos
    # parecidos ficam de fora: "parafuso de ajuste" e "corte de combustível"
    # orientam onde olhar; "ajuste o parafuso" e "corte o fio" mandam mexer.
    r"desconect|desmont|remov|solt[ae]|aperte|afrouxe|jumper|curto|faca uma ponte|aplique|injete|borrife|"
    r"\b(?:ligue|ligar|desligue|desligar|conecte|conectar|retire|retirar|tire|tirar|puxe|puxar|emende|emendar|"
    r"troque|trocar|substitua|substituir|regule|gire|girar|instale|instalar|encoste|encostar|raspe|raspar|"
    r"lixe|lixar|fure|furar|solde|soldar|force|forcar|cortar|ajustar|acelere|acelerar|de partida|dar partida)\b|"
    r"\b(?:corte|ajuste|regular)\s+(?:o|a|os|as|um|uma)\b|"
    # Número por extenso também é valor ("regule a folga com meio milímetro",
    # "na escala de doze"): os dígitos já são barrados pela checagem de números.
    r"\b(?:dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|quatorze|catorze|quinze|"
    r"dezesseis|dezessete|dezoito|dezenove|vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|"
    r"cem|cento|duzentos|trezentos|quatrocentos|quinhentos|mil)\b|"
    r"\bmei[oa]\s+(?:milimetro|centimetro|volt|grau|litro|bar|quilo)s?\b"
)


def eh_critica(texto: str) -> bool:
    return bool(_RE_CRITICO.search(normalizar(texto)))


@dataclass
class Verificacao:
    afirmacoes: list[Afirmacao]
    problemas_criticos: list[str] = field(default_factory=list)
    executada: bool = False                 # o passo LLM rodou?
    motivo_nao_executada: str | None = None
    numeros_suspeitos_extras: dict[str, list[str]] = field(default_factory=dict)  # falta/sugestões
    mensagens: list[dict] = field(default_factory=list)
    bruto: str | None = None


def _validar_citacoes(r: RespostaGerada) -> None:
    validos = {t.id for t in r.contexto}
    for a in r.afirmacoes:
        invalidos = [t for t in a.trechos if t not in validos]
        if invalidos:
            a.notas.append(f"citação inexistente descartada: {', '.join(invalidos)}")
        a.trechos = [t for t in dict.fromkeys(a.trechos) if t in validos]
        if a.tipo == "geral" and a.trechos:
            # Citou algo: então não é "conhecimento geral", é raciocínio a partir de fonte.
            a.tipo = "inferencia"
            a.notas.append("conhecimento geral com citação: tratado como inferência")
        elif a.tipo == "geral":
            a.trechos = []
        da_web = [t for t in a.trechos if t.startswith("W")]
        so_web = bool(a.trechos) and len(da_web) == len(a.trechos)
        if a.tipo in ("fonte", "inferencia") and so_web:
            # Web nunca é "fonte" nem base de inferência: vai para a seção não verificada.
            a.tipo = "web"
            a.notas.append("veio só da web: reclassificada como não verificada")
        elif a.tipo in ("fonte", "inferencia") and da_web:
            # Livro + web na mesma citação: a web sai. Senão um valor que só
            # existe no resultado web apareceria com a página do livro ao lado,
            # e o verificador o "confirmaria" lendo o próprio resultado web.
            a.trechos = [t for t in a.trechos if not t.startswith("W")]
            a.notas.append(f"resultado web tirado da citação ({', '.join(da_web)}): web não sustenta fonte")
        elif a.tipo == "web" and not any(t.startswith("W") for t in a.trechos):
            a.tipo = "inferencia"
            a.status = "rebaixada"
            a.notas.append("marcada como web sem citar resultado web: rebaixada para inferência")
        elif a.tipo == "fonte" and not a.trechos:
            a.tipo = "inferencia"
            a.status = "rebaixada"
            a.notas.append("sem citação válida: rebaixada para inferência")


def _mensagens_verificacao(r: RespostaGerada, alvo: list[Afirmacao]) -> list[dict]:
    por_id = {t.id: t for t in r.contexto}
    usados = [por_id[i] for i in dict.fromkeys(t for a in alvo for t in a.trechos)]
    trechos = "\n\n".join(t.para_prompt() for t in usados)
    linhas = []
    for a in alvo:
        tipo = "FONTE" if a.tipo == "fonte" else "INFERÊNCIA"
        linhas.append(f"[{a.id}] ({tipo}; cita {', '.join(a.trechos)}) {a.texto}")
    return [
        {"role": "system", "content": prompts.VERIFICADOR},
        {"role": "user", "content": f"TRECHOS:\n\n{trechos}\n\nAFIRMAÇÕES A VERIFICAR:\n" + "\n".join(linhas)},
    ]


def verificar(
    r: RespostaGerada,
    pergunta: str,
    llm: LLM | None,
    modelo: str,
    opcoes: dict | None = None,
    pensar: bool | None = None,
    textos_extras: list[str] | None = None,
    ativo: bool = True,
) -> Verificacao:
    v = Verificacao(afirmacoes=r.afirmacoes)
    _validar_citacoes(r)
    for a in r.afirmacoes:
        if eh_critica(a.texto):
            a.critica = True

    # --- passo LLM: só para afirmações que citam algo (as outras não têm o que conferir)
    # Web fica fora do verificador LLM: já sai marcada como não verificada.
    alvo = [a for a in r.afirmacoes if a.trechos and a.tipo not in ("web", "geral")]
    vereditos: dict[str, dict] = {}
    if not ativo:
        v.motivo_nao_executada = "verificador desligado no config"
    elif llm is None:
        v.motivo_nao_executada = "LLM indisponível"
    elif alvo:
        v.mensagens = _mensagens_verificacao(r, alvo)
        try:
            resp = llm.chat(modelo, v.mensagens, formato=esquemas.VERIFICACAO, opcoes=opcoes, pensar=pensar)
            v.bruto = resp["conteudo"]
            for item in json.loads(resp["conteudo"]).get("avaliacoes", []):
                vereditos[str(item.get("id", "")).strip().upper()] = item
            v.executada = True
        except Exception as e:  # noqa: BLE001 - falha do verificador nunca vira "aprovado"
            v.motivo_nao_executada = f"falha ao verificar: {e!r}"
    else:
        v.executada = True  # nada a verificar com LLM

    for a in r.afirmacoes:
        if a.tipo == "geral":
            a.veredito = "conhecimento_geral"
            # Aqui o ASSUNTO não importa (orientar a olhar a ignição é justamente o
            # objetivo); o que não pode é o CONTEÚDO: valor, especificação ou
            # instrução de mexer. Por isso não usamos a marca de "crítica".
            proibido = _RE_GERAL_PROIBIDO.search(normalizar(a.texto))
            if proibido:
                a.status = "removida"
                a.justificativa = ("conhecimento geral (sem fonte) não pode trazer valor, especificação nem "
                                   f"instrução de mexer no carro (termo: '{proibido.group(0)}')")
            continue
        if a.tipo == "web":
            a.veredito = "web_nao_verificado"
            if a.critica:
                v.problemas_criticos.append(
                    f"Informação crítica vinda SÓ da web (não verificada): \"{a.texto}\". Confira numa fonte confiável antes de usar."
                )
            continue
        if not a.trechos:
            a.veredito = "sem_base"
            if a.tipo == "inferencia":
                a.notas.append("raciocínio sem base direta nas fontes")
            continue
        item = vereditos.get(a.id)
        if item is None or item.get("veredito") not in ("suporta", "parcial", "nao_suporta"):
            a.veredito = "nao_verificado"
            if a.tipo == "fonte":
                a.tipo = "inferencia"
                a.status = "rebaixada"
            a.notas.append("não verificada" + (f" ({v.motivo_nao_executada})" if v.motivo_nao_executada else ""))
            if a.critica:
                v.problemas_criticos.append(f"Afirmação crítica NÃO verificada: \"{a.texto}\"")
            continue
        a.veredito = item["veredito"]
        a.justificativa = str(item.get("justificativa", "")).strip()
        if a.veredito == "nao_suporta":
            a.status = "removida"
            if a.critica:
                v.problemas_criticos.append(
                    f"O verificador REPROVOU e removeu: \"{a.texto}\". Motivo: {a.justificativa}. Não use essa informação."
                )
        elif a.veredito == "parcial" and a.tipo == "fonte":
            a.tipo = "inferencia"
            a.status = "rebaixada"
            a.notas.append(f"a fonte sustenta só em parte: {a.justificativa}")

    # --- números (código)
    # Origens aceitas para números: o que a afirmação cita (trecho, ferramenta
    # ou web), a pergunta e o perfil do veículo. Ferramentas (F#) fazem parte
    # do contexto, então conta feita por ferramenta passa; conta "de cabeça" não.
    # Ferramenta que deu erro ou recebeu número sem origem não vale como origem
    # (texto_para_numeros vazio): senão bastaria passar um valor inventado por
    # uma ferramenta para ele sair como "[cálculo: ...]".
    por_id = {t.id: getattr(t, "texto_para_numeros", t.texto) for t in r.contexto}
    sem_origem = {t.id: t.sem_origem for t in r.contexto if getattr(t, "sem_origem", None)}
    # Web só é origem para a afirmação marcada como web, que já sai como não verificada.
    todos_trechos = [txt for i, txt in por_id.items() if not i.startswith("W")]
    extras = list(textos_extras or [])
    for a in r.afirmacoes:
        if a.status == "removida":
            continue
        for t in a.trechos:
            if t in sem_origem:
                a.notas.append(f"{t} recebeu número sem origem ({', '.join(sem_origem[t])}): não conta como fonte")
        if a.tipo == "geral":
            origens = []          # sem fonte: só a pergunta e o perfil confirmado
        elif a.tipo_original in ("fonte", "web") and a.trechos:
            origens = [por_id[t] for t in a.trechos]
        else:
            origens = todos_trechos
        a.numeros_suspeitos = numeros_sem_origem(a.texto, origens + [pergunta] + extras)
        if a.numeros_suspeitos and a.tipo == "geral":
            a.status = "removida"
            a.justificativa = "conhecimento geral com número sem fonte: " + ", ".join(a.numeros_suspeitos)
            continue
        if a.numeros_suspeitos:
            a.notas.append("número sem origem verificável: " + ", ".join(a.numeros_suspeitos))
            if a.tipo == "fonte":
                # Se o número não está no trecho citado, a afirmação não pode
                # aparecer como "das fontes": a citação daria a entender que o
                # livro diz aquele número.
                a.tipo = "inferencia"
                a.status = "rebaixada"
                a.notas.append("o número não está no trecho citado")
            if a.critica:
                v.problemas_criticos.append(
                    f"Número sem origem numa afirmação crítica ({', '.join(a.numeros_suspeitos)}): \"{a.texto}\""
                )
    for nome, texto in [("falta", r.falta)] + [(f"sugestao_{i}", s) for i, s in enumerate(r.sugestoes, 1)]:
        susp = numeros_sem_origem(texto, todos_trechos + [pergunta] + extras)
        if susp:
            v.numeros_suspeitos_extras[nome] = susp
    return v
