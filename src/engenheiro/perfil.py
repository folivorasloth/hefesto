"""Perfil do veículo (perfil_veiculo.yaml).

Duas responsabilidades:
1. montar o texto que entra no prompt, separando CONFIRMADO de SUPOSIÇÃO de
   forma que o modelo não tenha como confundir;
2. atualizar campos pela CLI, registrando no histórico quem mudou o quê,
   quando e com qual fonte (rastreabilidade também para o perfil).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

STATUS = {"confirmado", "suposicao", "a_confirmar"}


class PerfilInvalido(ValueError):
    pass


def _campos(dados: dict) -> list[tuple[str, dict]]:
    saida = []
    for grupo, conteudo in dados.items():
        if grupo in ("restricoes", "historico") or not isinstance(conteudo, dict):
            continue
        for nome, campo in conteudo.items():
            if isinstance(campo, dict) and "status" in campo:
                saida.append((f"{grupo}.{nome}", campo))
    return saida


class Perfil:
    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        self.dados: dict = yaml.safe_load(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
        self.validar()

    def validar(self) -> None:
        erros = []
        for chave, c in _campos(self.dados):
            if c.get("status") not in STATUS:
                erros.append(f"{chave}: status '{c.get('status')}' inválido ({sorted(STATUS)})")
            if c.get("status") == "confirmado" and not c.get("fonte"):
                erros.append(f"{chave}: confirmado sem fonte")
        if erros:
            raise PerfilInvalido("Perfil do veículo com problemas:\n- " + "\n- ".join(erros))

    def campo(self, chave: str) -> dict | None:
        grupo, _, nome = chave.partition(".")
        return (self.dados.get(grupo) or {}).get(nome)

    def valor_confirmado(self, chave: str) -> Any:
        """Valor só se confirmado; senão None. Usado pelas ferramentas: uma
        suposição nunca vira parâmetro de cálculo sem você saber."""
        c = self.campo(chave)
        return c.get("valor") if c and c.get("status") == "confirmado" else None

    def valores_confirmados(self) -> str:
        """Só os VALORES confirmados (sem observações): é a única parte do
        perfil aceita como origem de números pelo verificador. O texto
        completo tem observações como "1a, 2a..." que fariam qualquer "2"
        da resposta parecer ter origem."""
        return "\n".join(f"{k}: {c['valor']}" for k, c in _campos(self.dados) if c["status"] == "confirmado")

    def para_prompt(self) -> str:
        conf, sup, falta = [], [], []
        for chave, c in _campos(self.dados):
            obs = f" ({c['observacao']})" if c.get("observacao") else ""
            if c["status"] == "confirmado":
                conf.append(f"- {chave}: {c['valor']}")
            elif c["status"] == "suposicao":
                sup.append(f"- {chave}: {c['valor']}{obs}")
            else:
                falta.append(f"- {chave}{obs}")
        partes = ["PERFIL DO VEÍCULO DO USUÁRIO"]
        partes.append("CONFIRMADO (pode usar como fato):\n" + ("\n".join(conf) or "- nada"))
        partes.append(
            "SUPOSIÇÃO (NÃO é fato: se a resposta depender disto, diga que é suposição e como confirmar):\n"
            + ("\n".join(sup) or "- nada")
        )
        partes.append("DESCONHECIDO (não invente; se precisar, diga como descobrir):\n" + ("\n".join(falta) or "- nada"))
        if self.dados.get("restricoes"):
            partes.append("RESTRIÇÕES ABSOLUTAS:\n" + "\n".join(f"- {r}" for r in self.dados["restricoes"]))
        return "\n\n".join(partes)

    def definir(self, chave: str, valor: Any, status: str, fonte: str | None, observacao: str | None = None) -> dict:
        if status not in STATUS:
            raise PerfilInvalido(f"status inválido: {status} ({sorted(STATUS)})")
        if status == "confirmado" and not fonte:
            raise PerfilInvalido("para marcar como confirmado, diga a fonte (--fonte)")
        grupo, _, nome = chave.partition(".")
        if not nome:
            raise PerfilInvalido("use o formato grupo.campo, ex.: carburador.modelo")
        antes = dict(self.campo(chave) or {})
        novo = {"valor": valor, "status": status, "fonte": fonte}
        if observacao is not None:
            novo["observacao"] = observacao
        elif antes.get("observacao") and status != "confirmado":
            novo["observacao"] = antes["observacao"]
        self.dados.setdefault(grupo, {})[nome] = novo
        self.dados.setdefault("historico", []).append({
            "quando": datetime.now().isoformat(timespec="seconds"),
            "campo": chave, "antes": antes or None, "depois": novo,
        })
        self.validar()
        # Preserva o bloco de comentários do topo (instruções de uso), que o
        # yaml.safe_dump descartaria.
        cabecalho = ""
        if self.caminho.exists():
            linhas = self.caminho.read_text(encoding="utf-8").splitlines(keepends=True)
            for linha in linhas:
                if linha.startswith("#") or not linha.strip():
                    cabecalho += linha
                else:
                    break
        self.caminho.write_text(
            cabecalho + yaml.safe_dump(self.dados, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8"
        )
        return novo
