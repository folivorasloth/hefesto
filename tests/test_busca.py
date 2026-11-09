from engenheiro.config import Config
from engenheiro.dev.embedder_falso import EmbedderFalso
from engenheiro.ingest.modelos import Trecho
from engenheiro.recuperacao.pipeline import Recuperador
from engenheiro.recuperacao.reescrita import Glossario, EntradaGlossario, gerar_variantes, rotear
from engenheiro.store.busca_hibrida import Acerto, consulta_fts, fundir_rrf, termos_tecnicos
from engenheiro.store.db import Banco, DadosDocumento


def _trecho(texto, secao="S"):
    return Trecho(texto, [secao], 1, 1, ["paragrafo"], ["texto"])


def _banco_com(trechos_por_colecao: dict[str, list[Trecho]], embedder=None) -> Banco:
    b = Banco(":memory:")
    for col, trechos in trechos_por_colecao.items():
        d = DadosDocumento(f"{col}/doc.pdf", col, "sha", "dig", f"Livro {col}", f"L-{col}")
        b.substituir_documento(d, trechos, ["pt"] * len(trechos))
    if embedder:
        pend = b.trechos_sem_embedding()
        vet = embedder.embed([r["texto"] for r in pend])
        b.preparar_vetores(embedder.nome, len(vet[0]))
        b.salvar_embeddings([(r["id"], r["colecao"], v) for r, v in zip(pend, vet)])
    return b


def test_consulta_fts_escapa_operadores_e_trata_codigos():
    q = consulta_fts('Qual peça 030-905-205 NEAR "NOT" no GPIO34?')
    assert '"030 905 205"' in q
    assert '"gpio34"' in q
    assert '"near"' in q and '"not"' in q  # viraram termos, não operadores
    assert consulta_fts("de da do") is None


def test_termos_tecnicos():
    assert termos_tecnicos("ligar no GPIO34 com LM2596 e peça 030-905-205") == ["GPIO34", "LM2596", "030-905-205"]


def test_gpio34_encontrado_pela_palavra_chave():
    b = _banco_com({
        "esp32": [_trecho("Use o GPIO34 como entrada analógica."), _trecho("O GPIO2 controla o LED da placa.")],
        "eletronica": [_trecho("Entradas analógicas em geral.")],
    })
    cfg = Config()
    rec = Recuperador(cfg, b, Glossario([]), embedder=None, reranker=None)
    res = rec.buscar("onde ligo o GPIO34?")
    assert "GPIO34" in res.finais[0].trecho.texto
    assert "bm25:original" in res.finais[0].listas


def test_codigo_de_peca_com_hifen():
    b = _banco_com({"veiculo": [_trecho("Relé código 030-905-205-X."), _trecho("Relé código 030-111-999.")]})
    res = Recuperador(Config(), b, Glossario([]), None, None).buscar("relé 030-905-205")
    assert "030-905-205" in res.finais[0].trecho.texto


def test_acentos_ignorados_na_busca():
    b = _banco_com({"ignicao": [_trecho("Verifique a ignição eletrônica.")]})
    res = Recuperador(Config(), b, Glossario([]), None, None).buscar("ignicao eletronica")
    assert res.finais


def test_filtro_por_colecao_no_bm25_e_no_vetor():
    emb = EmbedderFalso()
    b = _banco_com({"esp32": [_trecho("bobina de ignição")], "ignicao": [_trecho("bobina de ignição")]}, emb)
    res = Recuperador(Config(), b, Glossario([]), emb, None).buscar("bobina", colecoes=["ignicao"])
    assert {c.trecho.colecao for c in res.candidatos} == {"ignicao"}
    assert any(k.startswith("vetor:") for k in res.finais[0].listas)


def test_sem_embedder_avisa_e_continua():
    b = _banco_com({"veiculo": [_trecho("torque do cabeçote")]})
    res = Recuperador(Config(), b, Glossario([]), None, None).buscar("torque")
    assert res.finais
    assert any("palavra-chave" in a for a in res.avisos)
    assert any("Reranker desligado" in a for a in res.avisos)


def test_reranker_reordena():
    class RerankerInverte:
        nome = "teste"

        def pontuar(self, pergunta, textos):
            return [1.0 if "segundo" in t else 0.1 for t in textos]

    b = _banco_com({"veiculo": [_trecho("torque primeiro torque torque"), _trecho("torque segundo")]})
    res = Recuperador(Config(), b, Glossario([]), None, RerankerInverte()).buscar("torque")
    assert "segundo" in res.finais[0].trecho.texto
    assert res.finais[0].rerank == 1.0


def test_reranker_com_defeito_nao_zera_a_busca():
    class Quebrado:
        nome = "x"

        def pontuar(self, *a):
            raise RuntimeError("modelo não carregou")

    b = _banco_com({"veiculo": [_trecho("torque")]})
    res = Recuperador(Config(), b, Glossario([]), None, Quebrado()).buscar("torque")
    assert res.finais and any("Reranker falhou" in a for a in res.avisos)


def test_rrf_premia_quem_aparece_nas_duas_listas():
    listas = {
        "bm25": [Acerto(1, 1, 9.0), Acerto(2, 2, 5.0)],
        "vetor": [Acerto(3, 1, 0.9), Acerto(2, 2, 0.8)],
    }
    assert fundir_rrf(listas)[0][0] == 2


GLOSS = Glossario([
    EntradaGlossario(["bobina", "bobina de ignição"], ["ignition coil"], ["ignicao", "veiculo"]),
    EntradaGlossario(["afogador"], ["choke"], ["carburacao_etanol"]),
])


def test_variantes_com_glossario():
    v = {x.tipo: x.texto for x in gerar_variantes("Como testar a bobina?", GLOSS)}
    assert "ignition coil" in v["expandida"] and v["ingles"] == "ignition coil"


def test_glossario_casa_palavra_inteira_sem_acento():
    assert GLOSS.encontrar("AFOGADOR travado")
    assert not GLOSS.encontrar("bobinadeira")


def test_roteamento_sempre_inclui_veiculo_e_caderno():
    todas = Config().colecoes
    r = rotear("o afogador não fecha", GLOSS, todas, ["veiculo", "caderno_de_bordo"], "palavras_chave")
    assert set(r.colecoes) == {"carburacao_etanol", "veiculo", "caderno_de_bordo"}


def test_roteamento_sem_pista_busca_em_todas():
    todas = Config().colecoes
    r = rotear("pergunta qualquer", GLOSS, todas, ["veiculo"], "palavras_chave")
    assert r.colecoes == todas


def test_reranker_usa_a_consulta_no_idioma_de_cada_trecho():
    class Espiao:
        nome = "espiao"

        def __init__(self):
            self.chamadas = []

        def pontuar(self, consulta, textos):
            self.chamadas.append((consulta, len(textos)))
            return [0.5] * len(textos)

    b = Banco(":memory:")
    d = DadosDocumento("ignicao/l.pdf", "ignicao", "s", "d", "L", "L")
    b.substituir_documento(d, [_trecho("bobina de ignição"), _trecho("ignition coil test")], ["pt", "en"])
    rr = Espiao()
    res = Recuperador(Config(), b, Glossario([]), None, rr).buscar(
        "bobina ignition", consultas_rerank={"original": "bobina?", "llm_ingles": "coil?"})
    assert sorted(rr.chamadas) == [("bobina?", 1), ("coil?", 1)]      # cada trecho avaliado UMA vez
    por_trecho = {c.trecho.idioma: c.rerank_por_consulta for c in res.candidatos}
    assert por_trecho == {"pt": {"original": 0.5}, "en": {"llm_ingles": 0.5}}
