# Hefesto: o Engenheiro

Assistente pessoal de engenharia (mecânica, elétrica automotiva, ESP32) para o
projeto de telemetria de um VW Gol CL 1994 1.6 AP a etanol, carburado.

**Correção acima de tudo.** O assistente só afirma o que consegue mostrar
numa fonte (`[Livro, p. X]`), faz as contas com ferramentas (nunca "de cabeça")
e diz "não encontrei" quando a base não tem a resposta. Toda resposta gera um
rastro JSON auditável.

O identificador técnico é `engenheiro`. Nome, tom e exemplos ficam em
`persona/engenheiro.yaml`.

## Estado das fases

| Fase | Conteúdo | Estado |
|---|---|---|
| 1 | Ingestão (Docling + OCR), corte por seção, índice híbrido (BM25 + vetores), reranker, CLI de busca, avaliação de recuperação | **pronta** |
| 2 | Respostas com citações + verificador, segurança determinística, persona, rastro completo | **pronta** (validar com o seu Ollama) |
| 3 | Ferramentas de cálculo, tabela de pinos do ESP32, perfil do veículo, caderno de bordo, busca web (SearXNG) | **pronta** (validar com o seu Ollama) |
| 4 | Avaliação completa (fatos-chave, citações, "não sei") | parcial (modos `recuperacao` e `resposta` já existem) |
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

## Perguntando (fase 2)

```bash
engenheiro perguntar "como regular a marcha lenta?"
```

```bash
engenheiro rastro 20261106T214532Z-9b06d1
```

O primeiro comando mostra cada etapa enquanto acontece e, no fim, a resposta
e o id do rastro. O segundo mostra o rastro: candidatos com scores, o que
passou no limiar, o veredito de cada afirmação e a resposta final. Use
`--json` para ver tudo, inclusive os prompts exatos e as saídas brutas dos
modelos.

### Como a resposta é montada

1. **Modelo:** conversa (cumprimento, agradecimento) vai para o modelo rápido,
   sem busca e proibido de dar dado técnico. Todo o resto vai para o **forte**.
   A regra é por palavras, auditável no rastro: na dúvida, forte.
2. **Tradução:** o modelo rápido traduz a pergunta para o inglês técnico. A
   tradução vira mais uma busca, e o reranker pontua cada trecho pela pergunta
   original e pela tradução, ficando com o maior score.
3. **Limiar:** trechos abaixo de `busca.limiar_relevancia` não vão para o
   modelo. Se nenhum passar, ele diz que não encontrou e sugere onde procurar
   ou o que medir.
4. **Geração estruturada:** o modelo forte devolve JSON (o Ollama força o
   esquema), com cada afirmação separada, marcada como `fonte` ou
   `inferencia` e ligada aos ids dos trechos (`T1`, `T2`...).
5. **Verificador:** o código descarta citações a trechos inexistentes. Um
   segundo prompt no modelo forte confere cada afirmação contra os trechos
   citados. O código marca números que não aparecem na fonte citada nem na
   sua pergunta. As regras de decisão estão em
   `src/engenheiro/verificador/verificador.py`:

   | Situação | Resultado |
   |---|---|
   | Afirmação reprovada | Removida e listada à parte, com o motivo |
   | Suporte parcial | Vira inferência |
   | Número sem origem | Vira inferência, com ⚠ |
   | Verificador fora do ar | Nada conta como aprovado |
   | Problema em afirmação crítica (tensão, corrente, torque, combustível, bateria, ignição, segurança) | Aparece no **topo** da resposta |

6. **Segurança:** os avisos vêm de `dados_ref/seguranca.yaml`, disparados por
   palavras da pergunta, da resposta e dos trechos usados. Não dependem do
   modelo lembrar.
7. **Montagem:** o código troca `T1` por `[Livro, p. X]` a partir dos
   metadados do trecho. O modelo nunca escreve a citação, então não consegue
   inventar uma.

A resposta tem seções separadas: **Das fontes**, **Inferência**, **Não
encontrei nas fontes**, **Sugestões**, **Segurança** e **Removidas pelo
verificador**.

Sem o Ollama, ele não responde de memória: diz que está sem o modelo e lista
onde estão os trechos relevantes.

### Calibrando o limiar de relevância

O `limiar_relevancia: 0.10` é provisório. Depois de indexar seus livros e
preencher `eval/perguntas.yaml` (inclua perguntas cuja resposta NÃO está na
base), rode:

```bash
engenheiro avaliar
```

Compare `score_rerank_min_dos_acertos` com `score_rerank_max_fora_da_base` e
ponha o limiar entre os dois, mais perto do segundo. Errar para baixo só
manda um trecho a mais para o modelo (e o verificador ainda confere). Errar
para cima faz ele dizer "não encontrei" quando a resposta estava lá.

### Validando a fase 2 com o modelo real

```bash
engenheiro avaliar --modo resposta --perguntas eval/perguntas_corpus_teste.yaml --indice data/teste.sqlite
```

O relatório mede:

- `nao_sei_correto`: disse "não encontrei" quando a informação não estava na base?
- `falso_nao_sei`: disse "não encontrei" quando a informação estava lá?
- `fonte_aprovada`: das afirmações exibidas como fonte, quantas o verificador
  aprovou. Deve ser 1.0.
- `fatos_chave`: os fatos esperados aparecem na resposta?
- `respostas_com_problema_critico`;
- o tempo médio por resposta.

Cada linha do relatório tem o id do rastro para você auditar.

**Tempo:** cada pergunta técnica faz três chamadas ao modelo (tradução no
rápido, geração e verificação no forte). Num i7 sem GPU com um modelo de 14B,
conte alguns minutos por resposta. Para o `qwen3`, `geracao.pensar: false` no
config deixa bem mais rápido; `true` pode raciocinar melhor. Compare os dois
pela avaliação.

## Ferramentas, perfil, caderno e web (fase 3)

### Toda conta passa por ferramenta

Antes de responder, o modelo forte tem uma etapa só para chamar
ferramentas. Cada chamada vira uma fonte citável (`[cálculo: lei_de_ohm]`) e
fica no rastro com as entradas e as saídas. Um número que não veio de um
trecho, de uma ferramenta, da sua pergunta ou de um valor **confirmado** do
perfil é marcado como suspeito, mesmo que a conta esteja certa.

| Ferramenta | O que faz |
|---|---|
| `lei_de_ohm`, `potencia` | V, I, R e P (dois valores dados, o resto calculado) |
| `divisor_tensao` | Saída nominal e de pior caso pela tolerância dos resistores |
| `escolher_divisor` | Escolhe R1/R2 **entre os resistores do seu inventário** |
| `queda_tensao_fio` | Em mm² ou AWG, com retorno pelo chassi ou ida e volta, com temperatura |
| `dimensionar_fusivel` | Fusível de lâmina padrão (regra prática, marcada como tal) e conferência com o fio |
| `filtro_rc` | Frequência de corte e constante de tempo |
| `converter_unidade` | Conversões com `pint` (kgf·m, N·m, psi, bar, °C...) |
| `verificar_pinos_esp32` | Alertas da sua placa: só entrada, strapping, flash, ADC2 com Wi-Fi, UART |
| `rotacao_por_pulsos` | Hz do sinal de ignição ↔ rpm (4 cilindros, 4 tempos = 2 faíscas por volta) |
| `velocidade_por_rotacao` | km/h pela rotação, relações e medida do pneu |
| `lambda_afr` | λ ↔ AFR. Recusa calcular sem a estequiometria **confirmada com fonte** |
| `consultar_inventario` | O que você tem na bancada |
| `buscar_caderno` | O que você já fez ou mediu |
| `ler_telemetria` | Preparada para a fase 6 (MQTT do carro); por enquanto avisa que não existe |

Cada ferramenta também roda direto pela CLI, sem LLM:

```bash
engenheiro ferramenta
```

```bash
engenheiro ferramenta divisor_tensao vin_v=14.4 r1_ohm=47000 r2_ohm=10000 vout_max_permitido_v=3.3
```

```bash
engenheiro ferramenta verificar_pinos_esp32 pinos='[G34, G12]' uso=saida_digital
```

O primeiro comando lista as ferramentas e seus argumentos; os outros dois
são exemplos de uso.

As constantes ficam em `dados_ref/constantes.yaml`, cada uma com a sua fonte
(cobre IACS, definição do AWG, valores de fusível). A tabela de pinos fica em
`dados_ref/esp32_pinos.yaml`, marcada como "conferir com o datasheet" até
você indexar o datasheet da Espressif.

**Estequiometria do etanol:** o arquivo `dados_ref/combustiveis.yaml` vem
**sem valores, de propósito**. O etanol da bomba é hidratado e a gasolina
brasileira tem etanol misturado, então o número "de livro" não vale direto.
Preencha com valor e fonte de um livro da base.

### Perfil do veículo

`perfil_veiculo.yaml` entra em toda resposta, separado em três grupos:
CONFIRMADO, SUPOSIÇÃO (nunca tratada como fato) e DESCONHECIDO. As
ferramentas só usam valores confirmados.

```bash
engenheiro perfil
```

```bash
engenheiro perfil definir carburador.modelo "Weber 460" --status confirmado --fonte "gravação no corpo do carburador"
```

O primeiro mostra o perfil. O segundo atualiza um campo; cada mudança fica no
`historico` do arquivo, com data, valor anterior e fonte.

### Caderno de bordo

```bash
engenheiro anotar -t "Medição da bateria" --tag bateria "Medi 12,6 V com o motor desligado há 1 h"
```

```bash
engenheiro caderno bateria
```

O primeiro grava a anotação; o segundo busca no caderno. As anotações ficam
em `data/biblioteca/caderno_de_bordo/AAAA-MM-DD.md` (dá para editar à mão) e
entram no índice na hora. A coleção do caderno é sempre consultada. Nas
respostas, as anotações aparecem como `[Caderno 2026-11-07]` e são tratadas
como registro seu, não como fonte técnica.

### Busca na web (SearXNG)

Siga `docker/searxng/compose.yaml`:

```bash
cd docker/searxng && cp settings.example.yml settings.yml
```

Troque a `secret_key` (gere uma com `openssl rand -hex 32`) e suba o serviço:

```bash
docker compose up -d
```

No `config.yaml`, aponte `web.searxng_url` para o serviço. Por padrão
(`web.modo: pedido`), ele só busca quando você pede ("pesquise na internet...").

Tudo o que vem da web aparece na seção **Web (NÃO verificado)**, com o link.
Uma afirmação que o modelo marcar como "fonte" mas que só veio da web é
reclassificada como web. Informação crítica vinda só da web gera um aviso no
topo da resposta.

## Inventário de componentes

`inventario/componentes.yaml` lista o que existe fisicamente na bancada, para
este projeto e para o Divine Machinery. Toda especificação diz se foi
confirmada, se é provável ou se falta confirmar, e de onde veio. Veja
`inventario/README.md`.

```bash
engenheiro inventario
```

```bash
engenheiro inventario --pendencias
```

O primeiro lista os componentes. O segundo mostra o que falta contar,
fotografar ou confirmar. Desde a fase 3, o engenheiro consulta o inventário
(`consultar_inventario`) antes de sugerir um circuito, e o `escolher_divisor`
só usa resistores que você tem.

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
incremental, CLI, avaliação e, na fase 2, o assistente inteiro com um LLM
roteirizado. Esse LLM de teste se comporta mal de propósito (cita trecho que
não existe, inventa número, derruba o verificador) para provar que o sistema
pega cada caso. Os lentos ficam separados:

```bash
pytest -m docling
```

```bash
pytest -m reranker
```

O primeiro roda o Docling e o OCR de verdade sobre o corpus fictício (é o
critério de aceite da fase 1). O segundo usa o reranker real.
