from engenheiro.ingest.chunker import dividir, eh_aviso, numero_do_passo
from engenheiro.ingest.modelos import Bloco


def T(texto, nivel=1, p=1):
    return Bloco("titulo", texto, p, nivel=nivel)


def P(texto, p=1, tipo="paragrafo", origem="texto"):
    return Bloco(tipo, texto, p, origem=origem)


def test_numero_do_passo():
    assert numero_do_passo("1 Aqueça o motor") == 1
    assert numero_do_passo("2. Desligue") == 2
    assert numero_do_passo("3) Conecte") == 3
    assert numero_do_passo("Passo 4: gire") == 4
    assert numero_do_passo("Step 5 - turn") == 5
    # Não são passos:
    assert numero_do_passo("1.5 V é a tensão de referência") is None
    assert numero_do_passo("12V no positivo") is None
    assert numero_do_passo("Aqueça o motor") is None


def test_eh_aviso():
    assert eh_aviso("ATENÇÃO: desligue a bateria")
    assert eh_aviso("Cuidado com o combustível")
    assert eh_aviso("WARNING: fuel vapour")
    assert not eh_aviso("A atenção do mecânico")


def test_caminho_de_titulos_e_secoes_separadas():
    blocos = [
        T("1 Motor", 1),
        T("1.1 Cabeçote", 2),
        P("texto do cabeçote"),
        T("1.2 Bloco", 2),
        P("texto do bloco"),
        T("2 Elétrica", 1),
        P("texto elétrico"),
    ]
    tr = dividir(blocos)
    assert [t.caminho_titulos for t in tr] == [
        ["1 Motor", "1.1 Cabeçote"],
        ["1 Motor", "1.2 Bloco"],
        ["2 Elétrica"],
    ]
    # Título sem conteúdo próprio (1 Motor) não gera trecho vazio.
    assert all(t.texto.strip() for t in tr)


def test_tabela_nunca_e_cortada_mesmo_maior_que_o_maximo():
    tabela = "| a | b |\n" + "\n".join(f"| linha {i} | valor {i} |" for i in range(200))
    tr = dividir([T("Torques"), P("intro"), Bloco("tabela", tabela, 1), P("depois")], max_caracteres=500)
    com_tabela = [t for t in tr if "tabela" in t.tipos]
    assert len(com_tabela) == 1
    assert tabela in com_tabela[0].texto
    assert com_tabela[0].oversize


def test_procedimento_atravessa_pagina_e_fica_inteiro():
    passos = [P(f"{i} Passo número {i}. " + "detalhe " * 30, p=1 if i <= 3 else 2, tipo="item_lista") for i in range(1, 11)]
    tr = dividir([T("Regulagem"), P("Intro curta.")] + passos, max_caracteres=600)
    proc = [t for t in tr if "procedimento" in t.tipos]
    assert len(proc) == 1
    t = proc[0]
    assert "1 Passo número 1." in t.texto and "10 Passo número 10." in t.texto
    assert (t.pagina_inicio, t.pagina_fim) == (1, 2)
    assert t.oversize


def test_procedimento_tolera_nota_entre_passos():
    blocos = [T("S"), P("1 Primeiro"), P("NOTA: observação do passo 1"), P("2 Segundo"), P("3 Terceiro")]
    tr = dividir(blocos)
    assert len(tr) == 1 and "procedimento" in tr[0].tipos
    assert "NOTA" in tr[0].texto


def test_aviso_gruda_no_procedimento_seguinte():
    enchimento = [P("Parágrafo de enchimento. " * 20) for _ in range(3)]
    blocos = (
        [T("Marcha lenta")]
        + enchimento
        + [P("ATENÇÃO: local ventilado, risco de incêndio."), P("1 Aqueça"), P("2 Ajuste"), P("3 Confira")]
    )
    tr = dividir(blocos, max_caracteres=800)
    com_aviso = [t for t in tr if "ATENÇÃO" in t.texto]
    assert len(com_aviso) == 1
    assert "1 Aqueça" in com_aviso[0].texto and "3 Confira" in com_aviso[0].texto
    assert "aviso" in com_aviso[0].tipos


def test_um_numero_sozinho_nao_e_procedimento():
    tr = dividir([T("S"), P("1 vez por ano troque o óleo."), P("Outro parágrafo.")])
    assert "procedimento" not in tr[0].tipos


def test_paragrafos_agrupados_com_sobreposicao():
    frases = [P(f"Frase número {i} do texto corrido. Outra frase {i}.") for i in range(40)]
    tr = dividir([T("Teoria")] + frases, max_caracteres=400, sobreposicao=80)
    assert len(tr) > 1
    assert all(len(t.texto) <= 400 + 80 + 10 for t in tr)
    # O segundo trecho começa com a cauda do primeiro, sinalizada com (…)
    assert tr[1].texto.startswith("(…) ")
    cauda = tr[1].texto[4:].split("\n\n")[0]
    assert cauda in tr[0].texto


def test_nao_ha_sobreposicao_vinda_de_tabela():
    tabela = "| x |\n" + "| 1 |\n" * 50
    tr = dividir([T("S"), Bloco("tabela", tabela, 1), P("Texto depois da tabela. " * 10)], max_caracteres=300)
    assert not tr[-1].texto.startswith("(…)")


def test_paragrafo_gigante_dividido_por_frases():
    longo = " ".join(f"Frase {i} termina aqui." for i in range(300))
    tr = dividir([T("S"), P(longo)], max_caracteres=500, sobreposicao=0)
    assert len(tr) > 3
    assert all(len(t.texto) <= 500 for t in tr)
    juntos = " ".join(t.texto for t in tr)
    assert "Frase 0 termina" in juntos and "Frase 299 termina" in juntos


def test_origem_ocr_preservada():
    tr = dividir([T("S"), P("texto escaneado", origem="ocr")])
    assert tr[0].origens == ["ocr"]
