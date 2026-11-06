"""Gravação do rastro de auditoria em JSON.

Na fase 1 o rastro cobre a busca. As fases seguintes acrescentam geração,
ferramentas e verificador no mesmo arquivo, sob chaves próprias.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from engenheiro.eventos import Barramento


def novo_id() -> str:
    agora = datetime.now(timezone.utc)
    return agora.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def salvar(pasta: Path, id_rastro: str, conteudo: dict, barramento: Barramento | None = None) -> Path:
    data = id_rastro[:8]
    destino = pasta / data[:4] / data[4:6] / f"{id_rastro}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    corpo = {"id": id_rastro, **conteudo}
    if barramento is not None:
        corpo["eventos"] = [e.para_dict() for e in barramento.eventos]
    destino.write_text(json.dumps(corpo, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return destino


def carregar(pasta: Path, id_rastro: str) -> dict:
    data = id_rastro[:8]
    return json.loads((pasta / data[:4] / data[4:6] / f"{id_rastro}.json").read_text(encoding="utf-8"))
