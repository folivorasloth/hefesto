# Hefesto: o Engenheiro

Assistente pessoal de engenharia (mecânica, elétrica automotiva, ESP32) para o
projeto de telemetria de um VW Gol CL 1994 1.6 AP a etanol, carburado.

**Correção acima de tudo.** O assistente só afirma o que consegue mostrar
numa fonte (`[Livro, p. X]`), faz as contas com ferramentas (nunca "de cabeça")
e diz "não encontrei" quando a base não tem a resposta. Toda resposta gera um
rastro JSON auditável.

O identificador técnico é `engenheiro`; o nome exibido fica em `config.yaml`
(`assistente.nome`).

## Estado das fases

| Fase | Conteúdo | Estado |
|---|---|---|
| 1 | Ingestão (Docling + OCR), corte por seção, índice híbrido (BM25 + vetores), reranker, CLI de busca, avaliação de recuperação | **pronta** |
| 2 | Respostas com citações + verificador | — |
| 3 | Ferramentas de cálculo, tabela de pinos do ESP32, perfil do veículo, caderno de bordo | — |
| 4 | Avaliação completa (fatos-chave, citações, "não sei") | parcial (recuperação já mede) |
| 5 | Voz e mumbling | — |
| 6 | API HTTP e MQTT | — |

## Como funciona (fase 1)

```
PDF ──Docling──► blocos (título/parágrafo/lista/tabela/figura, com página)
                   │   OCR (Tesseract por+eng) nas páginas sem camada de texto
                   ▼
              chunker: corta por seção; nunca corta tabela nem procedimento
                   │  numerado; aviso (ATENÇÃO...) gruda no procedimento seguinte
                   ▼
   SQLite ─┬─ FTS5 (BM25, sem acento; acha GPIO34, 030-905-205...)
           └─ sqlite-vec (bge-m3 via Ollama, cosseno, particionado por coleção)

pergunta ─► variantes (original, expandida pelo glossário, termos em inglês)
         ─► roteamento (coleções do glossário + veiculo + caderno_de_bordo)
         ─► BM25 e vetor por variante ─► fusão RRF ─► reranker bge-reranker-v2-m3
         ─► 5 a 8 trechos finais, com o score de cada etapa
```

As decisões e os porquês estão comentados no código. Os pontos principais:

- **SQLite (FTS5 + sqlite-vec) em vez de Qdrant.** O bge-m3 pelo Ollama só dá
  o vetor denso, então o BM25 seria feito por fora de qualquer jeito. Além
  disso, é um arquivo só, fácil de copiar e auditar.
- **Página do PDF ≠ página impressa.** As citações mostram "p. 67 do PDF" até
  você informar o `deslocamento_paginas` na ficha do livro (ver abaixo).
- **Origem do texto.** Trechos de OCR e descrições de figura por modelo de
  visão são marcados como tal e aparecem com aviso.
- **Degradação explícita.** Sem Ollama, a busca segue só por palavra-chave e
  avisa. Sem reranker, vale a ordem RRF e avisa. Nunca há falha silenciosa.

## Máquinas

O engenheiro **não roda no homelab**. Ele roda numa das suas máquinas e fala
com o Ollama pela rede. Nenhum endereço fica no código: tudo vem do `config.yaml`
ou da variável `OLLAMA_HOST`.

### Notebook do LLM (i7 10ª, 16 GB, sem GPU)

1. Instale o Ollama: <https://ollama.com/download/linux>.
2. Para aceitar conexões da rede local, configure o serviço com
   `OLLAMA_HOST=0.0.0.0` (`sudo systemctl edit ollama` e adicione
   `Environment="OLLAMA_HOST=0.0.0.0"` em `[Service]`). Sugiro também
   `Environment="OLLAMA_MAX_LOADED_MODELS=1"` para não estourar os 16 GB.
3. Baixe os modelos:

```bash
ollama pull bge-m3
```

```bash
ollama pull qwen3:14b
```

```bash
ollama pull qwen3:4b
```

```bash
ollama pull qwen2.5vl:7b
```

`bge-m3` é o único necessário na fase 1. O `qwen2.5vl:7b` só é usado se você
ligar a descrição de figuras. Os nomes são sugestões e podem ser trocados no
`config.yaml`; a escolha final entre modelos deve sair da avaliação.

### Máquina onde o engenheiro roda (notebook pessoal ou o próprio notebook do LLM)

Requer Python 3.11+ e o Tesseract com o pacote de português:

```bash
sudo apt install tesseract-ocr tesseract-ocr-por tesseract-ocr-eng
```

```bash
git clone https://github.com/folivorasloth/hefesto && cd hefesto
```

```bash
python3 -m venv .venv && . .venv/bin/activate
```

```bash
pip install -e ".[ingestao,reranker,dev]"
```

```bash
cp config.example.yaml config.yaml
```

Edite o `config.yaml`, ou apenas exporte o endereço do notebook do LLM
(troque pelo nome ou IP da sua máquina):

```bash
export OLLAMA_HOST=notebook-llm.local:11434
```

```bash
engenheiro status
```

Na primeira indexação, o Docling baixa os modelos de layout e tabela (~500 MB)
e o reranker baixa o `bge-reranker-v2-m3` (~2,2 GB), os dois do Hugging Face.
Depois disso tudo roda offline.

**RAM:** o Docling, o reranker e um modelo de 14B juntos não cabem com folga
em 16 GB. Se tudo rodar no mesmo notebook, indexe à noite sem conversar com o
modelo forte ao mesmo tempo.

## Adicionando livros à base

1. Coloque o PDF na pasta da coleção certa, dentro de `data/biblioteca/`.
   Essa pasta fica fora do git.

   ```
   data/biblioteca/
     veiculo/  carburacao_etanol/  ignicao/  eletrica_automotiva/  eletronica/
     mecanica_motor/  sensores/  esp32/  aquisicao_dados/  caderno_de_bordo/
   ```

2. (Recomendado) Crie a ficha do livro, um `.yaml` com o mesmo nome do PDF:

   ```yaml
   # data/biblioteca/eletrica_automotiva/denton_automobile_electrical.yaml
   titulo: "Automobile Electrical and Electronic Systems"
   citacao: "Denton"           # nome curto usado em [Denton, p. 45]
   autor: "Tom Denton"
   edicao: 5
   idioma: en
   # Página impressa = página do PDF - deslocamento. Para descobrir, abra o
   # PDF numa página numerada: se a folha 67 do PDF mostra "45", use 22.
   deslocamento_paginas: 22
   ```

3. Indexe. Só o que mudou é processado, e pode rodar em lote à noite:

   ```bash
   engenheiro indexar
   ```

   Se o Ollama estiver desligado, o texto entra no índice mesmo assim (a busca
   por palavra-chave já funciona) e os embeddings são gerados na próxima vez
   que você rodar `engenheiro indexar` com ele ligado. Arquivo apagado da
   pasta sai do índice. Mudou só a ficha? Os trechos são refeitos sem repetir
   a extração, que fica em cache.

4. Busque:

   ```bash
   engenheiro buscar "qual o torque do cabeçote do AP?"
   ```

   Opções úteis: `--candidatos` (mostra todos antes do reranking), `--completo`,
   `--json`, `--rastro` (grava em `data/rastros/`), `--colecao esp32`,
   `--sem-rerank`.

Arquivos `.md`/`.txt` também são aceitos (títulos `#` viram seções). É assim
que o caderno de bordo vai entrar na fase 3.

Para descrever figuras com o modelo de visão, ligue
`ingestao.figuras.descrever_com_visao` no `config.yaml`. Em CPU, cada figura
leva de 30 a 90 s. As descrições entram marcadas como **não verificadas**.

## Testando sem os seus livros

O comando abaixo gera PDFs **fictícios** (valores inventados, marcados como
"TEXTO DE TESTE"): uma tabela de torque, um procedimento que atravessa página,
um aviso de segurança, um livro em inglês, um código de peça, o GPIO34 e uma
página escaneada.

```bash
engenheiro corpus-teste
```

```bash
engenheiro indexar --biblioteca data/teste --indice data/teste.sqlite
```

```bash
engenheiro buscar --indice data/teste.sqlite "como regular a marcha lenta?"
```

```bash
engenheiro avaliar --perguntas eval/perguntas_corpus_teste.yaml --indice data/teste.sqlite
```

Sem o Ollama, acrescente `--embedder-falso` ao `indexar`, ao `buscar` e ao
`avaliar`. É um embedder de mentira (hash de palavras), só para testar o
encanamento. O índice grava qual embedder usou e se recusa a misturar dois
embedders diferentes.

## Avaliação

`eval/perguntas.yaml` é o seu conjunto de perguntas. Ele vem com modelos
desativados; preencha com perguntas reais depois de indexar os livros. Rode:

```bash
engenheiro avaliar
```

O relatório (`eval/relatorios/*.md` e `.json`) mostra:

- acerto@k e MRR;
- acerto nas perguntas críticas;
- quantas fontes certas foram recuperadas, mas o reranker cortou;
- o score do reranker nos acertos e nas perguntas fora da base;
- a comparação com a execução anterior: o que melhorou e **o que piorou**,
  pergunta por pergunta.

## Testes

```bash
pytest
```

Esse comando roda os testes rápidos: chunker, busca, citações, indexação
incremental, CLI e avaliação. Os lentos ficam separados:

```bash
pytest -m docling
```

```bash
pytest -m reranker
```

O primeiro roda o Docling e o OCR de verdade sobre o corpus fictício (é o
critério de aceite da fase 1). O segundo usa o reranker real.
