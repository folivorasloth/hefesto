"""Busca na web pelo SearXNG (e só por ele).

Tudo o que vem daqui é marcado como NÃO VERIFICADO: entra numa seção
própria da resposta, com o link, e nunca é apresentado como fonte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx


class WebIndisponivel(RuntimeError):
    pass


@dataclass
class ResultadoWeb:
    id: str            # "W1", "W2"...
    titulo: str
    url: str
    trecho: str
    origens: list[str] = field(default_factory=lambda: ["web"])

    @property
    def dominio(self) -> str:
        return urlparse(self.url).netloc

    @property
    def citacao(self) -> str:
        return f"[web: {self.dominio}]"

    @property
    def texto(self) -> str:
        return f"{self.titulo}\n{self.trecho}"

    def para_prompt(self) -> str:
        return f"[{self.id}] WEB NÃO VERIFICADA | {self.titulo} | {self.url}\n{self.trecho}"


def buscar(url_searxng: str, consulta: str, maximo: int = 5, idioma: str = "pt-BR", timeout_s: float = 20) -> list[ResultadoWeb]:
    """Requer `search.formats: [html, json]` no settings.yml do SearXNG
    (ver docker/searxng/)."""
    if not url_searxng:
        raise WebIndisponivel("web.searxng_url não configurado no config.yaml")
    try:
        r = httpx.get(f"{url_searxng.rstrip('/')}/search",
                      params={"q": consulta, "format": "json", "language": idioma}, timeout=timeout_s)
    except httpx.HTTPError as e:
        raise WebIndisponivel(f"SearXNG inacessível em {url_searxng}: {e}") from e
    if r.status_code == 403:
        raise WebIndisponivel("SearXNG recusou o formato JSON: habilite 'json' em search.formats no settings.yml")
    r.raise_for_status()
    saida = []
    for item in r.json().get("results", [])[:maximo]:
        saida.append(ResultadoWeb(f"W{len(saida) + 1}", item.get("title", "").strip(), item.get("url", ""),
                                  (item.get("content") or "").strip()))
    return saida
