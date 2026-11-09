"""Gera um corpus de PDFs FICTÍCIOS para testar a ingestão e a busca.

ATENÇÃO: todo o conteúdo destes PDFs é inventado. Os valores numéricos são
propositalmente estranhos (ex.: torque "17,3 N·m") e cada página traz o aviso
"TEXTO DE TESTE". Eles servem só para conferir se o pipeline acha a seção
certa, nunca como referência técnica. Por isso mesmo eles vão para uma pasta
separada (padrão: data/teste/), não para data/biblioteca/.

Cada PDF exercita um caso que o chunker precisa tratar:
- tabela que não pode ser cortada;
- procedimento numerado longo, que atravessa quebra de página;
- aviso de segurança que deve ficar grudado no procedimento que ele precede;
- texto em inglês (para a busca multilíngue);
- termo técnico exato (GPIO34, código de peça) para a busca por palavra-chave;
- página "escaneada" (só imagem, sem camada de texto) para o OCR.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

AVISO_TESTE = "TEXTO DE TESTE - conteúdo fictício, não usar como referência"


def _rodape(canvas, doc):
    # Rodapé em toda página: deixa claro que é fictício e serve para testar
    # se o extrator descarta cabeçalhos/rodapés (eles poluiriam os trechos).
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.drawString(2 * cm, 1 * cm, f"{AVISO_TESTE} - pág. {doc.page}")
    canvas.restoreState()


def _estilos():
    s = getSampleStyleSheet()
    return s["Title"], s["Heading1"], s["Heading2"], s["BodyText"]


def _paragrafos_enchimento(n: int, tema: str, corpo, ingles: bool = False) -> list:
    """Texto genérico para encher seções e forçar quebras de página/trecho."""
    if ingles:
        frase = (
            f"This filler paragraph talks about {tema} in a generic way, without any "
            "technical value, only to give volume to the test document. "
        )
    else:
        frase = (
            f"Este parágrafo de enchimento fala sobre {tema} de forma genérica, "
            "sem nenhum valor técnico, apenas para dar volume ao documento de teste "
            "e obrigar o divisor de trechos a trabalhar com seções longas. "
        )
    return [Paragraph(frase * 3, corpo) for _ in range(n)]


def gerar_manual_veiculo(destino: Path) -> Path:
    titulo, h1, h2, corpo = _estilos()
    caminho = destino / "veiculo" / "manual_ficticio_gol.pdf"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(caminho), pagesize=A4, title="Manual Fictício do Veículo")
    el: list = [
        Paragraph("Manual Fictício do Veículo de Teste", titulo),
        Paragraph(AVISO_TESTE, corpo),
        Paragraph("1 Motor", h1),
        Paragraph("1.1 Torques de aperto do cabeçote", h2),
        Paragraph("A tabela abaixo lista os torques fictícios de aperto do cabeçote.", corpo),
    ]
    tabela = Table(
        [
            ["Etapa", "Parafusos", "Torque (fictício)"],
            ["1", "Todos, em espiral", "17,3 N·m"],
            ["2", "Todos, em espiral", "41,7 N·m"],
            ["3", "Todos", "+ 93 graus"],
            ["4", "Todos", "+ 93 graus"],
        ]
    )
    tabela.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black")]))
    el += [tabela, Spacer(1, 12)]
    el += _paragrafos_enchimento(3, "o motor", corpo)
    el += [
        Paragraph("1.2 Regulagem da marcha lenta", h2),
        Paragraph(
            "ATENÇÃO: trabalhe em local ventilado. Os gases do escapamento são tóxicos "
            "e há risco de incêndio perto do combustível.",
            corpo,
        ),
    ]
    passos = [
        "Aqueça o motor até a temperatura normal de trabalho.",
        "Desligue os consumidores elétricos (faróis, ventilador, rádio).",
        "Conecte o tacômetro de teste ao terminal negativo da bobina.",
        "Localize o parafuso de ajuste da marcha lenta no carburador fictício.",
        "Gire o parafuso até a rotação fictícia de 911 rpm.",
        "Ajuste o parafuso de mistura até a rotação máxima estável.",
        "Repita o passo 5 para voltar a 911 rpm.",
        "Confira a rotação com o eletroventilador ligado.",
        "Desconecte o tacômetro de teste.",
        "Registre o resultado no caderno de bordo.",
    ]
    # Passos longos de propósito: o procedimento inteiro passa do tamanho
    # máximo de trecho, e o chunker deve mantê-lo inteiro mesmo assim.
    el.append(
        ListFlowable(
            [ListItem(Paragraph(p + " " + "Detalhe fictício adicional. " * 6, corpo)) for p in passos],
            bulletType="1",
        )
    )
    el += [PageBreak(), Paragraph("2 Sistema elétrico", h1)]
    el += [
        Paragraph("2.1 Peças de reposição", h2),
        Paragraph(
            "O relé fictício da bomba tem o código de peça 030-905-205-X e "
            "fica na caixa de fusíveis do lado esquerdo.",
            corpo,
        ),
    ]
    el += _paragrafos_enchimento(4, "a parte elétrica", corpo)
    doc.build(el, onFirstPage=_rodape, onLaterPages=_rodape)
    return caminho


def gerar_livro_ignicao_ingles(destino: Path) -> Path:
    titulo, h1, h2, corpo = _estilos()
    caminho = destino / "ignicao" / "fictional_ignition_book.pdf"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(caminho), pagesize=A4, title="Fictional Ignition Systems")
    el = [
        Paragraph("Fictional Ignition Systems", titulo),
        Paragraph("TEST TEXT - fictional content, do not use as reference", corpo),
        Paragraph("3 Electronic ignition", h1),
        Paragraph("3.1 Hall effect sensor in the distributor", h2),
        Paragraph(
            "A Hall effect sensor inside the distributor produces a square wave. "
            "Each window of the rotating shutter vane switches the sensor output. "
            "The control module uses this signal to trigger the ignition coil.",
            corpo,
        ),
        Paragraph("3.2 Checking the ignition coil", h2),
        Paragraph(
            "Measure the primary winding resistance of the ignition coil with an ohmmeter. "
            "The fictional value for this test is 0.77 ohm.",
            corpo,
        ),
    ]
    el += _paragrafos_enchimento(2, "ignition", corpo, ingles=True)
    doc.build(el, onFirstPage=_rodape, onLaterPages=_rodape)
    return caminho


def gerar_doc_esp32(destino: Path) -> Path:
    titulo, h1, h2, corpo = _estilos()
    caminho = destino / "esp32" / "notas_ficticias_esp32.pdf"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(caminho), pagesize=A4, title="Notas Fictícias ESP32")
    el = [
        Paragraph("Notas Fictícias sobre o ESP32", titulo),
        Paragraph(AVISO_TESTE, corpo),
        Paragraph("4 Entradas analógicas", h1),
        Paragraph(
            "O pino GPIO34 é usado neste texto de teste como entrada analógica do "
            "sensor fictício de temperatura. Ele não tem resistor de pull-up interno.",
            corpo,
        ),
    ]
    el += _paragrafos_enchimento(2, "o microcontrolador", corpo)
    doc.build(el, onFirstPage=_rodape, onLaterPages=_rodape)
    return caminho


def gerar_pdf_escaneado(destino: Path) -> Path:
    """PDF só com imagem (sem camada de texto), simulando um livro escaneado."""
    from PIL import Image as PILImage
    from PIL import ImageDraw, ImageFont

    caminho = destino / "carburacao_etanol" / "apostila_escaneada_ficticia.pdf"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.new("RGB", (1654, 2339), "white")  # A4 a 200 dpi
    d = ImageDraw.Draw(img)
    try:
        fonte = ImageFont.truetype("DejaVuSans.ttf", 42)
        fonte_t = ImageFont.truetype("DejaVuSans-Bold.ttf", 60)
    except OSError:  # sem a fonte no sistema: usa a padrão (OCR fica pior)
        fonte = fonte_t = ImageFont.load_default()
    d.text((120, 150), "Apostila Ficticia de Carburacao", font=fonte_t, fill="black")
    linhas = [
        "TEXTO DE TESTE - conteudo ficticio",
        "",
        "Giclê principal do carburador ficticio:",
        "o diametro de teste e 1,37 mm.",
        "A boia controla o nivel da cuba.",
    ]
    for i, linha in enumerate(linhas):
        d.text((120, 320 + i * 70), linha, font=fonte, fill="black")
    tmp_png = caminho.with_suffix(".png")
    img.save(tmp_png)
    # Desenha a imagem direto no canvas: o PDF fica sem nenhuma camada de texto.
    from reportlab.pdfgen.canvas import Canvas

    cv = Canvas(str(caminho), pagesize=A4)
    cv.drawImage(str(tmp_png), 0, 0, width=A4[0], height=A4[1])
    cv.showPage()
    cv.save()
    tmp_png.unlink()
    return caminho


def gerar_corpus(destino: Path, incluir_escaneado: bool = True) -> list[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    arquivos = [
        gerar_manual_veiculo(destino),
        gerar_livro_ignicao_ingles(destino),
        gerar_doc_esp32(destino),
    ]
    if incluir_escaneado:
        arquivos.append(gerar_pdf_escaneado(destino))
    return arquivos
