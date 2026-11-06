from engenheiro.verificador.numeros import extrair_numeros, numeros_sem_origem, valores_em


def test_extrai_numeros_mas_nao_codigos():
    assert extrair_numeros("Aperte a 17,3 N·m no GPIO34 [T2], depois 93 graus.") == ["17,3", "93"]
    assert extrair_numeros("Use o T3 e o AP1600") == []


def test_virgula_e_ponto_decimal_equivalentes():
    assert numeros_sem_origem("diâmetro 1,37 mm", ["the diameter is 1.37 mm"]) == []
    assert numeros_sem_origem("resistência 0.77 ohm", ["valor de 0,77 Ω"]) == []


def test_milhar():
    assert 1000.0 in valores_em("1.000 rpm")
    assert 1000.0 in valores_em("1,000 rpm")
    assert numeros_sem_origem("a 3.000 rpm", ["at 3000 rpm"]) == []


def test_numero_inventado_e_suspeito():
    assert numeros_sem_origem("Aperte a 17,8 N·m", ["Etapa 1: 17,3 N·m"]) == ["17,8"]


def test_numero_da_pergunta_e_aceito():
    assert numeros_sem_origem("Com 13,8 V no alternador", ["texto sem números", "medi 13,8 V, está ok?"]) == []


def test_ponto_final_de_frase_nao_atrapalha():
    assert extrair_numeros("O valor é 12.") == ["12"]
    assert numeros_sem_origem("O valor é 12.", ["12 V"]) == []
