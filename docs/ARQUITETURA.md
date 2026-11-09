# Arquitetura do Hefesto

Como o Hefesto funciona por dentro, por que cada decisão foi tomada, o que foi
medido e o que ainda é limitação conhecida. Para usar, veja o
[Manual](MANUAL.md); para instalar, o [Guia de instalação](GUIA_INSTALACAO.md).

O identificador técnico é `engenheiro` (pacote Python, comando de terminal,
tópicos MQTT); o nome exibido e falado é **Hefesto** (`persona/engenheiro.yaml`).

## 1. Princípio

> Correção acima de velocidade e de elegância. Prefiro "não encontrei" a uma
> resposta errada com confiança.

Daí saem quatro regras de projeto, que atravessam o código:

1. **O modelo de linguagem nunca é a fonte da verdade.** Ele só redige. Fatos
   vêm de trechos de livros; contas vêm de ferramentas em Python; avisos de
   segurança vêm de um arquivo.
2. **Tudo o que dá para conferir com código é conferido com código.** Citações,
   números (valor e unidade), criticidade e formato da resposta são checados
   de forma determinística. O LLM verificador entra só onde é preciso
   julgamento.
3. **O modelo não escreve citações.** Ele aponta ids (`T3`, `F1`), e o código
   monta `[Livro, p. X]` a partir dos metadados. Citação inventada é
   impossível; citação de id inexistente é descartada.
4. **Degradação explícita.** Sem Ollama, sem reranker, sem web ou sem
   verificador, ele continua, mas **diz** o que ficou faltando. Nenhuma falha
   é silenciosa e nada que não foi verificado é apresentado como verificado.

## 2. Máquinas e componentes

```
 Notebook do LLM (i7, 16 GB)          Máquina do Hefesto (pode ser a mesma)
 ┌──────────────────────┐   HTTP     ┌──────────────────────────────────────────┐
 │ Ollama               │◄──────────►│ engenheiro (Python)                      │
 │  qwen3:14b  (forte)  │            │  índice SQLite (FTS5 + sqlite-vec)       │
 │  qwen3:4b   (rápido) │            │  Docling + Tesseract (ingestão)          │
 │  bge-m3     (vetores)│            │  bge-reranker-v2-m3 (CPU)                │
 │  qwen2.5vl  (figuras)│            │  Whisper + Piper (voz, opcional)         │
 └──────────────────────┘            │  CLI · API HTTP · cliente MQTT           │
                                     └──────────┬───────────────────────────────┘
 Homelab (Docker)                               │ MQTT
 ┌──────────────────────┐                       │
 │ Mosquitto ◄──────────┼───────────────────────┘◄── outros personagens / ESP32 do carro
 │ SearXNG (busca web)  │◄── HTTP (só quando você pede busca na web)
 └──────────────────────┘
```

## 3. O caminho de uma resposta

```
fala ─► (conversa) reescrita com o histórico ─► escolha do modelo (regras)
     ─► tradução PT→EN (rápido)
     ─► busca: variantes (original, glossário, inglês) × (BM25 + vetor)
              ─► fusão RRF ─► reranker (cada trecho × consulta no idioma dele)
              ─► limiar de relevância (abaixo dele: "não encontrei")
     ─► etapa 1: ferramentas (o modelo pede contas, pinos, inventário, caderno)
     ─► etapa 2: resposta em JSON (afirmações tipadas, ligadas a ids)
     ─► verificador (código + LLM) ─► avisos de segurança (arquivo)
     ─► montagem: texto da tela + versão falada ─► rastro JSON
     ─► (conversa) propostas de anotação: perfil/caderno, só com "sim"
```

### 3.1 Escolha do modelo (`llm/selecao.py`)

Por regras, auditáveis no rastro:

| Situação | Modelo |
|---|---|
| Cumprimento ou agradecimento | **rápido**, sem busca e proibido de dar dado técnico |
| No modo conversa, orientação sem valor nem risco ("onde fica", "como identifico") | **rápido**, sem etapa de ferramentas |
| Qualquer valor, medida, procedimento, segurança, elétrica | **forte** |
| Na dúvida | **forte** |

### 3.2 Níveis de confiança na resposta

| Nível | De onde vem | Como aparece |
|---|---|---|
| **Fonte** | Trecho de livro (T#) ou resultado de ferramenta (F#), aprovado pelo verificador | "Das fontes", com `[Livro, p. X]` ou `[cálculo: nome]` |
| **Inferência** | Raciocínio do modelo a partir das fontes | "Inferência (raciocínio meu...)", "a partir de [...]" |
| **Conhecimento geral** | O que o modelo sabe, sem fonte, **só para orientar a observação** | Seção própria; o código remove dela qualquer número, valor ou instrução de mexer no carro |
| **Web** | SearXNG, só quando você pede | "Web (NÃO verificado)", com o link |

### 3.3 Regras do verificador (`verificador/verificador.py`)

| Situação | Resultado |
|---|---|
| Cita id inexistente | Citação descartada; "fonte" sem citação vira inferência |
| Verificador LLM: `suporta` | Mantida |
| `parcial` (fonte) | Vira inferência, com a justificativa |
| `nao_suporta` | **Removida**, listada à parte com o motivo |
| Verificador fora do ar | Nada conta como aprovado; aviso no topo |
| Número sem origem (valor **e** unidade) | Marcado ⚠; "fonte" vira inferência |
| Conhecimento geral com número/valor/instrução | **Removida** |
| Informação crítica só da web | Aviso no topo |
| Qualquer problema em afirmação **crítica** (tensão, corrente, torque, combustível, bateria, ignição, segurança) | Aparece **no topo** da resposta (e é falado primeiro) |

Origens aceitas para um número: o trecho citado, o resultado de ferramenta, a
sua pergunta e os valores **confirmados** do perfil (não o texto inteiro do
perfil: as observações dele fariam um "2" qualquer parecer ter origem).

## 4. Ingestão e busca

```
PDF ──Docling──► blocos (título/parágrafo/lista/tabela/figura, com página)
                   │   OCR (Tesseract por+eng) nas páginas sem camada de texto
                   ▼
              chunker: corta por seção; nunca corta tabela nem procedimento
                   │  numerado (mesmo atravessando página); aviso (ATENÇÃO...)
                   │  gruda no procedimento seguinte
                   ▼
   SQLite ─┬─ FTS5 (BM25, sem acento; acha GPIO34, 030-905-205...)
           └─ sqlite-vec (bge-m3, cosseno, particionado por coleção)
```

- **Incremental em três níveis:** a extração (lenta) fica em cache pelo hash
  do PDF; os trechos são refeitos se mudar a ficha do livro ou a config de
  corte; os embeddings ficam pendentes se o Ollama estiver fora e são
  gerados depois.
- **Página do PDF ≠ página impressa:** a citação mostra "p. 67 do PDF" até
  você informar `deslocamento_paginas` na ficha do livro.
- **Origem do texto:** trechos de OCR e descrições de figura por IA são
  marcados e aparecem com aviso.
- **Roteamento:** o glossário PT/EN escolhe as coleções; `veiculo` e
  `caderno_de_bordo` entram sempre; sem pista nenhuma, busca em todas.
- **Reranker por idioma:** com a tradução disponível, trecho em inglês é
  pontuado pela pergunta traduzida e trecho em português pela original. Isso
  levou a pergunta em português contra o livro em inglês de 0,06 para 0,998,
  pela metade do custo de pontuar pelas duas.

## 5. Decisões e porquês

| Decisão | Por quê |
|---|---|
| SQLite (FTS5 + sqlite-vec) em vez de Qdrant | O bge-m3 pelo Ollama só dá o vetor denso, então o BM25 seria feito por fora de qualquer jeito; é um arquivo só, copiável e auditável |
| Docling em vez de Marker | Licença MIT, tabelas e hierarquia de títulos, página de cada item |
| Tesseract em vez do OCR padrão do Docling | 100% local, pacote de português no apt; o padrão baixa modelos de um servidor de terceiros |
| Chunker próprio | O Docling não marca procedimento numerado e o quebra na virada de página; o chunker reconhece a sequência 1, 2, 3... |
| Saída em JSON com esquema | O Ollama força o formato: cada afirmação tem tipo e ids; o texto final é montado pelo código |
| Duas etapas (ferramentas, depois resposta) com o mesmo começo de prompt | Tool calling e saída estruturada juntos não são confiáveis em todos os modelos; o prefixo comum deixa o Ollama reaproveitar o processamento do prompt |
| Estequiometria sem valor padrão | O etanol da bomba é hidratado e a gasolina brasileira tem etanol: o número "de livro" não vale direto |
| Fato aprendido na conversa só com "sim" | O código exige que o trecho esteja **literalmente** na sua fala; interpretação vira suposição |
| Aviso de segurança completo uma vez por conversa | Repetir o bloco a cada turno tornava a conversa ilegível; o lembrete continua aparecendo |
| Ativação da voz por transcrição | Funciona sem treinar nada; o openWakeWord só tem palavras em inglês prontas |
| Interrupção só pela palavra ou pelo botão | Sem cancelamento de eco, a própria fala do Hefesto o interromperia |
| `llm` conferido a cada pergunta | O Hefesto "acorda" sozinho quando o notebook do LLM liga |
| Vários cérebros, escolha fixa por resposta | O projeto não depende de uma máquina (o notebook do trabalho entra e sai pela config); uma resposta nunca mistura modelos de máquinas diferentes, e o rastro diz qual respondeu |
| Embeddings em endereço próprio | O `bge-m3` no homelab (sempre ligado) mantém a busca semântica funcionando com os cérebros desligados |
| Cliente remoto de voz | O notebook da garagem só ouve e fala; livros, índice e memória ficam num lugar só, sem cópias |
| `keep_alive` do Ollama em cada pedido | Evita recarregar o modelo do disco entre perguntas (dezenas de segundos para um 14B em CPU) |

## 6. Mapa do código (`src/engenheiro/`)

| Módulo | Responsabilidade |
|---|---|
| `config.py` | Config validada (pydantic); `config.example.yaml` documenta toda opção (há teste garantindo) |
| `ingest/` | `extrator` (Docling/OCR/figuras), `chunker`, `idioma`, `indexador` (incremental) |
| `store/` | Esquema SQLite, `db` (documentos, trechos, vetores), `busca_hibrida` (BM25, vetor, RRF) |
| `recuperacao/` | `reescrita` (glossário, roteamento), `reranker`, `pipeline` (busca completa com scores) |
| `llm/` | `ollama` (cliente HTTP: chat, JSON, tools, embeddings), `selecao` (rápido/forte), `cerebros` (várias máquinas em ordem de preferência) |
| `geracao/` | `prompts`, `esquemas`, `gerador` (contexto e chamada), `montagem` (texto e fala) |
| `verificador/` | `numeros` (valor + unidade), `verificador` (citações, LLM, regras) |
| `ferramentas/` | `base` (registro/validação), `eletrica`, `motor`, `unidades`, `esp32`, `etapa` (tool calling) |
| `assistente.py` | Orquestra uma resposta; rastro; modo sem LLM |
| `conversa.py` | Sessão, reescrita, modo guiado, propostas de anotação |
| `perfil.py`, `caderno.py`, `inventario.py` | Perfil do carro, caderno de bordo, inventário da bancada |
| `seguranca.py`, `persona.py` | Avisos determinísticos; persona |
| `web.py`, `telemetria.py` | SearXNG; cache da telemetria ao vivo |
| `voz/` | `audio`, `vad`, `stt_tts`, `ativacao`, `mumbling`, `orquestrador` |
| `servico.py`, `interfaces/` | Núcleo do serviço; `cli`, `api` (FastAPI), `mqtt` (paho), `remoto` (voz/texto usando o serviço de outra máquina) |
| `eventos.py`, `rastro.py` | Barramento de eventos (rastro e mumbling); gravação do rastro |
| `avaliacao.py` | Avaliação de busca, respostas e cenários; relatórios comparáveis |

Os dados de referência ficam fora do código, em arquivos editáveis:
`dados_ref/` (glossário, segurança, constantes, combustíveis, pinos do ESP32),
`persona/`, `eval/`, e os **modelos** dos seus arquivos pessoais em `modelos/`.

**Seus dados nunca ficam no repositório:** o perfil, o inventário, as perguntas
e os relatórios de avaliação moram em `data/usuario/`, criados a partir dos
modelos na primeira vez. Um arquivo de referência que você personaliza
(`engenheiro personalizar`) também vai para `data/usuario/` e passa a valer
no lugar do padrão. Assim, atualizar o projeto (`git pull`) nunca conflita
com os seus dados.

## 7. Dados em disco (`data/`, fora do git)

| Pasta | Conteúdo |
|---|---|
| `data/usuario/` | **Seus dados**: perfil, inventário, avaliação, arquivos personalizados |
| `data/biblioteca/<coleção>/` | Seus PDFs e fichas `.yaml`; o caderno de bordo em `caderno_de_bordo/` |
| `data/indice.sqlite` | Índice (texto, BM25, vetores) |
| `data/cache/` | Extrações do Docling (a parte lenta) |
| `data/figuras/` | Imagens das figuras dos livros |
| `data/rastros/AAAA/MM/` | Um JSON por resposta (auditoria) |
| `data/conversas/` | Sessões de conversa (memória) |
| `data/vozes/` | Voz do Piper |
| `data/backups/` | Backups (`engenheiro backup`) |

## 8. Concorrência

- O modelo atende um pedido por vez (o notebook não aguenta dois): o serviço
  tem uma fila única, que também protege o índice.
- Na voz, a resposta é montada numa thread de trabalho enquanto a thread
  principal fala o mumbling; o SQLite é aberto com `check_same_thread=False`,
  mas o acesso continua serializado.
- No MQTT, o laço de rede nunca espera o modelo: as mensagens vão para uma
  fila processada noutra thread.

## 9. Números medidos no desenvolvimento

Medidos num container de 4 vCPU, sem GPU. Os do seu i7 serão diferentes; o
rastro e a avaliação medem os reais.

| O quê | Medida |
|---|---|
| Docling + OCR no corpus de teste (4 PDFs pequenos) | ~15 s; o primeiro uso baixa ~500 MB de modelos |
| Reranker, 25 trechos curtos | 20 s (max_tokens 1024) / 12 s (512) |
| Pergunta pelo MQTT sem LLM, antes e depois das otimizações | 101 s → 9 s |
| Instalação limpa (Python 3.12, PyTorch CPU, todos os extras) | 2,6 GB, sem pacotes NVIDIA |
| Piper: 3,2 s de fala | gerados em 1,9 s |
| Whisper tiny / small / medium em uma pergunta falada | 0,7 s / 1,9 s / 4,9 s |
| Score do reranker: acerto típico × pergunta fora da base | ~0,97 × ~0,0007 |

## 10. Limitações conhecidas

- **Modelo de linguagem real não testado no desenvolvimento:** todo o fluxo
  com LLM foi testado com respostas roteirizadas (inclusive as erradas de
  propósito). O comportamento do qwen3 de verdade (seguir o JSON, chamar
  ferramentas, usar o "conhecimento geral" só para orientar) precisa ser
  medido com `engenheiro avaliar` na sua máquina.
- **Limiar de relevância provisório (0,10):** calibre com os seus livros.
- **Tabela de pinos do ESP32:** as restrições são as conhecidas do ESP32
  clássico, ainda marcadas como "conferir com o datasheet".
- **Voz sintética:** "tem três fios" foi transcrito errado; com voz real e
  barulho de garagem, só testando. A proteção do aprendizado impediu gravar o
  fato errado.
- **Checagem de números:** compara valor e grandeza, mas não entende contexto
  ("12 V" de outra peça na mesma página passaria). O verificador LLM cobre
  parte disso.
- **Ativação por transcrição:** gasta CPU contínua enquanto alguém fala perto
  do microfone; a alternativa leve (openWakeWord) exige treinar "Hefesto".
- **Sem cancelamento de eco:** a interrupção é pela palavra ou pelo botão.
