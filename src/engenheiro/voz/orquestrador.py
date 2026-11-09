"""Loop de voz do Hefesto.

    ESPERANDO ──(palavra/botão)──► OUVINDO ──► PENSANDO (mumbling) ──► FALANDO
        ▲                                                             │
        │       ◄── janela de resposta: se ele fez uma pergunta, ─────┤
        │           ouve de novo SEM precisar dizer "Hefesto"         │
        └──────────── interrupção: "Hefesto" ou botão durante a fala ◄┘

Modo dirigindo: nada de mumbling e respostas não são faladas (ficam
guardadas e são lidas quando você diz "parei"); só ALERTAS CRÍTICOS falam.
Alerta crítico = problema crítico do verificador e, na fase 6, alertas da
telemetria (método `alertar`).

Limitação conhecida: sem cancelamento de eco, a interrupção é pela palavra
de ativação ou pelo botão, não por "qualquer voz", senão a própria fala do
Hefesto, captada pelo microfone, o interromperia.
"""

from __future__ import annotations

import queue
import re
import threading
from typing import Callable

from engenheiro.recuperacao.reescrita import normalizar

_RE_DIRIGINDO_ON = re.compile(r"\b(modo dirigindo|vou dirigir|to dirigindo|estou dirigindo)\b")
_RE_DIRIGINDO_OFF = re.compile(r"\b(parei|sai do modo dirigindo|sair do modo dirigindo|desativa o modo dirigindo|cheguei)\b")
_RE_NOVA = re.compile(r"\b(nova conversa|outro assunto|esquece isso)\b")


class LoopVoz:
    def __init__(self, conversador, microfone, falante, sintetizador, transcritor, ativacao, recortador, cfg_voz,
                 dirigindo: bool = False, mostrar: Callable[[str, str], None] | None = None) -> None:
        self.conv = conversador
        self.mic = microfone
        self.falante = falante
        self.sint = sintetizador
        self.stt = transcritor
        self.ativacao = ativacao
        self.rec = recortador
        self.cfg = cfg_voz
        self.dirigindo = dirigindo
        self.mostrar = mostrar or (lambda quem, texto: None)
        self.guardadas: list[str] = []          # respostas segurando no modo dirigindo
        self._murmurios: queue.Queue[str] = queue.Queue()
        self.mumbler = None
        if cfg_voz.mumbling:
            from .mumbling import Mumbler

            self.mumbler = Mumbler(self._murmurios.put, cfg_voz.intervalo_minimo_mumbling_s)
            self.conv.eng.bus.assinar(self.mumbler)

    def receber_murmurio(self, texto: str) -> None:
        """Mumbling vindo de fora (ex.: do servidor, pelo MQTT, no modo remoto)."""
        if texto and self.cfg.mumbling and not self.dirigindo:
            self._murmurios.put(texto)

    # ------------------------------------------------------------ fala
    def falar(self, texto: str, volume: float | None = None, continuar: Callable[[], bool] = lambda: True) -> bool:
        """Fala frase a frase. False = interrompida."""
        vol = self.cfg.volume if volume is None else volume
        for audio, taxa in self.sint.frases(texto):
            if not continuar() or not self.falante.tocar(audio, taxa, vol):
                return False
        return True

    def falar_interrompivel(self, texto: str, quadros) -> tuple[bool, str | None]:
        """Fala numa thread enquanto a ativação escuta o microfone. Se você disser
        "Hefesto" (ou apertar o botão), ele para. Devolve (interrompido, resto)."""
        terminou = threading.Event()
        cancelado = threading.Event()

        def _fala():
            self.falar(texto, continuar=lambda: not cancelado.is_set())
            terminou.set()

        t = threading.Thread(target=_fala, daemon=True)
        t.start()
        resto = self.ativacao.esperar(quadros, continuar=lambda: not terminou.is_set())
        if resto is not None and not terminou.is_set():
            cancelado.set()
            self.falante.parar()
            t.join(timeout=2)
            return True, resto
        t.join()
        return False, None

    def alertar(self, texto: str) -> None:
        """Alerta crítico: fala SEMPRE, inclusive no modo dirigindo (fase 6: telemetria)."""
        self.mostrar("alerta", texto)
        self.falar("Atenção. " + texto)

    # ------------------------------------------------------------ comandos de voz
    def _comando(self, fala: str) -> str | None:
        n = normalizar(fala)
        if _RE_DIRIGINDO_ON.search(n):
            self.dirigindo = True
            if self.mumbler:
                self.mumbler.ativo = False
            return "Modo dirigindo ligado. Fico quieto; só falo se for crítico. Diga parei quando quiser as respostas."
        if _RE_DIRIGINDO_OFF.search(n) and self.dirigindo:
            self.dirigindo = False
            if self.mumbler:
                self.mumbler.ativo = True
            if not self.guardadas:
                return "Modo dirigindo desligado."
            texto = "Modo dirigindo desligado. Você tinha perguntado algumas coisas. " + " ".join(self.guardadas)
            self.guardadas = []
            return texto
        if _RE_NOVA.search(n):
            self.conv.nova_conversa()
            return "Certo, assunto novo."
        return None

    # ------------------------------------------------------------ um atendimento
    def atender(self, pergunta: str, quadros) -> None:
        while pergunta:
            self.mostrar("voce", pergunta)
            comando = self._comando(pergunta)
            if comando:
                self.mostrar("hefesto", comando)
                self.falar(comando)
                return

            self._esvaziar_murmurios()
            resultado: list = []
            erro: list = []

            def _trabalho(p=pergunta):
                try:
                    resultado.append(self.conv.turno(p))
                except Exception as e:  # noqa: BLE001 - um erro num turno não pode derrubar o loop de voz
                    erro.append(e)

            t = threading.Thread(target=_trabalho, daemon=True)
            t.start()
            while t.is_alive():                       # PENSANDO: fala o mumbling enquanto espera
                try:
                    m = self._murmurios.get(timeout=0.2)
                except queue.Empty:
                    continue
                if not self.dirigindo:
                    self.falar(m, self.cfg.volume_mumbling)
            t.join()
            self._esvaziar_murmurios()
            if erro:
                msg = "Tive um erro interno ao montar a resposta. Os detalhes estão na tela."
                self.mostrar("alerta", f"Erro interno: {erro[0]!r}")
                self.falar(msg)
                return
            resp = resultado[0]
            self.mostrar("hefesto", resp.texto)

            if self.dirigindo:
                for p in resp.problemas_criticos:
                    self.alertar(p)
                self.guardadas.append(resp.fala)
                return

            self._descartar_microfone()
            interrompido, resto = self.falar_interrompivel(resp.fala, quadros)
            if interrompido:
                pergunta = resto or self._ouvir(quadros, self.cfg.janela_resposta_s)
                continue
            if resp.espera_resposta:
                # Ele perguntou algo: ouve a resposta sem exigir "Hefesto", e usa a
                # própria pergunta como contexto para a transcrição.
                contexto = resp.fala[-300:] + (" Sim. Não. Pode anotar." if resp.propostas else "")
                pergunta = self._ouvir(quadros, self.cfg.janela_resposta_s, contexto)
                continue
            return

    def _ouvir(self, quadros, timeout_s: float, contexto: str = "") -> str:
        self._descartar_microfone()
        fala = self.rec.proxima_fala(quadros, timeout_s=timeout_s)
        if not fala:
            return ""
        try:
            return self.stt.transcrever(fala, contexto)
        except TypeError:   # transcritor sem suporte a contexto (ex.: testes)
            return self.stt.transcrever(fala)

    def _descartar_microfone(self) -> None:
        # Enquanto ele pensava ou falava, o microfone continuou gravando:
        # esse áudio velho não pode virar "a sua próxima fala".
        descartar = getattr(self.mic, "descartar", None)
        if descartar:
            descartar()

    def _esvaziar_murmurios(self) -> None:
        while not self._murmurios.empty():
            self._murmurios.get_nowait()

    # ------------------------------------------------------------ loop principal
    def rodar(self, parar: Callable[[], bool] = lambda: False) -> None:
        quadros = self.mic.quadros()
        while not parar():
            resto = self.ativacao.esperar(quadros)
            if resto is None:
                continue
            if not resto:
                self.falar("Pois não?")
                resto = self._ouvir(quadros, self.cfg.janela_resposta_s)
            if resto:
                self.atender(resto, quadros)
