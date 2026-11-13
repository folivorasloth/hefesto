"""O config.example.yaml é o manual das opções: ele precisa carregar e
listar TODA opção que o código conhece (senão a opção existe, mas ninguém
sabe dela)."""

from pathlib import Path

import yaml
from pydantic import BaseModel

from engenheiro.config import Config, carregar_config

RAIZ = Path(__file__).parents[1]


def _chaves(modelo: type[BaseModel], prefixo: str = "") -> set[str]:
    saida = set()
    for nome, campo in modelo.model_fields.items():
        if nome == "raiz":
            continue
        tipo = campo.annotation
        if isinstance(tipo, type) and issubclass(tipo, BaseModel):
            saida |= _chaves(tipo, f"{prefixo}{nome}.")
        else:
            saida.add(prefixo + nome)
    return saida


def _chaves_yaml(d: dict, prefixo: str = "") -> set[str]:
    saida = set()
    for k, v in d.items():
        if isinstance(v, dict):
            saida |= _chaves_yaml(v, f"{prefixo}{k}.")
        else:
            saida.add(prefixo + k)
    return saida


def test_exemplo_carrega_sem_erro():
    cfg = carregar_config(RAIZ / "config.example.yaml")
    assert cfg.assistente.id == "engenheiro" and cfg.busca.candidatos_rerank == 15


def test_exemplo_documenta_todas_as_opcoes():
    no_codigo = _chaves(Config)
    no_exemplo = _chaves_yaml(yaml.safe_load((RAIZ / "config.example.yaml").read_text(encoding="utf-8")))
    faltando = sorted(no_codigo - no_exemplo)
    sobrando = sorted(no_exemplo - no_codigo)
    assert not faltando, f"opções sem documentação no config.example.yaml: {faltando}"
    assert not sobrando, f"opções no exemplo que o código não conhece: {sobrando}"


def test_api_so_local_por_padrao():
    from engenheiro.config import Api

    assert Api().so_local()
    for h in ("localhost", "127.0.0.1", "127.0.1.1", "::1", "[::1]"):
        assert Api(host=h).so_local(), h
    for h in ("0.0.0.0", "::", "192.168.0.10", "homelab"):
        assert not Api(host=h).so_local(), h
