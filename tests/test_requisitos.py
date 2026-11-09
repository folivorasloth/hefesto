"""As versões travadas (requisitos/testados.txt) precisam cobrir toda
dependência declarada no pyproject.toml; senão a instalação "travada" deixa
pacotes soltos sem ninguém perceber."""

import re
import tomllib
from pathlib import Path

RAIZ = Path(__file__).parents[1]


def _nome(req: str) -> str:
    return re.split(r"[<>=!~\[; ]", req.strip(), maxsplit=1)[0].lower().replace("_", "-")


def test_toda_dependencia_tem_versao_travada():
    proj = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    deps = list(proj["dependencies"]) + [d for extra in proj["optional-dependencies"].values() for d in extra]
    travadas = {
        _nome(linha) for linha in (RAIZ / "requisitos" / "testados.txt").read_text(encoding="utf-8").splitlines()
        if "==" in linha and not linha.startswith("#")
    }
    faltando = sorted({_nome(d) for d in deps} - travadas)
    assert not faltando, f"sem versão travada em requisitos/testados.txt: {faltando}"


def test_python_minimo_coerente_com_os_testes_do_github():
    proj = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    minimo = proj["requires-python"].removeprefix(">=")
    ci = (RAIZ / ".github" / "workflows" / "testes.yml").read_text(encoding="utf-8")
    assert f'"{minimo}"' in ci, "o GitHub precisa testar a versão mínima declarada"
