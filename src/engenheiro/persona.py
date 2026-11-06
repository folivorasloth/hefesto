"""Carrega a persona (persona/engenheiro.yaml) e monta o trecho do prompt."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Persona:
    nome: str = "Engenheiro"
    descricao: str = "Engenheiro mecânico experiente, didático, calmo e honesto."
    tom: list[str] = field(default_factory=list)
    exemplos: list[dict] = field(default_factory=list)

    @classmethod
    def carregar(cls, caminho: Path) -> "Persona":
        if not caminho.exists():
            return cls()
        d = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        return cls(
            nome=d.get("nome", cls.nome),
            descricao=(d.get("descricao") or cls.descricao).strip(),
            tom=d.get("tom", []),
            exemplos=d.get("exemplos", []),
        )

    def para_prompt(self) -> str:
        partes = [f"Você é {self.nome}. {self.descricao}"]
        if self.tom:
            partes.append("Tom:\n" + "\n".join(f"- {t}" for t in self.tom))
        if self.exemplos:
            partes.append(
                "Exemplos de estilo (só o jeito de falar, não são fatos):\n"
                + "\n".join(f"- {e.get('situacao')}: {str(e.get('estilo', '')).strip()}" for e in self.exemplos)
            )
        return "\n\n".join(partes)
