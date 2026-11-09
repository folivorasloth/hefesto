"""Inventário de componentes físicos (seu: data/usuario/inventario.yaml; modelo: modelos/inventario.yaml).

Validação estrita: o engenheiro vai usar este arquivo para saber o que você
tem antes de propor um circuito. Um status escrito errado ("confirmdo") ou
um id repetido tem que falhar alto, não virar "verdade" silenciosamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

STATUS_VALIDOS = {"confirmado", "provavel", "a_confirmar"}
CATEGORIAS_VALIDAS = {
    "microcontrolador", "alimentacao", "interface", "display", "saida", "entrada",
    "passivo", "semicondutor", "sensor", "montagem", "ferramenta", "outro",
}


class InventarioInvalido(ValueError):
    pass


@dataclass
class Especificacao:
    item: str
    valor: str | None
    status: str
    fonte: str | None = None


@dataclass
class Componente:
    id: str
    nome: str
    categoria: str
    quantidade: int | None
    projetos: list[str]
    especificacoes: list[Especificacao] = field(default_factory=list)
    cuidados: list[str] = field(default_factory=list)
    pendencias: list[str] = field(default_factory=list)
    descricao_compra: str | None = None

    @property
    def tem_pendencia(self) -> bool:
        return bool(self.pendencias) or self.quantidade is None or any(e.status != "confirmado" for e in self.especificacoes)


@dataclass
class Inventario:
    itens: list[Componente]
    faltando_sugerido: list[dict]

    def por_id(self, id_: str) -> Componente | None:
        return next((c for c in self.itens if c.id == id_), None)


def carregar(caminho: Path) -> Inventario:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    erros: list[str] = []
    itens: list[Componente] = []
    vistos: set[str] = set()
    for n, bruto in enumerate(dados.get("itens") or [], start=1):
        onde = f"item {n} ({bruto.get('id', 'sem id')})"
        for campo in ("id", "nome", "categoria", "projetos"):
            if not bruto.get(campo):
                erros.append(f"{onde}: falta '{campo}'")
        if bruto.get("id") in vistos:
            erros.append(f"{onde}: id repetido")
        vistos.add(bruto.get("id"))
        if bruto.get("categoria") and bruto["categoria"] not in CATEGORIAS_VALIDAS:
            erros.append(f"{onde}: categoria '{bruto['categoria']}' inválida (use uma de {sorted(CATEGORIAS_VALIDAS)})")
        qtd = bruto.get("quantidade")
        if qtd is not None and (not isinstance(qtd, int) or qtd < 0):
            erros.append(f"{onde}: quantidade deve ser inteiro >= 0 ou null")
        especs = []
        for e in bruto.get("especificacoes") or []:
            if e.get("status") not in STATUS_VALIDOS:
                erros.append(f"{onde}: especificação '{e.get('item')}' com status '{e.get('status')}' inválido")
            if e.get("status") == "confirmado" and not e.get("fonte"):
                erros.append(f"{onde}: especificação '{e.get('item')}' confirmada sem 'fonte'")
            especs.append(Especificacao(e.get("item", "?"), e.get("valor"), e.get("status", "?"), e.get("fonte")))
        itens.append(Componente(
            id=bruto.get("id", ""), nome=bruto.get("nome", ""), categoria=bruto.get("categoria", ""),
            quantidade=qtd, projetos=list(bruto.get("projetos") or []), especificacoes=especs,
            cuidados=list(bruto.get("cuidados") or []), pendencias=list(bruto.get("pendencias") or []),
            descricao_compra=bruto.get("descricao_compra"),
        ))
    if erros:
        raise InventarioInvalido("Inventário com problemas:\n- " + "\n- ".join(erros))
    return Inventario(itens, list(dados.get("faltando_sugerido") or []))
