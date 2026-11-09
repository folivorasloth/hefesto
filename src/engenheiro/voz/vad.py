"""Detecção de fala (VAD): recorta uma fala do fluxo do microfone.

Usa o webrtcvad, que é leve e roda bem em CPU. A garagem é barulhenta: a
agressividade (0 a 3) ajusta o quanto ruído é ignorado, e uma fala só começa
depois de alguns quadros seguidos de voz (evita disparar com uma batida).
"""

from __future__ import annotations

from collections import deque
from typing import Iterator

from .audio import QUADRO_MS, TAXA


class Recortador:
    def __init__(self, agressividade: int = 2, silencio_fim_ms: int = 900, duracao_max_s: float = 20.0,
                 quadros_para_comecar: int = 5, margem_inicio_ms: int = 300, detector=None) -> None:
        if detector is None:
            import webrtcvad

            detector = webrtcvad.Vad(agressividade)
        self.vad = detector
        self.quadros_silencio_fim = max(1, silencio_fim_ms // QUADRO_MS)
        self.max_quadros = int(duracao_max_s * 1000 / QUADRO_MS)
        self.quadros_para_comecar = quadros_para_comecar
        self.margem = max(1, margem_inicio_ms // QUADRO_MS)

    def eh_fala(self, quadro: bytes) -> bool:
        return self.vad.is_speech(quadro, TAXA)

    def proxima_fala(self, quadros: Iterator[bytes], timeout_s: float | None = None,
                     continuar=lambda: True) -> bytes | None:
        """Bloqueia até uma fala completa (do começo ao silêncio final) e a
        devolve em PCM int16. Com `timeout_s`, desiste se ninguém começar a
        falar nesse tempo (usado na janela de resposta)."""
        antes: deque[bytes] = deque(maxlen=self.margem)  # um pouco de áudio antes do início, para não cortar a 1ª sílaba
        seguidos = 0
        falando = False
        fala: list[bytes] = []
        silencio = 0
        esperados = None if timeout_s is None else int(timeout_s * 1000 / QUADRO_MS)
        for n, q in enumerate(quadros):
            if not continuar():
                return None
            voz = self.eh_fala(q)
            if not falando:
                antes.append(q)
                seguidos = seguidos + 1 if voz else 0
                if seguidos >= self.quadros_para_comecar:
                    falando = True
                    fala = list(antes)
                elif esperados is not None and n >= esperados:
                    return None
                continue
            fala.append(q)
            silencio = 0 if voz else silencio + 1
            if silencio >= self.quadros_silencio_fim or len(fala) >= self.max_quadros:
                return b"".join(fala)
        return b"".join(fala) if falando else None
