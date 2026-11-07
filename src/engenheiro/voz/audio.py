"""Entrada e saída de áudio (microfone e alto-falante).

Formato interno único: mono, 16 kHz, int16, em quadros de 30 ms (480
amostras). É o que o webrtcvad, o openWakeWord e o Whisper esperam, então
não há conversão no meio do caminho.

Interfaces pequenas (`Microfone`, `AltoFalante`) para os testes usarem
versões falsas, sem placa de som.
"""

from __future__ import annotations

import queue
import threading
from typing import Iterator, Protocol

import numpy as np

TAXA = 16_000
QUADRO_MS = 30
AMOSTRAS_QUADRO = TAXA * QUADRO_MS // 1000   # 480


class Microfone(Protocol):
    def quadros(self) -> Iterator[bytes]: ...          # quadros de 30 ms, int16 mono 16 kHz
    def fechar(self) -> None: ...


class AltoFalante(Protocol):
    def tocar(self, audio: np.ndarray, taxa: int, volume: float = 1.0) -> bool: ...   # False = interrompido
    def parar(self) -> None: ...
    @property
    def tocando(self) -> bool: ...


class MicrofoneSD:
    """Microfone real via sounddevice (PortAudio)."""

    def __init__(self, dispositivo: int | str | None = None) -> None:
        from engenheiro.dependencias import exigir

        exigir("sounddevice", "voz", "O microfone")
        import sounddevice as sd

        self._fila: queue.Queue[bytes] = queue.Queue(maxsize=500)
        self._stream = sd.RawInputStream(samplerate=TAXA, blocksize=AMOSTRAS_QUADRO, channels=1, dtype="int16",
                                         device=dispositivo, callback=self._cb)
        self._stream.start()

    def _cb(self, dados, n, tempo, status) -> None:  # noqa: ARG002 - assinatura do PortAudio
        try:
            self._fila.put_nowait(bytes(dados))
        except queue.Full:
            pass  # processamento atrasado: perder um quadro é melhor que travar o áudio

    def quadros(self) -> Iterator[bytes]:
        while True:
            yield self._fila.get()

    def descartar(self) -> None:
        """Joga fora o áudio acumulado (gravado enquanto o Hefesto pensava/falava)."""
        while not self._fila.empty():
            try:
                self._fila.get_nowait()
            except queue.Empty:
                break

    def fechar(self) -> None:
        self._stream.stop()
        self._stream.close()


class AltoFalanteSD:
    """Alto-falante real, interrompível: tocar() roda em blocos curtos e
    para assim que parar() é chamado (de outra thread)."""

    def __init__(self, dispositivo: int | str | None = None) -> None:
        self.dispositivo = dispositivo
        self._parar = threading.Event()
        self._tocando = threading.Event()

    @property
    def tocando(self) -> bool:
        return self._tocando.is_set()

    def parar(self) -> None:
        self._parar.set()

    def tocar(self, audio: np.ndarray, taxa: int, volume: float = 1.0) -> bool:
        import sounddevice as sd

        self._parar.clear()
        self._tocando.set()
        dados = np.clip(audio.astype(np.float32) * volume, -32768, 32767).astype(np.int16)
        bloco = taxa // 10   # 100 ms: latência de interrupção baixa
        try:
            with sd.OutputStream(samplerate=taxa, channels=1, dtype="int16", device=self.dispositivo) as out:
                for i in range(0, len(dados), bloco):
                    if self._parar.is_set():
                        return False
                    out.write(dados[i:i + bloco])
            return True
        finally:
            self._tocando.clear()
