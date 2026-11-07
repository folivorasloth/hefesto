"""Palavra de ativação ("Hefesto") e botão de falar.

Três modos (config voz.ativacao.modo):

- "transcricao" (padrão): recorta cada fala com o VAD, transcreve com um
  Whisper pequeno e confere se começa com "Hefesto". Funciona já, sem treinar
  nada, e permite dizer tudo de uma vez ("Hefesto, onde fica a bobina?").
  Custo: CPU contínua enquanto alguém fala perto do microfone.
- "openwakeword": detector dedicado, bem mais leve. Precisa de um modelo da
  palavra "Hefesto" (o pacote só traz palavras em inglês); docs/MANUAL.md (voz) explica
  como treinar.
- "botao": aperte Enter e fale. Na garagem barulhenta é o mais confiável; na
  fase 6 o botão pode ser físico, no ESP32, via MQTT.

Todos expõem `esperar(quadros, continuar)`:
  None  -> nada detectado (continuar() ficou falso);
  ""    -> ativado, a pergunta vem na próxima fala;
  texto -> ativado e a pergunta já veio junto ("Hefesto, <texto>").
"""

from __future__ import annotations

import difflib
import queue
import threading
from typing import Callable, Iterator

import numpy as np

from engenheiro.recuperacao.reescrita import normalizar

from .vad import Recortador


def detectar_palavra(texto: str, palavra: str = "Hefesto", limiar: float = 0.75) -> tuple[bool, str]:
    """Confere se a fala começa com a palavra de ativação, tolerando os erros
    típicos de transcrição ("É festo", "Efesto", "Hefestos"). Devolve
    (ativou, resto da fala)."""
    alvo = normalizar(palavra).replace(" ", "")
    tokens = normalizar(texto).replace(",", " ").replace(".", " ").replace("!", " ").split()
    originais = texto.replace(",", " ").replace(".", " ").replace("!", " ").split()
    # Ignora um cumprimento na frente ("ei Hefesto", "ô Hefesto").
    inicio = 1 if tokens and tokens[0] in ("ei", "oi", "o", "ola", "e", "hey") and len(tokens) > 1 else 0
    for n in (1, 2):   # "Hefesto" ou "É festo" (duas palavras)
        candidato = "".join(tokens[inicio:inicio + n])
        if candidato and difflib.SequenceMatcher(None, candidato, alvo).ratio() >= limiar:
            return True, " ".join(originais[inicio + n:]).strip(" ,.!?") + ("?" if texto.rstrip().endswith("?") else "")
    return False, texto


class AtivacaoTranscricao:
    """`transcritor` (pequeno, rápido) só procura a palavra. Quando ela aparece
    junto com a pergunta, o MESMO áudio é transcrito de novo com o
    `transcritor_principal`: no teste real, o tiny transformou "tipo de
    ignição" em "tipo de denição"."""

    def __init__(self, recortador: Recortador, transcritor, palavra: str = "Hefesto", transcritor_principal=None) -> None:
        self.rec = recortador
        self.stt = transcritor
        self.stt_principal = transcritor_principal
        self.palavra = palavra
        self.ultima_transcricao = ""

    def esperar(self, quadros: Iterator[bytes], continuar: Callable[[], bool] = lambda: True) -> str | None:
        while continuar():
            fala = self.rec.proxima_fala(quadros, continuar=continuar)
            if fala is None:
                return None
            texto = self.stt.transcrever(fala)
            self.ultima_transcricao = texto
            ativou, resto = detectar_palavra(texto, self.palavra)
            if ativou:
                if resto.strip(" ?") and self.stt_principal is not None and self.stt_principal is not self.stt:
                    melhor = self.stt_principal.transcrever(fala)
                    ok, resto_melhor = detectar_palavra(melhor, self.palavra)
                    self.ultima_transcricao = melhor
                    resto = resto_melhor if ok else melhor
                return resto if resto.strip(" ?") else ""
        return None


class AtivacaoOpenWakeWord:
    """openWakeWord espera blocos de 80 ms (1280 amostras a 16 kHz)."""

    BLOCO = 1280

    def __init__(self, caminho_modelo: str, limiar: float = 0.5) -> None:
        if not caminho_modelo:
            raise ValueError("voz.ativacao.modelo_openwakeword vazio: treine o modelo de 'Hefesto' ou use modo 'transcricao'")
        from openwakeword.model import Model

        self.modelo = Model(wakeword_models=[caminho_modelo])
        self.limiar = limiar

    def esperar(self, quadros: Iterator[bytes], continuar: Callable[[], bool] = lambda: True) -> str | None:
        buf = np.zeros(0, dtype=np.int16)
        for q in quadros:
            if not continuar():
                return None
            buf = np.concatenate([buf, np.frombuffer(q, dtype=np.int16)])
            while len(buf) >= self.BLOCO:
                bloco, buf = buf[: self.BLOCO], buf[self.BLOCO:]
                if max(self.modelo.predict(bloco).values()) >= self.limiar:
                    self.modelo.reset()
                    return ""
        return None


class AtivacaoBotao:
    """Enter no terminal. A leitura do teclado roda numa thread para não travar
    o microfone (que precisa continuar sendo esvaziado)."""

    def __init__(self, ler=input) -> None:
        self._eventos: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._ouvir_teclado, args=(ler,), daemon=True).start()

    def _ouvir_teclado(self, ler) -> None:
        while True:
            try:
                ler()
            except EOFError:
                return
            self._eventos.put("")

    def esperar(self, quadros: Iterator[bytes], continuar: Callable[[], bool] = lambda: True) -> str | None:
        for _ in quadros:   # consome o microfone enquanto espera
            if not continuar():
                return None
            try:
                return self._eventos.get_nowait()
            except queue.Empty:
                continue
        return None
