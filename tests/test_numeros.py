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


# ---------------------------------------------------------------- unidade (fase 4)
def test_unidade_diferente_e_suspeita():
    assert numeros_sem_origem("A tensão é 12 V.", ["corrente de 12 A"]) == ["12"]
    assert numeros_sem_origem("Use 2 A.", ["engate a 2ª marcha"]) == ["2"]


def test_prefixos_convertidos():
    assert numeros_sem_origem("12000 mV", ["12 V"]) == []
    assert numeros_sem_origem("4,7 kΩ", ["resistor de 4700 Ω"]) == []
    assert numeros_sem_origem("150 mA", ["0,15 A"]) == []
    assert numeros_sem_origem("17,3 N·m", ["17,3 Nm"]) == []


def test_numero_sem_unidade_na_origem_ainda_vale():
    # Tabela com cabeçalho "Torque (N·m)" e valores soltos: a célula não tem unidade.
    assert numeros_sem_origem("17,3 N·m", ["| 1 | 17,3 |"]) == []
    # Afirmação sem unidade aceita o valor com qualquer unidade.
    assert numeros_sem_origem("são 3 fios", ["3 V"]) == []


def test_minusculo_a_nao_e_ampere():
    assert numeros_sem_origem("de 3 a 5 voltas", ["entre 3 e 5 voltas"]) == []
