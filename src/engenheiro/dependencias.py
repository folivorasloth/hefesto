"""Mensagem clara quando falta uma dependência opcional (extra do pip)."""

from __future__ import annotations

import importlib


class DependenciaFaltando(ImportError):
    pass


def exigir(modulo: str, extra: str, para: str) -> None:
    """Falha com o comando exato de instalação, em vez de um ModuleNotFoundError cru."""
    try:
        importlib.import_module(modulo)
    except ImportError as e:
        raise DependenciaFaltando(
            f"{para} precisa do pacote '{modulo}', que não está instalado. "
            f"Instale com:  pip install -e \".[{extra}]\""
        ) from e
