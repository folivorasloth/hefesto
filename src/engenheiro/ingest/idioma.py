"""Detecção de idioma dos trechos (a base mistura português e inglês)."""

from __future__ import annotations

from functools import lru_cache

from lingua import Language, LanguageDetectorBuilder

_CODIGOS = {Language.PORTUGUESE: "pt", Language.ENGLISH: "en", Language.SPANISH: "es"}


@lru_cache(maxsize=1)
def _detector():
    # Restringir a 3 idiomas deixa a detecção bem mais precisa em textos
    # técnicos curtos, cheios de siglas e números.
    return LanguageDetectorBuilder.from_languages(*_CODIGOS).build()


def detectar(texto: str) -> str:
    texto = texto[:2000]
    if len(texto.strip()) < 20:
        return "desconhecido"
    lang = _detector().detect_language_of(texto)
    return _CODIGOS.get(lang, "desconhecido") if lang else "desconhecido"
