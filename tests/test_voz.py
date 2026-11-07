"""Fase 5: voz. Peças puras + loop com áudio falso; teste real em `pytest -m voz`."""

import os
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from engenheiro.config import Voz
from engenheiro.conversa import RespostaTurno
from engenheiro.eventos import Barramento, Evento
from engenheiro.geracao.gerador import Afirmacao, RespostaGerada
from engenheiro.geracao.montagem import montar_fala
from engenheiro.seguranca import AvisoTema
from engenheiro.verificador.verificador import Verificacao
from engenheiro.voz.ativacao import detectar_palavra
from engenheiro.voz.mumbling import Mumbler
from engenheiro.voz.orquestrador import LoopVoz
from engenheiro.voz.texto import dividir_em_frases, normalizar_para_fala
from engenheiro.voz.vad import Recortador


# ------------------------------------------------------------------ texto para fala
def test_unidades_viram_palavras():
    t = normalizar_para_fala("Medi 12,6 V e 150 mA no GPIO34 [Denton, p. 45]; de 3 a 5 vezes.")
    assert "12,6 volts" in t and "150 miliampères" in t and "G P I O 34" in t
    assert "[" not in t and "de 3 a 5 vezes" in t     # "a" minúsculo não vira ampère
    assert "17,3 newton-metro" in normalizar_para_fala("17,3 N·m")


def test_frases_curtas():
    frases = dividir_em_frases("Primeira frase. " + "palavra, " * 60 + "fim.")
    assert frases[0] == "Primeira frase." and all(len(f) <= 221 for f in frases)


# ------------------------------------------------------------------ palavra de ativação
@pytest.mark.parametrize("texto, ativou, resto", [
    ("Hefesto, onde fica a bobina?", True, "onde fica a bobina?"),
    ("Efesto, como o identifica o tipo de ignição do meu Gol?", True, "como o identifica o tipo de ignição do meu Gol?"),
    ("É festo, tudo bem", True, "tudo bem"),
    ("ei Hefesto", True, ""),
    ("vamos embora daqui", False, "vamos embora daqui"),
    ("o festival foi bom", False, "o festival foi bom"),
])
def test_detectar_palavra(texto, ativou, resto):
    assert detectar_palavra(texto) == (ativou, resto)


# ------------------------------------------------------------------ VAD
class DetectorFalso:
    """Fala onde o byte do quadro é 1."""

    def is_speech(self, quadro, taxa):
        return quadro[0] == 1


def _q(seq):
    return iter(bytes([b]) * 960 for b in seq)


def test_recorta_fala_com_margem_e_silencio_final():
    rec = Recortador(silencio_fim_ms=90, quadros_para_comecar=2, margem_inicio_ms=60, detector=DetectorFalso())
    fala = rec.proxima_fala(_q([0, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1]))
    # margem de 2 quadros (60 ms) antes + fala + 3 de silêncio (90 ms)
    assert len(fala) // 960 == 2 + 1 + 3


def test_batida_curta_nao_dispara():
    rec = Recortador(quadros_para_comecar=3, detector=DetectorFalso())
    assert rec.proxima_fala(_q([1, 0, 1, 0, 0, 0]), timeout_s=0.15) is None


def test_janela_de_resposta_expira():
    rec = Recortador(detector=DetectorFalso())
    assert rec.proxima_fala(_q([0] * 100), timeout_s=0.3) is None


# ------------------------------------------------------------------ mumbling
def test_mumbling_vem_de_eventos_reais_com_dados_reais():
    ditas = []
    relogio = iter([0, 10, 20, 21, 30, 40])
    m = Mumbler(ditas.append, intervalo_minimo_s=4, relogio=lambda: next(relogio))
    m(Evento("busca.roteamento", {"colecoes": ["veiculo", "ignicao", "caderno_de_bordo"], "motivo": "", "termos": []}))
    m(Evento("busca.final", {"trechos": [{"id": 1, "livro": "Denton", "rerank": 0.9}, {"id": 2, "livro": "Denton", "rerank": 0.8}]}))
    m(Evento("ferramenta.chamada", {"id": "F1", "nome": "divisor_tensao", "argumentos": {}, "saida": {}, "erro": None}))
    m(Evento("ferramenta.chamada", {"id": "F2", "nome": "lei_de_ohm", "argumentos": {}, "saida": {}, "erro": None}))  # 1 s depois: descartada
    m(Evento("geracao.concluida", {"afirmacoes": 2, "encontrou": True}))   # sem frase
    m(Evento("verificacao.iniciada", {"afirmacoes": 2}))
    assert ditas == [
        "Deixa eu ver nos manuais do Gol e na parte de ignição...",
        "Achei 2 trechos, no Denton...",
        "conferindo esse divisor de tensão...",
        "Conferindo a resposta com as fontes...",
    ]


def test_mumbling_desligado_fica_quieto():
    ditas = []
    m = Mumbler(ditas.append)
    m.ativo = False
    m(Evento("web.busca", {"motivo": "x", "resultados": 3}))
    assert ditas == []


# ------------------------------------------------------------------ versão falada
def _ctx(id_, cit):
    return SimpleNamespace(id=id_, citacao=cit, texto="x", origens=["texto"])


def test_fala_poe_critico_primeiro_e_pergunta_por_ultimo():
    r = RespostaGerada(True, [
        Afirmacao("A1", "O torque é 17,3 N·m.", "fonte", ["T1"], True, "fonte"),
        Afirmacao("A2", "Valor inventado.", "fonte", ["T1"], True, "fonte", status="removida"),
        Afirmacao("A3", "Olhe o conector.", "geral", [], False, "geral"),
    ], "", [], "Quantos fios você vê?", [_ctx("T1", "[Denton, pp. 45–46]")], [], "", "m", {})
    v = Verificacao(r.afirmacoes, ["Afirmação crítica NÃO verificada: X"], executada=True)
    seg = [AvisoTema("ignicao", "bobina", ["Não toque na bobina ligada.", "Segundo aviso."])]
    fala = montar_fala(r, v, seg)
    assert fala.startswith("Atenção antes de tudo:")
    assert "Segundo Denton, páginas 45 a 46." in fala
    assert "Valor inventado" not in fala and "Tirei da resposta" in fala
    assert "Sem fonte, só para te orientar: Olhe o conector." in fala
    assert "Não toque na bobina ligada." in fala and "Segundo aviso." not in fala   # só o 1º aviso é falado
    assert fala.endswith("Quantos fios você vê?")
    assert "Não toque" not in montar_fala(r, v, seg, temas_ja_avisados={"ignicao"})


# ------------------------------------------------------------------ loop com áudio falso
class SintFalso:
    def __init__(self):
        self.ditos = []

    def frases(self, texto):
        self.ditos.append(texto)
        yield np.zeros(10, dtype=np.int16), 16000


class FalanteFalso:
    tocando = False

    def __init__(self):
        self.volumes = []

    def tocar(self, audio, taxa, volume=1.0):
        self.volumes.append(volume)
        return True

    def parar(self):
        pass


class AtivacaoFalsa:
    """Durante a fala do Hefesto (continuar=...), não interrompe."""

    def esperar(self, quadros, continuar=lambda: True):
        while continuar():
            pass
        return None


class ConversadorFalso:
    def __init__(self, respostas, eventos_por_turno=(), pensar_s=0.0):
        self.pensar_s = pensar_s
        self.respostas = list(respostas)
        self.eventos = list(eventos_por_turno)
        self.perguntas = []
        self.eng = SimpleNamespace(bus=Barramento())
        self.sessao = None

    def turno(self, fala):
        self.perguntas.append(fala)
        for ev in self.eventos:
            self.eng.bus.publicar(ev[0], **ev[1])
        if self.pensar_s:
            import time

            time.sleep(self.pensar_s)   # o modelo "pensando": é quando o mumbling é falado
        return self.respostas.pop(0)


def _loop(conv, falas_ouvidas, dirigindo=False, mumbling=False):
    cfg = Voz(mumbling=mumbling, intervalo_minimo_mumbling_s=0)
    stt = SimpleNamespace(transcrever=lambda pcm: falas_ouvidas.pop(0))
    rec = SimpleNamespace(proxima_fala=lambda quadros, timeout_s=None, continuar=None: b"x" if falas_ouvidas else None)
    sint = SintFalso()
    falante = FalanteFalso()
    loop = LoopVoz(conv, SimpleNamespace(quadros=lambda: iter(()), descartar=lambda: None), falante, sint, stt,
                   AtivacaoFalsa(), rec, cfg, dirigindo=dirigindo)
    return loop, sint, falante


def test_conversa_guiada_por_voz_sem_repetir_palavra_de_ativacao():
    conv = ConversadorFalso([
        RespostaTurno("t1", fala="Olhe o distribuidor. Quantos fios entram no conector?", espera_resposta=True),
        RespostaTurno("t2", fala="Quer que eu anote no perfil? Diga sim ou não.", espera_resposta=True),
        RespostaTurno("t3", fala="Anotado."),
    ])
    loop, sint, _ = _loop(conv, ["tem três fios", "sim"])
    loop.atender("como eu identifico o tipo de ignição?", iter(()))
    assert conv.perguntas == ["como eu identifico o tipo de ignição?", "tem três fios", "sim"]
    assert sint.ditos == [r.fala for r in [
        RespostaTurno("", fala="Olhe o distribuidor. Quantos fios entram no conector?"),
        RespostaTurno("", fala="Quer que eu anote no perfil? Diga sim ou não."),
        RespostaTurno("", fala="Anotado.")]]


def test_mumbling_falado_mais_baixo_enquanto_pensa():
    ev = [("busca.roteamento", {"colecoes": ["ignicao"], "motivo": "", "termos": []})]
    conv = ConversadorFalso([RespostaTurno("t", fala="Resposta.")], eventos_por_turno=ev, pensar_s=0.5)
    loop, sint, falante = _loop(conv, [], mumbling=True)
    loop.atender("onde fica a bobina?", iter(()))
    assert sint.ditos == ["Deixa eu ver na parte de ignição...", "Resposta."]
    assert falante.volumes[0] == Voz().volume_mumbling and falante.volumes[1] == Voz().volume


def test_modo_dirigindo_guarda_respostas_e_so_fala_critico():
    conv = ConversadorFalso([
        RespostaTurno("t", fala="Resposta longa."),
        RespostaTurno("t", fala="Outra.", problemas_criticos=["Tensão sem fonte."]),
    ])
    loop, sint, _ = _loop(conv, [])
    loop.atender("modo dirigindo", iter(()))
    assert loop.dirigindo and "Modo dirigindo ligado" in sint.ditos[-1]
    loop.atender("qual a pressão do pneu?", iter(()))
    loop.atender("e a tensão da bobina?", iter(()))
    assert sint.ditos[-1] == "Atenção. Tensão sem fonte."         # só o crítico foi falado
    loop.atender("parei", iter(()))
    assert "Resposta longa." in sint.ditos[-1] and "Outra." in sint.ditos[-1]
    assert not loop.dirigindo


def test_interrupcao_pela_palavra_de_ativacao():
    class AtivacaoQueInterrompe:
        def esperar(self, quadros, continuar=lambda: True):
            return "pare, outra pergunta"

    class FalanteLento(FalanteFalso):
        def __init__(self):
            super().__init__()
            self.parado = threading.Event()

        def tocar(self, audio, taxa, volume=1.0):
            return not self.parado.wait(1.0)

        def parar(self):
            self.parado.set()

    conv = ConversadorFalso([RespostaTurno("t", fala="Uma resposta muito longa."), RespostaTurno("t", fala="Ok.")])
    loop, _, _ = _loop(conv, [])
    loop.falante = FalanteLento()
    loop.ativacao = AtivacaoQueInterrompe()
    interrompido, resto = loop.falar_interrompivel("Uma resposta muito longa.", iter(()))
    assert interrompido and resto == "pare, outra pergunta" and loop.falante.parado.is_set()


# ------------------------------------------------------------------ real (Piper + VAD + Whisper)
VOZ = Path(os.environ.get("HEFESTO_VOZ_TESTE", "data/vozes/pt_BR-faber-medium.onnx"))


@pytest.mark.voz
@pytest.mark.skipif(not VOZ.exists(), reason="voz do Piper não baixada (HEFESTO_VOZ_TESTE)")
def test_ida_e_volta_real():
    import scipy.signal as ss

    from engenheiro.voz.stt_tts import Sintetizador, Transcritor

    sint = Sintetizador(VOZ)
    partes = [ss.resample_poly(a.astype(np.float32), 16000, sr) for a, sr in sint.frases("Hefesto, onde fica a bobina de ignição?")]
    silencio = np.zeros(16000, dtype=np.int16)
    audio = np.concatenate([silencio, np.concatenate(partes).astype(np.int16), silencio, silencio])
    quadros = (audio[i:i + 480].tobytes() for i in range(0, len(audio) - 480, 480))
    fala = Recortador().proxima_fala(quadros)
    texto = Transcritor("tiny").transcrever(fala)
    ativou, resto = detectar_palavra(texto)
    assert ativou and "bobina" in resto.lower()


def test_erro_no_turno_nao_derruba_o_loop():
    class Quebrado(ConversadorFalso):
        def turno(self, fala):
            raise RuntimeError("banco caiu")

    loop, sint, _ = _loop(Quebrado([]), [])
    mostrados = []
    loop.mostrar = lambda quem, t: mostrados.append((quem, t))
    loop.atender("onde fica a bobina?", iter(()))
    assert "erro interno" in sint.ditos[-1] and any(q == "alerta" and "banco caiu" in t for q, t in mostrados)


def test_banco_pode_ser_usado_por_outra_thread(tmp_path):
    from engenheiro.store.db import Banco

    b = Banco(tmp_path / "i.sqlite")
    erros = []
    t = threading.Thread(target=lambda: erros.append(None) if b.estatisticas() else None)
    t.start()
    t.join()
    assert erros == [None]


def test_pergunta_e_retranscrita_com_o_modelo_principal():
    from engenheiro.voz.ativacao import AtivacaoTranscricao

    rec = SimpleNamespace(proxima_fala=lambda quadros, continuar=None: b"audio")
    pequeno = SimpleNamespace(transcrever=lambda a: "Efesto, como o identifica o tipo de denição?")
    principal = SimpleNamespace(transcrever=lambda a: "Hefesto, como eu identifico o tipo de ignição?")
    ativ = AtivacaoTranscricao(rec, pequeno, "Hefesto", transcritor_principal=principal)
    assert ativ.esperar(iter(())) == "como eu identifico o tipo de ignição?"
