"""Monta o registro de ferramentas disponíveis para o modelo.

As descrições abaixo são o que o modelo lê para decidir o que chamar: elas
dizem a unidade de cada argumento e de onde o valor deve vir.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from engenheiro.eventos import Barramento

from . import eletrica, esp32, motor, unidades
from .base import ErroFerramenta, Ferramenta, Registro, numero

__all__ = ["criar_registro", "Registro", "ErroFerramenta"]


def _yaml(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}


def criar_registro(raiz: Path, barramento: Barramento | None = None, caderno=None, perfil=None,
                   telemetria=None, ref=None, inventario: Path | None = None) -> Registro:
    """`raiz`: pasta do projeto. `ref(nome)`: caminho de um arquivo de
    dados_ref/ (o padrão é o do projeto; a fábrica passa a versão que respeita
    as suas cópias personalizadas). `inventario`: o SEU inventário."""
    reg = Registro(barramento)
    ref = ref or (lambda nome: raiz / "dados_ref" / nome)
    const = _yaml(ref("constantes.yaml"))
    combustiveis = (_yaml(ref("combustiveis.yaml"))).get("combustiveis", {})
    inventario = inventario or raiz / "modelos" / "inventario.yaml"
    tabela_pinos = str(ref("esp32_pinos.yaml"))

    def cfg_motor(nome: str, padrao: int) -> int:
        # Só usa o perfil se o campo estiver CONFIRMADO.
        v = perfil.valor_confirmado(f"veiculo.{nome}") if perfil else None
        return int(v) if v is not None else padrao

    reg.registrar(Ferramenta(
        "lei_de_ohm", "Lei de Ohm: informe exatamente dois entre tensão (V), corrente (A) e resistência (Ω); devolve o terceiro e a potência.",
        {"type": "object", "properties": {"tensao_v": numero("volts"), "corrente_a": numero("ampères"),
                                          "resistencia_ohm": numero("ohms")}},
        eletrica.lei_de_ohm))
    reg.registrar(Ferramenta(
        "potencia", "Potência elétrica a partir de dois entre tensão (V), corrente (A) e resistência (Ω).",
        {"type": "object", "properties": {"tensao_v": numero("volts"), "corrente_a": numero("ampères"),
                                          "resistencia_ohm": numero("ohms")}},
        eletrica.potencia))
    reg.registrar(Ferramenta(
        "divisor_tensao",
        "Divisor de tensão R1 (entre entrada e saída) / R2 (entre saída e GND): saída nominal e de pior caso pela tolerância. "
        "Use para conferir se um sinal do carro fica abaixo do limite do ADC.",
        {"type": "object", "required": ["vin_v", "r1_ohm", "r2_ohm"],
         "properties": {"vin_v": numero("tensão de entrada em volts (use a MÁXIMA esperada)"), "r1_ohm": numero("ohms"),
                        "r2_ohm": numero("ohms"), "tolerancia_pct": numero("tolerância dos resistores em %, padrão 1"),
                        "vout_max_permitido_v": numero("limite da entrada que recebe o sinal, em volts")}},
        eletrica.divisor_tensao))

    def escolher(vin_max_v, vout_max_v, tolerancia_pct=1.0, r_total_min_ohm=10_000, r_total_max_ohm=200_000):
        valores = eletrica.valores_do_kit(inventario) if inventario.exists() else []
        return eletrica.escolher_divisor(vin_max_v, vout_max_v, valores, tolerancia_pct, r_total_min_ohm, r_total_max_ohm)

    reg.registrar(Ferramenta(
        "escolher_divisor",
        "Escolhe R1/R2 entre os resistores QUE O USUÁRIO TEM (inventário) para que a saída nunca passe do limite no pior caso.",
        {"type": "object", "required": ["vin_max_v", "vout_max_v"],
         "properties": {"vin_max_v": numero("maior tensão de entrada esperada, V"), "vout_max_v": numero("limite da saída, V"),
                        "tolerancia_pct": numero("tolerância %"), "r_total_min_ohm": numero("Ω"), "r_total_max_ohm": numero("Ω")}},
        escolher))
    reg.registrar(Ferramenta(
        "queda_tensao_fio",
        "Queda de tensão em fio de cobre. comprimento_m = comprimento do fio de ida. retorno_pelo_chassi=true (padrão no carro) "
        "conta só a ida; false conta ida e volta. Informe secao_mm2 OU awg.",
        {"type": "object", "required": ["corrente_a", "comprimento_m"],
         "properties": {"corrente_a": numero("A"), "comprimento_m": numero("metros"), "secao_mm2": numero("mm²"),
                        "awg": {"type": "integer", "description": "bitola AWG"},
                        "retorno_pelo_chassi": {"type": "boolean"}, "temperatura_c": numero("°C do fio, padrão 20"),
                        "tensao_sistema_v": numero("tensão do sistema para calcular a queda em %")}},
        lambda **kw: eletrica.queda_tensao_fio(**kw, constantes=const.get("cobre"))))
    reg.registrar(Ferramenta(
        "dimensionar_fusivel",
        "Sugere o fusível de lâmina padrão para uma carga (regra prática) e confere com a capacidade do fio, se informada.",
        {"type": "object", "required": ["corrente_carga_a"],
         "properties": {"corrente_carga_a": numero("corrente contínua da carga, A"),
                        "capacidade_fio_a": numero("capacidade de corrente do fio, A (de uma fonte)")}},
        lambda **kw: eletrica.dimensionar_fusivel(**kw, constantes=const.get("fusiveis_lamina"))))
    reg.registrar(Ferramenta(
        "filtro_rc", "Filtro RC passa-baixa: informe dois entre resistência (Ω), capacitância (µF) e frequência de corte (Hz).",
        {"type": "object", "properties": {"resistencia_ohm": numero("Ω"), "capacitancia_uf": numero("µF"),
                                          "frequencia_corte_hz": numero("Hz")}},
        eletrica.filtro_rc))
    reg.registrar(Ferramenta(
        "converter_unidade", "Converte unidades (ex.: kgf.m -> N.m, psi -> bar, °C -> °F, polegada -> mm).",
        {"type": "object", "required": ["valor", "de", "para"],
         "properties": {"valor": numero("valor"), "de": {"type": "string"}, "para": {"type": "string"}}},
        unidades.converter_unidade))
    reg.registrar(Ferramenta(
        "verificar_pinos_esp32",
        "Confere pinos do ESP32 da placa do usuário para um uso: alerta pinos só de entrada, de strapping, da flash, "
        "ADC2 com Wi-Fi etc. Sempre use antes de recomendar um pino.",
        {"type": "object", "required": ["pinos", "uso"],
         "properties": {"pinos": {"type": "array", "items": {"type": "string"}, "description": "ex.: ['GPIO34', '21']"},
                        "uso": {"type": "string", "enum": esp32.USOS}, "wifi_ativo": {"type": "boolean"}}},
        lambda pinos, uso, wifi_ativo=True: esp32.verificar_pinos(pinos, uso, wifi_ativo, tabela_pinos)))
    reg.registrar(Ferramenta(
        "rotacao_por_pulsos",
        "Converte frequência do sinal de ignição (Hz) em rotação (rpm) ou o inverso. Padrão do perfil: 4 cilindros, 4 tempos "
        "(2 faíscas por volta do virabrequim).",
        {"type": "object", "properties": {"frequencia_hz": numero("Hz"), "rpm": numero("rpm"),
                                          "cilindros": {"type": "integer"}, "tempos": {"type": "integer", "enum": [2, 4]},
                                          "pulsos_por_faisca": numero("padrão 1")}},
        lambda **kw: motor.rotacao_por_pulsos(**{"cilindros": cfg_motor("cilindros", 4), "tempos": cfg_motor("tempos", 4), **kw})))
    reg.registrar(Ferramenta(
        "velocidade_por_rotacao",
        "Velocidade (km/h) a partir de rpm, relação da marcha, relação do diferencial e medida do pneu. "
        "As relações e o pneu precisam vir do perfil CONFIRMADO ou de uma fonte; não invente.",
        {"type": "object", "required": ["rpm", "relacao_marcha", "relacao_diferencial"],
         "properties": {"rpm": numero("rpm"), "relacao_marcha": numero("ex.: 3.45"), "relacao_diferencial": numero("ex.: 4.11"),
                        "medida_pneu": {"type": "string", "description": "ex.: '175/70 R13'"},
                        "diametro_pneu_mm": numero("alternativa à medida")}},
        lambda diametro_pneu_mm=None, **kw: motor.velocidade_por_rotacao(diametro_pneu_mm_=diametro_pneu_mm, **kw)))
    reg.registrar(Ferramenta(
        "lambda_afr",
        "Converte lambda <-> relação ar/combustível (AFR). A relação estequiométrica vem de dados_ref/combustiveis.yaml "
        "(confirmada) ou de afr_estequiometrico + fonte_estequiometrico citados de um trecho da base.",
        {"type": "object", "required": ["combustivel"],
         "properties": {"combustivel": {"type": "string", "enum": sorted(combustiveis) or ["etanol_hidratado"]},
                        "lambda": numero("λ"), "afr": numero("AFR"),
                        "afr_estequiometrico": numero("só se vier de uma fonte"),
                        "fonte_estequiometrico": {"type": "string", "description": "ex.: '[Livro, p. 45]'"}}},
        lambda combustivel, **kw: motor.lambda_afr(combustivel, lambda_=kw.pop("lambda", None), tabela=combustiveis, **kw)))

    def consultar_inventario(termo: str = "", categoria: str | None = None) -> dict:
        from engenheiro import inventario as inv

        dados = inv.carregar(inventario)
        t = termo.lower()
        itens = [c for c in dados.itens if (not categoria or c.categoria == categoria)
                 and (not t or t in f"{c.id} {c.nome}".lower() or any(t in str(e.valor).lower() for e in c.especificacoes))]
        return {"resultado": {"itens": [
            {"id": c.id, "nome": c.nome, "quantidade": c.quantidade,
             "especificacoes": {e.item: f"{e.valor} ({e.status})" for e in c.especificacoes},
             "cuidados": c.cuidados} for c in itens]},
            "formula": "consulta ao seu inventário (data/usuario/inventario.yaml)", "notas": ["(status) indica se o dado foi confirmado."]}

    reg.registrar(Ferramenta(
        "consultar_inventario",
        "Consulta os componentes que o usuário TEM (quantidade, especificações confirmadas ou não, cuidados). "
        "Use antes de sugerir um circuito ou uma compra.",
        {"type": "object", "properties": {"termo": {"type": "string"}, "categoria": {"type": "string"}}},
        consultar_inventario))

    if caderno is not None:
        def buscar_caderno(termo: str = "", limite: int = 10) -> dict:
            achadas = caderno.buscar(termo, limite)
            return {"resultado": {"anotacoes": [{"citacao": a.citacao, "titulo": a.titulo, "texto": a.texto, "tags": a.tags}
                                                for a in achadas]},
                    "formula": "busca de texto no caderno de bordo", "notas": ["São anotações do usuário, não fontes técnicas."]}

        reg.registrar(Ferramenta(
            "buscar_caderno", "Busca no caderno de bordo do usuário (o que ele fez, mediu e decidiu, com data).",
            {"type": "object", "properties": {"termo": {"type": "string"}, "limite": {"type": "integer"}}},
            buscar_caderno))

    def ler_telemetria(sinal: str) -> dict:
        # Sem cliente MQTT ligado, não há de onde ler (ver engenheiro servir).
        if telemetria is None:
            raise ErroFerramenta(f"telemetria ao vivo indisponível (sinal pedido: {sinal}): o serviço MQTT não está ligado")
        return telemetria.ler(sinal)

    reg.registrar(Ferramenta(
        "ler_telemetria",
        "Lê o último valor AO VIVO de um sinal do carro (via MQTT), recusando dado velho. "
        "Se o sinal não existir, o erro lista os sinais disponíveis.",
        {"type": "object", "required": ["sinal"], "properties": {"sinal": {"type": "string", "description": "ex.: rpm, temp_motor"}}},
        ler_telemetria))
    return reg
