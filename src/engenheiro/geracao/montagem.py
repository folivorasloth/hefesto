"""Monta o texto final a partir da resposta verificada.

É aqui que "T3" vira "[Denton, p. 45]": a citação sai dos metadados do
trecho, nunca do texto do modelo. Por isso não existe citação inventada.

Layout (texto simples, legível no terminal e no MQTT; a voz lê só o miolo):

    ⚠ VERIFICAÇÃO               (só se houver problema crítico: vem PRIMEIRO)
    Das fontes:                 afirmações confirmadas, com citação
    Inferência (minha):         raciocínios, marcados como tais
    Web (não verificado):       resultados do SearXNG, com link
    Não encontrei nas fontes:   o que falta + sugestões
    Segurança:                  avisos determinísticos
    Removidas pelo verificador: o que foi cortado e por quê
"""

from __future__ import annotations

from engenheiro.geracao.gerador import Afirmacao, RespostaGerada
from engenheiro.seguranca import AvisoTema
from engenheiro.verificador.verificador import Verificacao


_NOME_TEMA = {"ignicao": "ignição", "combustivel": "combustível", "bateria": "bateria", "partida_a_frio": "partida a frio",
              "eletronica_12v": "eletrônica nos 12 V", "arrefecimento": "arrefecimento", "elevacao": "carro levantado"}


def _citacoes(a: Afirmacao, r: RespostaGerada) -> str:
    por_id = {t.id: t for t in r.contexto}
    cits = list(dict.fromkeys(por_id[t].citacao for t in a.trechos if t in por_id))
    return " ".join(cits)


def _avisos_origem(a: Afirmacao, r: RespostaGerada) -> list[str]:
    por_id = {t.id: t for t in r.contexto}
    origens = {o for t in a.trechos if t in por_id for o in por_id[t].origens}
    saida = []
    if "ocr" in origens:
        saida.append("trecho lido por OCR: confira no original")
    if "visao" in origens:
        saida.append("baseado em descrição de figura por IA, não verificada")
    return saida


def _links(a: Afirmacao, r: RespostaGerada) -> list[str]:
    por_id = {t.id: t for t in r.contexto}
    return list(dict.fromkeys(por_id[t].url for t in a.trechos if t in por_id and hasattr(por_id[t], "url")))


def _linha(a: Afirmacao, r: RespostaGerada) -> str:
    cit = _citacoes(a, r)
    partes = [a.texto]
    if cit:
        partes.append(cit if a.tipo in ("fonte", "web") else f"(a partir de {cit})")
    if a.tipo == "web":
        partes += _links(a, r)
    notas = list(a.notas) + _avisos_origem(a, r)
    if a.numeros_suspeitos:
        notas = [n for n in notas if not n.startswith("número sem origem")]
        partes.append(f"⚠ número(s) sem origem verificável: {', '.join(a.numeros_suspeitos)}")
    if notas:
        partes.append(f"({'; '.join(notas)})")
    return "• " + " ".join(partes)


def montar_texto(
    r: RespostaGerada | None,
    v: Verificacao | None,
    avisos_seguranca: list[AvisoTema],
    avisos_sistema: list[str] | None = None,
    nao_encontrei_padrao: str | None = None,
    temas_ja_avisados: set[str] | None = None,
) -> str:
    """`temas_ja_avisados` (modo conversa): temas de segurança cujo aviso
    completo já foi dado nesta conversa viram uma linha de lembrete, em vez de
    repetir o bloco inteiro a cada turno. O aviso nunca some."""
    blocos: list[str] = []

    if v and v.problemas_criticos:
        blocos.append("⚠ VERIFICAÇÃO: atenção antes de usar esta resposta\n" + "\n".join(f"• {p}" for p in v.problemas_criticos))
    if v and not v.executada and v.motivo_nao_executada:
        blocos.append(f"⚠ Esta resposta NÃO passou pelo verificador ({v.motivo_nao_executada}).")

    if r is not None:
        vivas = [a for a in r.afirmacoes if a.status != "removida"]
        fontes = [a for a in vivas if a.tipo == "fonte"]
        infer = [a for a in vivas if a.tipo == "inferencia"]
        web = [a for a in vivas if a.tipo == "web"]
        geral = [a for a in vivas if a.tipo == "geral"]
        if fontes:
            blocos.append("Das fontes:\n" + "\n".join(_linha(a, r) for a in fontes))
        if infer:
            blocos.append(
                "Inferência (raciocínio meu a partir das fontes; não está escrito nelas):\n"
                + "\n".join(_linha(a, r) for a in infer)
            )
        if web:
            blocos.append(
                "Web (NÃO verificado: veio de busca na internet; confira o link antes de confiar):\n"
                + "\n".join(_linha(a, r) for a in web)
            )
        if geral:
            blocos.append(
                "Conhecimento geral (meu, NÃO está nas suas fontes; serve para orientar onde olhar):\n"
                + "\n".join(_linha(a, r) for a in geral)
            )
        if not fontes and geral and not r.falta and r.encontrou:
            blocos.append("Nas suas fontes não encontrei isso: o que está acima é conhecimento geral, sem página para conferir.")
        elif not r.encontrou or not fontes:
            txt = "Não encontrei isso nas fontes."
            if r.falta:
                txt += f" {r.falta}"
            if v and v.numeros_suspeitos_extras.get("falta"):
                txt += f" ⚠ número(s) sem origem: {', '.join(v.numeros_suspeitos_extras['falta'])}"
            blocos.append("Não encontrei nas fontes:\n" + txt)
        elif r.falta:
            blocos.append("O que as fontes não cobrem:\n" + r.falta)
        if r.sugestoes:
            linhas = []
            for i, s in enumerate(r.sugestoes, 1):
                susp = (v.numeros_suspeitos_extras.get(f"sugestao_{i}") if v else None) or []
                linhas.append(f"• {s}" + (f" ⚠ número(s) sem origem: {', '.join(susp)}" if susp else ""))
            blocos.append("Sugestões para descobrir (inferência):\n" + "\n".join(linhas))
        removidas = [a for a in r.afirmacoes if a.status == "removida"]
        if removidas:
            blocos.append(
                "Removidas pelo verificador (não use):\n"
                + "\n".join(f"• \"{a.texto}\": {a.justificativa or 'sem suporte nas fontes'}" for a in removidas)
            )
    elif nao_encontrei_padrao:
        blocos.append(nao_encontrei_padrao)

    if avisos_seguranca:
        ja = temas_ja_avisados or set()
        novos = [t for t in avisos_seguranca if t.tema not in ja]
        repetidos = [_NOME_TEMA.get(t.tema, t.tema.replace("_", " ")) for t in avisos_seguranca if t.tema in ja]
        linhas = list(dict.fromkeys(av for t in novos for av in t.avisos))
        if repetidos:
            linhas.append(f"Continuam valendo os avisos que já dei nesta conversa sobre: {', '.join(repetidos)}.")
        blocos.append("Segurança (avisos gerais do sistema):\n" + "\n".join(f"• {x}" for x in linhas))
    if avisos_sistema:
        blocos.append("Observações do sistema:\n" + "\n".join(f"• {x}" for x in avisos_sistema))
    if r is not None and r.pergunta_ao_usuario:
        # No modo guiado, a pergunta fecha a resposta: é o que a pessoa responde em seguida.
        blocos.append(f"➜ {r.pergunta_ao_usuario}")
    return "\n\n".join(blocos)


# ---------------------------------------------------------------- versão falada
def _citacao_falada(cit: str) -> str:
    """'[Denton, p. 45]' -> 'Denton, página 45'; '[cálculo: lei_de_ohm]' -> 'pela conta'."""
    c = cit.strip("[]")
    if c.startswith("cálculo"):
        return "pela conta"
    if c.startswith("web"):
        return "na internet"
    c = c.replace("pp. ", "páginas ").replace("p. ", "página ").replace("–", " a ")
    return c


def montar_fala(
    r: RespostaGerada | None,
    v: Verificacao | None,
    avisos_seguranca: list[AvisoTema],
    temas_ja_avisados: set[str] | None = None,
    nao_encontrei_padrao: str | None = None,
) -> str:
    """O que o Hefesto FALA: mais curto que o texto da tela, na ordem certa
    para ouvir. Problema crítico primeiro; depois as fontes (com o livro e a
    página ditos de forma natural), a inferência, o conhecimento geral, o
    que não achou, a segurança nova, e por último a pergunta para você.
    Afirmações removidas pelo verificador NÃO são faladas (estão na tela)."""
    partes: list[str] = []
    if v and v.problemas_criticos:
        partes.append("Atenção antes de tudo: " + " ".join(v.problemas_criticos))
    if v and not v.executada and v.motivo_nao_executada:
        partes.append("Esta resposta não passou pelo verificador.")
    if r is None:
        if nao_encontrei_padrao:
            partes.append(nao_encontrei_padrao.split(":")[0] + ". Os trechos estão na tela.")
    else:
        por_id = {t.id: t for t in r.contexto}
        vivas = [a for a in r.afirmacoes if a.status != "removida"]
        for a in vivas:
            if a.tipo == "fonte":
                cits = [_citacao_falada(por_id[t].citacao) for t in a.trechos if t in por_id]
                partes.append(a.texto + (f" Segundo {', '.join(dict.fromkeys(cits))}." if cits else ""))
        infer = [a.texto for a in vivas if a.tipo == "inferencia"]
        if infer:
            partes.append("Pelo meu raciocínio, sem estar escrito nas fontes: " + " ".join(infer))
        geral = [a.texto for a in vivas if a.tipo == "geral"]
        if geral:
            partes.append("Sem fonte, só para te orientar: " + " ".join(geral))
        web = [a.texto for a in vivas if a.tipo == "web"]
        if web:
            partes.append("Da internet, sem verificação: " + " ".join(web))
        if not any(a.tipo == "fonte" for a in vivas) and not geral:
            partes.append("Não encontrei isso nas suas fontes." + (f" {r.falta}" if r.falta else ""))
        if any(a.status == "removida" for a in r.afirmacoes):
            partes.append("Tirei da resposta algumas afirmações que não consegui confirmar; estão na tela.")
    ja = temas_ja_avisados or set()
    novos = [t for t in avisos_seguranca if t.tema not in ja]
    if novos:
        # Falado: só o PRIMEIRO aviso de cada tema novo (o completo está na tela).
        partes.append("Cuidado: " + " ".join(t.avisos[0] for t in novos if t.avisos))
    if r is not None and r.pergunta_ao_usuario:
        partes.append(r.pergunta_ao_usuario)
    return " ".join(p.strip() for p in partes if p.strip())
