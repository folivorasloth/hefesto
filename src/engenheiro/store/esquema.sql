-- Esquema do índice. A tabela vetorial (trechos_vec) é criada pelo código,
-- porque a dimensão depende do modelo de embeddings.

CREATE TABLE IF NOT EXISTS meta (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY,
    caminho TEXT NOT NULL UNIQUE,        -- relativo à pasta da biblioteca
    colecao TEXT NOT NULL,
    sha256 TEXT NOT NULL,                -- hash do arquivo (indexação incremental)
    impressao_digital TEXT NOT NULL,     -- hash + config que afeta o resultado
    livro TEXT NOT NULL,                 -- título completo
    citacao TEXT NOT NULL,               -- nome curto usado em [Livro, p. X]
    autor TEXT,
    edicao TEXT,
    idioma TEXT,
    -- página impressa = página do PDF - deslocamento. NULL = desconhecido;
    -- nesse caso a citação mostra a página do PDF e diz isso explicitamente.
    deslocamento_paginas INTEGER,
    n_paginas INTEGER,
    paginas_ocr TEXT,                    -- JSON com as páginas que vieram de OCR
    indexado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trechos (
    id INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL,
    colecao TEXT NOT NULL,
    texto TEXT NOT NULL,
    secao TEXT NOT NULL,                 -- "Cap. > Seção > Subseção"
    pagina_inicio INTEGER NOT NULL,      -- páginas do PDF
    pagina_fim INTEGER NOT NULL,
    idioma TEXT,
    tipos TEXT NOT NULL,                 -- JSON: ["tabela", "procedimento", "aviso", ...]
    origens TEXT NOT NULL,               -- JSON: ["texto"] / ["ocr"] / ["visao"]
    oversize INTEGER NOT NULL DEFAULT 0,
    figuras TEXT NOT NULL DEFAULT '[]',
    tem_embedding INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_trechos_doc ON trechos(documento_id);
CREATE INDEX IF NOT EXISTS idx_trechos_pendentes ON trechos(tem_embedding);

-- Busca por palavra-chave. remove_diacritics: "ignição" casa com "ignicao".
-- O tokenizer padrão mantém "GPIO34" como um token só; códigos com hífen
-- ("030-905-205") viram uma busca por frase (tokens adjacentes).
-- rowid = trechos.id.
CREATE VIRTUAL TABLE IF NOT EXISTS trechos_fts USING fts5(
    texto, secao,
    tokenize = "unicode61 remove_diacritics 2"
);
