"""Atalho: `python eval/avaliar.py [opções]` == `engenheiro avaliar [opções]`."""

from engenheiro.interfaces.cli import app

if __name__ == "__main__":
    app(["avaliar", *__import__("sys").argv[1:]])
