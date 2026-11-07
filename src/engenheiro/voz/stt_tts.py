"""Transcrição (faster-whisper) e síntese de fala (Piper), ambos locais."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .texto import dividir_em_frases, normalizar_para_fala

# Vocabulário passado ao Whisper como contexto: melhora muito o
# reconhecimento de nomes que ele não conhece ("Hefesto" virava "É festo").
VOCABULARIO = ("Hefesto, Gol, AP, carburador, Weber, giclê, afogador, distribuidor, bobina, sensor Hall, "
               "ignição, etanol, ESP32, GPIO, multímetro, optoacoplador, divisor de tensão.")


class Transcritor:
    def __init__(self, modelo: str = "small", dispositivo: str = "cpu", compute_type: str = "int8",
                 vocabulario: str = VOCABULARIO) -> None:
        from engenheiro.dependencias import exigir

        exigir("faster_whisper", "voz", "A transcrição de voz")
        from faster_whisper import WhisperModel

        self.modelo = WhisperModel(modelo, device=dispositivo, compute_type=compute_type)
        self.vocabulario = vocabulario

    def transcrever(self, pcm16: bytes | np.ndarray, contexto: str = "") -> str:
        """`contexto`: o que o Hefesto acabou de perguntar. Respostas curtas
        ("sim", "três fios") são as mais difíceis; saber a pergunta ajuda o
        Whisper a acertar (no teste, "sim" virava "Tchim")."""
        audio = np.frombuffer(pcm16, dtype=np.int16) if isinstance(pcm16, (bytes, bytearray)) else pcm16
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        prompt = f"{self.vocabulario} {contexto}".strip()
        segmentos, _ = self.modelo.transcribe(audio, language="pt", initial_prompt=prompt,
                                              vad_filter=True, beam_size=5, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segmentos).strip()


class Sintetizador:
    def __init__(self, caminho_voz: Path, velocidade: float = 1.0) -> None:
        from engenheiro.dependencias import exigir

        exigir("piper", "voz", "A fala do Hefesto")
        from piper import PiperVoice
        from piper.config import SynthesisConfig

        if not Path(caminho_voz).exists():
            raise FileNotFoundError(
                f"Voz do Piper não encontrada em {caminho_voz}. Baixe com:\n"
                f"  python -m piper.download_voices --download-dir {Path(caminho_voz).parent} pt_BR-faber-medium"
            )
        self.voz = PiperVoice.load(str(caminho_voz))
        self.config = SynthesisConfig(length_scale=velocidade)

    def frases(self, texto: str):
        """Gera (áudio int16, taxa) frase a frase, para começar a falar logo."""
        for frase in dividir_em_frases(normalizar_para_fala(texto)):
            pedacos = list(self.voz.synthesize(frase, self.config))
            if pedacos:
                yield np.concatenate([p.audio_int16_array for p in pedacos]), pedacos[0].sample_rate
