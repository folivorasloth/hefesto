from pathlib import Path

import pytest

from engenheiro.inventario import InventarioInvalido, carregar

RAIZ = Path(__file__).parents[1]


def test_inventario_real_e_valido():
    inv = carregar(RAIZ / "inventario" / "componentes.yaml")
    esp = inv.por_id("esp32-devkit-38p")
    assert esp is not None and esp.quantidade == 1
    # O alerta dos pinos de flash não pode sumir do inventário.
    assert any("GPIO 6 a 11" in c for c in esp.cuidados)
    assert inv.por_id("multimetro-astroai-dt132a") is not None
    r = inv.por_id("resistores-kit-600").especificacoes
    valores = next(e.valor for e in r if e.item == "valores").split(", ")
    assert len(valores) == 30  # 30 valores da etiqueta


def test_status_invalido_falha(tmp_path):
    p = tmp_path / "i.yaml"
    p.write_text(
        "itens:\n  - {id: x, nome: X, categoria: passivo, projetos: [hefesto],\n"
        "     especificacoes: [{item: v, valor: '1', status: confirmdo, fonte: f}]}\n", encoding="utf-8")
    with pytest.raises(InventarioInvalido, match="confirmdo"):
        carregar(p)


def test_confirmado_exige_fonte_e_id_unico(tmp_path):
    p = tmp_path / "i.yaml"
    p.write_text(
        "itens:\n"
        "  - {id: x, nome: X, categoria: passivo, projetos: [h], especificacoes: [{item: v, valor: '1', status: confirmado}]}\n"
        "  - {id: x, nome: Y, categoria: passivo, projetos: [h]}\n", encoding="utf-8")
    with pytest.raises(InventarioInvalido) as e:
        carregar(p)
    assert "sem 'fonte'" in str(e.value) and "id repetido" in str(e.value)
