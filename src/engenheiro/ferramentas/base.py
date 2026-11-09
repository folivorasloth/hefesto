"""Registro e execução de ferramentas.

Regra do projeto: TODA conta passa por ferramenta, nunca pelo LLM. O modelo
decide qual ferramenta chamar e com quais números (que precisam vir das
fontes, do perfil ou da pergunta); o Python faz a conta. O resultado vira
uma fonte citável ("F1", "F2"...) e o verificador de números aceita os
valores que saíram dela.

Cada ferramenta devolve um dicionário com, no mínimo:
    resultado: os valores calculados
    formula:   a fórmula usada (para você conferir à mão)
    notas:     premissas e limitações (ex.: "regra prática, não norma")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from engenheiro.eventos import Barramento


class ErroFerramenta(ValueError):
    """Entrada inválida ou dado faltando. A mensagem vai para o modelo e para
    você: precisa dizer o que falta, não só que deu erro."""


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict             # JSON Schema dos argumentos
    funcao: Callable[..., dict]

    def esquema_ollama(self) -> dict:
        return {"type": "function", "function": {"name": self.nome, "description": self.descricao,
                                                  "parameters": self.parametros}}


@dataclass
class Chamada:
    id: str                      # "F1", "F2"...
    nome: str
    argumentos: dict
    saida: dict | None = None
    erro: str | None = None

    @property
    def citacao(self) -> str:
        return f"[cálculo: {self.nome}]"

    @property
    def texto(self) -> str:
        """Texto usado pelo verificador e pela checagem de números."""
        corpo = self.saida if self.erro is None else {"erro": self.erro}
        return f"{self.nome}({json.dumps(self.argumentos, ensure_ascii=False)}) -> {json.dumps(corpo, ensure_ascii=False, default=str)}"

    # Mesma interface dos trechos de livro (TrechoContexto), para o gerador,
    # o verificador e a montagem tratarem tudo igual.
    origens: list[str] = field(default_factory=lambda: ["ferramenta"])

    def para_prompt(self) -> str:
        return f"[{self.id}] Ferramenta {self.nome}\n{self.texto}"


def _validar(esquema: dict, args: dict) -> dict:
    """Validação mínima (tipos e obrigatórios), sem depender de jsonschema.
    Converte números que o modelo mande como texto ("12,5" -> 12.5)."""
    props = esquema.get("properties", {})
    saida = {}
    for nome in esquema.get("required", []):
        if args.get(nome) is None:
            raise ErroFerramenta(f"argumento obrigatório faltando: {nome}")
    for nome, valor in args.items():
        if nome not in props:
            raise ErroFerramenta(f"argumento desconhecido: {nome}")
        tipo = props[nome].get("type")
        if valor is None:
            continue
        if tipo == "number":
            if isinstance(valor, str):
                try:
                    valor = float(valor.replace(",", "."))
                except ValueError as e:
                    raise ErroFerramenta(f"{nome} deve ser número, veio {valor!r}") from e
            if not isinstance(valor, (int, float)) or isinstance(valor, bool):
                raise ErroFerramenta(f"{nome} deve ser número, veio {valor!r}")
        elif tipo == "integer":
            if isinstance(valor, str) and valor.strip().lstrip("-").isdigit():
                valor = int(valor)
            if not isinstance(valor, int) or isinstance(valor, bool):
                raise ErroFerramenta(f"{nome} deve ser inteiro, veio {valor!r}")
        elif tipo == "boolean" and not isinstance(valor, bool):
            raise ErroFerramenta(f"{nome} deve ser true/false, veio {valor!r}")
        elif tipo == "array" and not isinstance(valor, list):
            valor = [valor]
        if "enum" in props[nome] and valor not in props[nome]["enum"]:
            raise ErroFerramenta(f"{nome} deve ser um de {props[nome]['enum']}, veio {valor!r}")
        saida[nome] = valor
    return saida


class Registro:
    def __init__(self, barramento: Barramento | None = None) -> None:
        self.ferramentas: dict[str, Ferramenta] = {}
        self.bus = barramento or Barramento()
        self.chamadas: list[Chamada] = []

    def registrar(self, f: Ferramenta) -> None:
        self.ferramentas[f.nome] = f

    def esquemas(self) -> list[dict]:
        return [f.esquema_ollama() for f in self.ferramentas.values()]

    def nova_sessao(self) -> None:
        self.chamadas = []

    def executar(self, nome: str, argumentos: dict | str | None) -> Chamada:
        if isinstance(argumentos, str):
            try:
                argumentos = json.loads(argumentos or "{}")
            except json.JSONDecodeError:
                argumentos = {"_bruto": argumentos}
        argumentos = argumentos or {}
        ch = Chamada(f"F{len(self.chamadas) + 1}", nome, dict(argumentos))
        self.chamadas.append(ch)
        f = self.ferramentas.get(nome)
        try:
            if f is None:
                raise ErroFerramenta(f"ferramenta inexistente: {nome}. Disponíveis: {sorted(self.ferramentas)}")
            ch.saida = f.funcao(**_validar(f.parametros, argumentos))
        except ErroFerramenta as e:
            ch.erro = str(e)
        except Exception as e:  # noqa: BLE001 - defeito numa ferramenta não derruba a resposta
            ch.erro = f"falha interna: {e!r}"
        self.bus.publicar("ferramenta.chamada", id=ch.id, nome=nome, argumentos=ch.argumentos,
                          saida=ch.saida, erro=ch.erro)
        return ch


def numero(descricao: str, **extra) -> dict:
    return {"type": "number", "description": descricao, **extra}
