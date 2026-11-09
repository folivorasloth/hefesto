from pathlib import Path
from types import SimpleNamespace

from engenheiro.geracao.gerador import montar_contexto
from engenheiro.seguranca import Seguranca
from engenheiro.verificador.verificador import eh_critica

RAIZ = Path(__file__).parents[1]


def _cand(texto, i):
    t = SimpleNamespace(id=i, texto=texto, secao="S", idioma="pt", origens=["texto"], arquivo="v/l.pdf",
                        citacao="L", pagina_inicio=1, pagina_fim=1, deslocamento_paginas=0)
    return SimpleNamespace(trecho=t, rerank=0.9)


def test_contexto_respeita_a_janela_e_avisa():
    cands = [_cand("x" * 3000, i) for i in range(8)]
    # num_ctx pequeno: cabem poucos trechos; o resto sai COM aviso.
    ctx, avisos = montar_contexto(cands, num_ctx=4096, tamanho_fixo=2000, maximo=8)
    assert 0 < len(ctx) < 8
    assert len(avisos) == 8 - len(ctx) and "num_ctx" in avisos[0]
    assert [t.id for t in ctx] == [f"T{i}" for i in range(1, len(ctx) + 1)]


def test_contexto_respeita_maximo_de_trechos():
    ctx, _ = montar_contexto([_cand("curto", i) for i in range(10)], 12288, 1000, maximo=3)
    assert len(ctx) == 3


def test_seguranca_por_tema():
    s = Seguranca.carregar(RAIZ / "dados_ref" / "seguranca.yaml")
    temas = {t.tema for t in s.avisos_para("Vou trocar a bobina e limpar o carburador")}
    assert {"ignicao", "combustivel"} <= temas
    assert {t.tema for t in s.avisos_para("Quero ligar o ESP32 nos 12V do carro")} >= {"eletronica_12v"}
    assert s.avisos_para("Qual a cor do painel?") == []


def test_seguranca_casa_plural_e_sem_acento():
    s = Seguranca.carregar(RAIZ / "dados_ref" / "seguranca.yaml")
    assert {t.tema for t in s.avisos_para("as baterias e a IGNICAO")} >= {"bateria", "ignicao"}


def test_criticidade_deterministica():
    assert eh_critica("A tensão no pino é 5 V")
    assert eh_critica("aperte a 40 N·m")
    assert eh_critica("risco de incêndio")
    assert not eh_critica("O distribuidor fica na frente do motor")
