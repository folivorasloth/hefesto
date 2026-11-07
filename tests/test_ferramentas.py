"""Ferramentas de cálculo contra valores conhecidos (a conta está no comentário)."""

import math
from pathlib import Path

import pytest

from engenheiro.ferramentas import criar_registro
from engenheiro.ferramentas.base import ErroFerramenta
from engenheiro.ferramentas import eletrica as el, motor, unidades
from engenheiro.ferramentas.esp32 import verificar_pinos

RAIZ = Path(__file__).parents[1]
TABELA = str(RAIZ / "dados_ref" / "esp32_pinos.yaml")
aprox = lambda x, rel=1e-4: pytest.approx(x, rel=rel)  # noqa: E731


# ------------------------------------------------------------------ Ohm
def test_ohm_e_potencia():
    r = el.lei_de_ohm(tensao_v=12, corrente_a=2)["resultado"]   # R = 12/2 = 6; P = 24
    assert r["resistencia_ohm"] == 6 and r["potencia_w"] == 24
    assert el.lei_de_ohm(corrente_a=0.02, resistencia_ohm=150)["resultado"]["tensao_v"] == aprox(3.0)


def test_ohm_exige_dois_valores():
    with pytest.raises(ErroFerramenta, match="exatamente dois"):
        el.lei_de_ohm(tensao_v=12)


# ------------------------------------------------------------------ divisor
def test_divisor_nominal_e_pior_caso():
    # 12 V, 10k/10k: 6 V. Com 1%: max = 12×10,1/(9,9+10,1) = 6,06; min = 12×9,9/(10,1+9,9) = 5,94
    r = el.divisor_tensao(12, 10_000, 10_000, 1.0)["resultado"]
    assert r["vout_nominal_v"] == aprox(6.0)
    assert r["vout_max_v"] == aprox(6.06) and r["vout_min_v"] == aprox(5.94)
    assert r["corrente_a"] == aprox(0.0006)


def test_divisor_alerta_acima_do_limite():
    r = el.divisor_tensao(15, 10_000, 3_300, 1.0, vout_max_permitido_v=3.3)
    # nominal = 15×3,3/13,3 = 3,7218 V > 3,3
    assert r["resultado"]["dentro_do_limite"] is False and r["notas"][0].startswith("ALERTA")


def test_notacao_de_resistor():
    assert [el.converter_notacao_resistor(v) for v in ("10R", "4K7", "2K2", "1M", "100K")] == [10, 4700, 2200, 1e6, 1e5]


def test_escolher_divisor_usa_valores_do_inventario():
    valores = el.valores_do_kit(RAIZ / "inventario" / "componentes.yaml")
    assert len(valores) == 30
    r = el.escolher_divisor(16.0, 3.3, valores)["resultado"]["pares"]
    assert r and all(p["vout_max_pior_caso_v"] <= 3.3 for p in r)
    assert all(p["r1_ohm"] in valores and p["r2_ohm"] in valores for p in r)
    # Confere o melhor par com a ferramenta de divisor (duas implementações, mesmo número)
    p = r[0]
    d = el.divisor_tensao(16.0, p["r1_ohm"], p["r2_ohm"], 1.0)["resultado"]
    assert d["vout_max_v"] == aprox(p["vout_max_pior_caso_v"])


# ------------------------------------------------------------------ fios
def test_awg_pela_definicao():
    # AWG 10: d = 0,127 × 92^(26/39) = 2,588 mm -> 5,261 mm²; AWG 18 -> 0,8231 mm²
    assert el.awg_para_mm2(10) == aprox(5.2612, 1e-3)
    assert el.awg_para_mm2(18) == aprox(0.8231, 1e-3)


def test_queda_de_tensao_retorno_pelo_chassi():
    # 1 mm², 1 m, 1 A, 20 °C: R = 0,017241 Ω; ΔV = 0,017241 V
    r = el.queda_tensao_fio(1, 1, secao_mm2=1)["resultado"]
    assert r["resistencia_ohm"] == aprox(0.017241) and r["queda_v"] == aprox(0.017241)


def test_queda_de_tensao_ida_e_volta_com_percentual():
    # 2,5 mm², 5 m ida + 5 m volta, 10 A: R = 0,017241×10/2,5 = 0,068964 Ω; ΔV = 0,68964 V = 5,747% de 12 V
    r = el.queda_tensao_fio(10, 5, secao_mm2=2.5, retorno_pelo_chassi=False, tensao_sistema_v=12)["resultado"]
    assert r["queda_v"] == aprox(0.68964) and r["queda_pct"] == aprox(5.747, 1e-3)


def test_queda_de_tensao_com_temperatura():
    # 70 °C: ρ = 0,017241 × (1 + 0,00393×50) = 0,020629
    assert el.queda_tensao_fio(1, 1, secao_mm2=1, temperatura_c=70)["resultado"]["resistencia_ohm"] == aprox(0.020629)


def test_queda_exige_secao_ou_awg():
    with pytest.raises(ErroFerramenta):
        el.queda_tensao_fio(1, 1)


# ------------------------------------------------------------------ fusível e RC
def test_fusivel():
    r = el.dimensionar_fusivel(6)                                   # 6 × 1,25 = 7,5 -> 7,5 A
    assert r["resultado"]["fusivel_padrao_a"] == 7.5 and "REGRA PRÁTICA" in " ".join(r["notas"])
    assert el.dimensionar_fusivel(8)["resultado"]["fusivel_padrao_a"] == 10   # 10 A
    r = el.dimensionar_fusivel(6, capacidade_fio_a=5)
    assert r["resultado"]["fio_suporta"] is False and r["notas"][0].startswith("ALERTA")


def test_filtro_rc():
    # 10 kΩ, 0,1 µF: fc = 1/(2π × 10⁴ × 10⁻⁷) = 159,155 Hz; τ = 1 ms
    r = el.filtro_rc(resistencia_ohm=10_000, capacitancia_uf=0.1)["resultado"]
    assert r["frequencia_corte_hz"] == aprox(159.155) and r["constante_tempo_s"] == aprox(0.001)
    assert el.filtro_rc(resistencia_ohm=10_000, frequencia_corte_hz=159.155)["resultado"]["capacitancia_uf"] == aprox(0.1)


# ------------------------------------------------------------------ motor
def test_rotacao_4_cilindros_4_tempos():
    # 2 faíscas por volta: 100 Hz × 60 / 2 = 3000 rpm
    assert motor.rotacao_por_pulsos(frequencia_hz=100)["resultado"]["rpm"] == 3000
    assert motor.rotacao_por_pulsos(rpm=900)["resultado"]["frequencia_hz"] == 30
    assert motor.faiscas_por_volta(6, 4) == 3


def test_pneu_e_velocidade():
    # 175/70 R13: 13×25,4 + 2×175×0,70 = 330,2 + 245 = 575,2 mm
    assert motor.diametro_pneu_mm("175/70 R13") == aprox(575.2)
    # 3000 rpm, marcha 1:1, diferencial 4:1 -> 750 rpm na roda × π×0,5752 m × 60/1000 = 81,32 km/h
    r = motor.velocidade_por_rotacao(3000, 1.0, 4.0, medida_pneu="175/70 R13")["resultado"]
    assert r["velocidade_kmh"] == aprox(750 * math.pi * 0.5752 * 60 / 1000)


def test_lambda_sem_estequiometria_confirmada_recusa():
    with pytest.raises(ErroFerramenta, match="não foi confirmada"):
        motor.lambda_afr("etanol_hidratado", lambda_=1.0, tabela={"etanol_hidratado": {"afr_estequiometrico": None, "status": "a_confirmar"}})


def test_lambda_exige_fonte_do_valor_informado():
    with pytest.raises(ErroFerramenta, match="sem fonte"):
        motor.lambda_afr("x", lambda_=1.0, afr_estequiometrico=9.0)
    # Valor FICTÍCIO só para testar a conta: 1,1 × 9,0 = 9,9
    r = motor.lambda_afr("x", lambda_=1.1, afr_estequiometrico=9.0, fonte_estequiometrico="teste")["resultado"]
    assert r["afr"] == aprox(9.9) and r["mistura"] == "pobre"


# ------------------------------------------------------------------ unidades
def test_conversoes():
    assert unidades.converter_unidade(10, "kgf.m", "N.m")["resultado"]["valor"] == aprox(98.0665)
    assert unidades.converter_unidade(100, "°C", "°F")["resultado"]["valor"] == aprox(212)
    assert unidades.converter_unidade(1, "bar", "psi")["resultado"]["valor"] == aprox(14.5038)
    assert unidades.converter_unidade(1, "uF", "nF")["resultado"]["valor"] == aprox(1000)  # F é farad
    with pytest.raises(ErroFerramenta):
        unidades.converter_unidade(1, "V", "m")


# ------------------------------------------------------------------ pinos
def _pino(res, i=0):
    return res["resultado"]["pinos"][i]


def test_pino_so_entrada_bloqueia_saida():
    r = verificar_pinos(["GPIO34"], "saida_digital", caminho_tabela=TABELA)
    assert _pino(r)["pode_usar"] is False and r["resultado"]["algum_bloqueio"]


def test_pino_so_entrada_serve_para_analogico():
    assert _pino(verificar_pinos(["34"], "analogico", caminho_tabela=TABELA))["ok"] is True


def test_pino_da_flash_e_proibido():
    for p in ("GPIO6", "SD0", "CMD", "11"):
        assert _pino(verificar_pinos([p], "entrada_digital", caminho_tabela=TABELA))["pode_usar"] is False


def test_adc2_com_wifi():
    r = verificar_pinos(["GPIO4"], "analogico", wifi_ativo=True, caminho_tabela=TABELA)
    assert any(a["restricao"] == "adc2_wifi" for a in _pino(r)["alertas"])
    assert not verificar_pinos(["GPIO4"], "analogico", wifi_ativo=False, caminho_tabela=TABELA)["resultado"]["pinos"][0]["alertas"]
    sugestoes = r["resultado"]["sugestoes_livres"]
    assert sugestoes and all("ADC1" in s for s in sugestoes)


def test_strapping_e_apelidos():
    r = verificar_pinos(["G12", "SP", "G21"], "entrada_digital", caminho_tabela=TABELA)["resultado"]["pinos"]
    assert any(a["restricao"] == "strapping" for a in r[0]["alertas"])
    assert r[1]["gpio"] == 36 and any(a["restricao"] == "sem_pull_interno" for a in r[1]["alertas"])
    assert r[2]["ok"] is True
    # Todo alerta carrega fonte e status (para o verificador saber o quanto confiar).
    assert all("fonte" in a and "status" in a for a in r[0]["alertas"])


def test_pino_inexistente():
    assert _pino(verificar_pinos(["GPIO24"], "entrada_digital", caminho_tabela=TABELA))["pode_usar"] is False


# ------------------------------------------------------------------ registro
def test_registro_valida_argumentos_e_registra_chamadas():
    reg = criar_registro(RAIZ)
    ch = reg.executar("lei_de_ohm", {"tensao_v": "12,0", "corrente_a": 2})   # texto com vírgula vira número
    assert ch.erro is None and ch.saida["resultado"]["resistencia_ohm"] == 6 and ch.id == "F1"
    ch2 = reg.executar("lei_de_ohm", {"tensao_v": "doze"})
    assert ch2.erro and ch2.id == "F2"
    assert "inexistente" in reg.executar("calcular_tudo", {}).erro
    assert "argumento desconhecido" in reg.executar("filtro_rc", {"r": 1}).erro
    assert "6" in ch.texto  # o texto citável contém o resultado


def test_registro_lambda_e_telemetria_honestos():
    reg = criar_registro(RAIZ)
    assert "não foi confirmada" in reg.executar("lambda_afr", {"combustivel": "etanol_hidratado", "lambda": 1.0}).erro
    assert "ainda não disponível" in reg.executar("ler_telemetria", {"sinal": "rpm"}).erro


def test_registro_inventario():
    reg = criar_registro(RAIZ)
    ch = reg.executar("consultar_inventario", {"termo": "esp32"})
    assert any(i["id"] == "esp32-devkit-38p" for i in ch.saida["resultado"]["itens"])
