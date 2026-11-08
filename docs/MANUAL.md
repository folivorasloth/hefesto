# Manual do Hefesto

Como usar cada recurso, organizado por tarefa. Para instalar, veja o
[Guia de instalação](GUIA_INSTALACAO.md); para entender como funciona por
dentro, veja a [Arquitetura](ARQUITETURA.md).

Todos os comandos rodam de dentro da pasta do projeto, com o ambiente virtual
ativo (`. .venv/bin/activate`). `engenheiro --help` lista os comandos, e
`engenheiro <comando> --help` mostra as opções de cada um.

## 1. Adicionando livros à base

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
que o caderno de bordo entra no índice.

Para descrever figuras com o modelo de visão, ligue
`ingestao.figuras.descrever_com_visao` no `config.yaml`. Em CPU, cada figura
leva de 30 a 90 s. As descrições entram marcadas como **não verificadas**.

## 2. Testando sem os seus livros

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

## 3. Conversando com o Hefesto

```bash
engenheiro conversar
```

O Hefesto conversa como uma pessoa: lembra o que foi dito, entende as respostas
curtas e guia você no carro passo a passo. A conversa continua de onde parou
(`--nova` começa outra). Dentro dela, os comandos são `/perfil` (o que ele sabe do
carro), `/rastro` (auditar a última resposta), `/nova` e `/sair`. Pode começar a fala
com "Hefesto, ...", como vai ser na voz.

Exemplo do formato:

```
Você: Hefesto, como eu identifico o tipo de ignição?
Hefesto: Conhecimento geral (meu, NÃO está nas suas fontes; serve para orientar onde olhar):
         • Abra o capô e localize o distribuidor...
         ➜ Quantos fios entram no conector do distribuidor?
Você: tem 3 fios no conector
Hefesto: (...)
         Quer que eu registre isso? (sim / não)
           1. perfil observacoes.fios_conector = 3 fios como CONFIRMADO (você viu)
           2. perfil ignicao.tipo = sensor Hall como SUPOSIÇÃO (interpretação minha)
Você: sim
Hefesto: Anotado: ...
```

### O que muda em relação a `engenheiro perguntar`

- **Memória e reescrita:** cada fala é reescrita como pergunta completa antes da
  busca ("tem 3 fios" vira "o conector do distribuidor tem 3 fios; o que isso
  indica?"). O rastro guarda a fala original e a reescrita.
- **Modo guiado:** em identificação e diagnóstico, ele dá o próximo passo e
  termina com uma pergunta sobre o que você está vendo.
- **Conhecimento geral rotulado:** sem fonte na base, ele pode orientar onde olhar
  e o que observar, numa seção própria. O código **remove** desse nível qualquer
  número, valor, especificação ou instrução de mexer no carro: isso continua
  exigindo fonte ou ferramenta.
- **Velocidade:** perguntas de orientação sem valor nem risco ("onde fica", "como
  identifico") usam o modelo rápido e pulam a etapa de ferramentas. Qualquer
  valor, medida, procedimento ou segurança continua no modelo forte com o
  verificador. O motivo da escolha fica no rastro.
- **Aprende com confirmação:** quando você conta o que viu ou mediu, ele propõe
  anotar no perfil (observação) ou no caderno (medição). Só grava com "sim".
  O código descarta fato cujo trecho não está na sua fala e registra
  interpretação como suposição, nunca como confirmado.
- **Menos repetição:** o aviso de segurança completo de cada tema aparece uma vez
  por conversa; depois, uma linha lembra que ele continua valendo.
  Observações do sistema aparecem uma vez. Tudo fica no rastro.

As conversas ficam em `data/conversas/`.

## 4. Falando com o Hefesto (voz)

Na máquina da garagem (a que tem microfone e caixa de som), instale as
dependências de voz:

```bash
sudo apt install libportaudio2
```

```bash
pip install -e ".[voz]"
```

Baixe a voz em português (cerca de 60 MB):

```bash
python -m piper.download_voices --download-dir data/vozes pt_BR-faber-medium
```

Teste o alto-falante e o microfone:

```bash
engenheiro audio falar
```

```bash
engenheiro audio ouvir
```

O primeiro fala uma frase de teste. O segundo ouve você e mostra a
transcrição, dizendo se reconheceu "Hefesto". Depois, ligue:

```bash
engenheiro voz
```

Para usar só o botão de falar (Enter), que é o mais confiável com barulho:

```bash
engenheiro voz --botao
```

O Whisper "small" e o modelo tiny da ativação são baixados na primeira vez.

### Como funciona

- **Ativação:** diga "Hefesto, onde fica a bobina?" de uma vez, ou só "Hefesto"
  e espere o "Pois não?". Com `--botao`, aperte Enter e fale.
- **Conversa guiada por voz:** quando ele termina com uma pergunta ("quantos fios
  você vê?") ou pede confirmação ("quer que eu anote?"), ele ouve a resposta por
  `voz.janela_resposta_s` segundos **sem precisar dizer "Hefesto" de novo**.
- **Mumbling:** enquanto pensa, ele fala baixinho o que está realmente fazendo:
  "deixa eu ver na parte de ignição...", "achei 3 trechos, no Denton...",
  "conferindo os pinos do ESP32...". Cada frase vem de um passo real do
  processamento; se o passo não aconteceu, a frase não existe. Para desligar,
  use `--sem-mumbling` ou `voz.mumbling: false`.
- **O que ele fala:** uma versão curta da resposta.
  - O problema crítico vem primeiro e a pergunta para você por último.
  - As fontes são ditas como "segundo Denton, página 45".
  - As unidades são lidas por extenso ("12,6 volts").
  - O que o verificador removeu não é falado, e o resto fica na tela.
  - De cada tema de segurança novo, ele fala o primeiro aviso; a lista completa
    fica na tela.
- **Interrupção:** diga "Hefesto" (ou aperte Enter no modo botão) enquanto ele
  fala, e ele para. Ele **não** para com qualquer voz: sem cancelamento de eco,
  a própria fala dele, captada pelo microfone, o interromperia.
- **Comandos de voz:**
  - "modo dirigindo": silêncio total, as respostas ficam guardadas e só alertas
    críticos são falados;
  - "parei": sai do modo dirigindo e ele lê o que ficou guardado;
  - "nova conversa".

### Ajustes para a garagem

| Problema | Ajuste no config |
|---|---|
| Barulho dispara a escuta | `voz.agressividade_vad: 3` |
| Ele corta você no meio da frase | aumente `voz.silencio_fim_fala_ms` |
| Entende mal | `voz.whisper_modelo: medium` (no teste, acertou frases que o small errou; leva cerca de 5 s por fala na CPU) |
| CPU alta esperando a palavra | `voz.ativacao.modo: openwakeword` (veja abaixo) ou botão |

### Palavra de ativação dedicada (opcional)

O modo padrão (`transcricao`) transcreve tudo o que é falado perto do
microfone para achar "Hefesto". Ele funciona sem preparo, mas usa CPU. O
openWakeWord é muito mais leve, porém só traz palavras em inglês prontas. Para
"Hefesto", é preciso treinar um modelo: o openWakeWord tem um notebook de
treino que gera exemplos sintéticos da palavra (dá para usar a voz pt_BR do
Piper). Depois, aponte `voz.ativacao.modelo_openwakeword` para o arquivo
gerado e use `voz.ativacao.modo: openwakeword`.

### O que já foi testado e o que falta

Testado aqui, sem placa de som:
- a voz do Piper falando a pergunta, o recorte por VAD, o Whisper transcrevendo
  e a palavra de ativação reconhecida;
- o loop completo em tempo simulado: ativação, resposta falada, ouvir a
  resposta sem a palavra, e o "sim";
- o que funcionou: "Hefesto" (até transcrito como "Efesto"), "sim" e "não";
- o que errou: "tem três fios" virou "tentei os fios" na voz sintética. A
  proteção do aprendizado **descartou** o fato em vez de gravar errado.

Falta testar com o microfone e a voz real, na garagem.

## 5. Perguntas avulsas e auditoria (rastro)

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

### Calibrando o limiar de relevância

O `limiar_relevancia: 0.10` é provisório. Depois de indexar seus livros e
preencher `data/usuario/avaliacao/perguntas.yaml` (inclua perguntas cuja resposta NÃO está na
base), rode:

```bash
engenheiro avaliar
```

Compare `score_rerank_min_dos_acertos` com `score_rerank_max_fora_da_base` e
ponha o limiar entre os dois, mais perto do segundo. Errar para baixo só
manda um trecho a mais para o modelo (e o verificador ainda confere). Errar
para cima faz ele dizer "não encontrei" quando a resposta estava lá.

### Validando as respostas com o modelo real

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

## 6. Ferramentas, perfil do carro, caderno de bordo e web

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
| `ler_telemetria` | Último valor ao vivo de um sinal do carro, recebido pelo MQTT (`engenheiro servir`). Recusa dado velho |

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

O perfil (`data/usuario/perfil_veiculo.yaml`) entra em toda resposta, separado em três grupos:
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

## 7. Inventário de componentes

`data/usuario/inventario.yaml` lista o que existe fisicamente na bancada, para
este projeto e para o Divine Machinery. Toda especificação diz se foi
confirmada, se é provável ou se falta confirmar, e de onde veio. Veja
[INVENTARIO.md](INVENTARIO.md).

```bash
engenheiro inventario
```

```bash
engenheiro inventario --pendencias
```

O primeiro lista os componentes. O segundo mostra o que falta contar,
fotografar ou confirmar. O Hefesto consulta o inventário
(`consultar_inventario`) antes de sugerir um circuito, e o `escolher_divisor`
só usa resistores que você tem.

## 8. Serviço: API HTTP e MQTT

```bash
pip install -e ".[servico]"
```

```bash
export HEFESTO_API_TOKEN="um-token-longo-qualquer"
```

```bash
engenheiro servir
```

O último comando liga a API em `http://<máquina>:8765` (documentação interativa
em `/docs`) e o MQTT, se `mqtt.host` estiver no config. `--sem-api` e
`--sem-mqtt` desligam cada parte.

**API (cabeçalho `Authorization: Bearer <token>`, exceto em `/status`):**

| Rota | O que faz |
|---|---|
| `GET /status` | Estado, Ollama, sinais de telemetria recebidos |
| `POST /perguntar` `{"pergunta": ...}` | Pergunta isolada |
| `POST /conversas/{interlocutor}/turno` `{"fala": ...}` | Conversa com memória, uma por interlocutor |
| `POST /conversas?interlocutor=...` | Começa uma conversa nova |
| `GET /rastro/{id}` | Auditoria completa de uma resposta |
| `POST /caderno` e `GET /caderno?termo=` | Anotar e buscar no caderno |
| `GET /perfil` | Perfil do veículo |
| `GET /ferramentas` e `POST /ferramentas/{nome}` | Calculadoras sem LLM, úteis para outros personagens |

**MQTT:** o protocolo completo para os outros personagens está em
[`docs/PROTOCOLO_MQTT.md`](PROTOCOLO_MQTT.md). Em resumo:
- entrada em `joao/fala/engenheiro`, como texto ou JSON
  `{"texto", "id", "de"}`;
- saída em `npc/engenheiro/fala`, em JSON com versão curta e completa;
- status retido em `npc/engenheiro/status`, com Last Will "offline";
- mumbling em `npc/engenheiro/pensamento`;
- telemetria do carro em `carro/telemetria/#`, usada pela ferramenta
  `ler_telemetria`.

**Comportamento do serviço:**
- O modelo atende **um pedido por vez**: o notebook não aguenta dois. Os
  outros esperam na fila.
- Se o Ollama estiver desligado, o estado fica `sem_cerebro` e **volta sozinho**
  quando ele ligar.
- O reranker é carregado ao ligar o serviço, para a primeira pergunta não
  pagar esse tempo.

## 9. Avaliação

A avaliação faz parte da definição de pronto: toda mudança (modelo, prompt,
limiar, corte) deve ser medida antes e depois.

| Modo | O que mede | Precisa do Ollama |
|---|---|---|
| `recuperacao` | A fonte certa aparece nos trechos? (acerto@k, MRR, scores do reranker) | não |
| `resposta` | O assistente completo, pelo modo `perguntar` | sim |
| `conversa` | O mesmo, pelo modo conversa (modelo rápido em orientação) | sim |
| `completo` | Recuperação e resposta no mesmo relatório | sim |
| `cenarios` | Conversas de vários turnos (`data/usuario/avaliacao/cenarios.yaml`) | sim |

```bash
engenheiro avaliar --modo completo
```

```bash
engenheiro avaliar --modo cenarios
```

**Métricas de resposta:**
- `nao_sei_correto`: disse "não encontrei" quando a informação não estava na base?
- `falso_nao_sei`: disse "não encontrei" quando a informação estava lá?
- `fonte_aprovada`: das afirmações exibidas como fonte, quantas o verificador
  aprovou. Deve ser 1.0.
- `citacao_na_fonte_esperada`: ele cita o livro **certo**?
- `fatos_chave` e `fatos_chave_criticas`: comparação com unidade, então
  "0,15 A" conta como "150 mA", mas não como "0,15 V".
- `geral_violacoes`: quantas vezes o modelo tentou pôr valor sem fonte no
  "conhecimento geral".
- `respostas_com_problema_critico`.
- Tempo médio, mediana e máximo: é o número que diz se a GPU faz falta.

**Relatórios:** cada execução grava `data/usuario/avaliacao/relatorios/*.md` e `*.json`, com a
configuração usada, e compara com a execução anterior do mesmo arquivo,
pergunta por pergunta, listando o que melhorou e **o que piorou**. Com
`--falhar-se-piorar`, o comando sai com erro se algo piorou.

**Seus arquivos:**
- `data/usuario/avaliacao/perguntas.yaml` (criado de `eval/perguntas.yaml` na
  primeira vez): modelos desativados para você preencher com perguntas
  reais. Inclua algumas cuja resposta NÃO está na base.
- `data/usuario/avaliacao/cenarios.yaml` (criado de `eval/cenarios.yaml`):
  conversas de exemplo que valem mesmo com a base vazia.
  A avaliação de cenários usa uma cópia do perfil: não grava no perfil do seu
  carro.
- `eval/perguntas_corpus_teste.yaml`: perguntas sobre o corpus fictício.

**Calibrar o limiar de relevância:** compare `score_rerank_min_dos_acertos`
com `score_rerank_max_fora_da_base`, no modo `recuperacao`.

## 10. Testes automáticos

```bash
pytest
```

Esse comando roda os testes rápidos (cerca de 180, alguns segundos). Eles
cobrem:
- chunker, busca, citações e indexação incremental;
- todas as ferramentas de cálculo, com valores conferíveis à mão;
- verificador, conversa, voz com áudio falso, API e MQTT (contra um Mosquitto
  local, se instalado).

O assistente inteiro é testado com um LLM roteirizado que se comporta mal de
propósito (cita trecho que não existe, inventa número, faz conta de cabeça,
derruba o verificador) para provar que o sistema pega cada caso.

Os testes lentos ficam separados:

```bash
pytest -m docling
```

```bash
pytest -m reranker
```

```bash
HEFESTO_VOZ_TESTE=data/vozes/pt_BR-faber-medium.onnx pytest -m voz
```

O primeiro roda o Docling e o OCR de verdade sobre o corpus fictício. O
segundo usa o reranker real. O terceiro faz a ida e volta Piper → VAD →
Whisper com a voz baixada.

Para rodar tudo:

```bash
pytest -m ""
```

## 11. Seus dados, personalização e backup

**Onde ficam:** tudo o que é seu fica em `data/`, fora do git. Atualizar o
projeto (`git pull`) nunca mexe nisso nem dá conflito.

| O quê | Onde |
|---|---|
| Perfil do carro (com histórico) | `data/usuario/perfil_veiculo.yaml` |
| Inventário da bancada | `data/usuario/inventario.yaml` |
| Perguntas, cenários e relatórios de avaliação | `data/usuario/avaliacao/` |
| Arquivos de referência personalizados | `data/usuario/dados_ref/`, `data/usuario/persona/` |
| Caderno de bordo | `data/biblioteca/caderno_de_bordo/` |
| Conversas | `data/conversas/` |
| Livros, índice, cache, rastros | `data/biblioteca/`, `data/indice.sqlite`, `data/cache/`, `data/rastros/` |

O perfil, o inventário e os arquivos de avaliação são criados na primeira vez
a partir dos modelos do projeto (`modelos/`, `eval/`).

**Personalizar um arquivo de referência:** estequiometria, glossário, avisos
de segurança, pinos do ESP32, constantes e persona têm um padrão no projeto.
Para mudar um deles, crie a sua cópia:

```bash
engenheiro personalizar
```

```bash
engenheiro personalizar combustiveis
```

O primeiro lista o que dá para personalizar. O segundo cria
`data/usuario/dados_ref/combustiveis.yaml`. Edite essa cópia: ela passa a
valer no lugar do padrão. Para voltar ao padrão, apague a cópia.

**Backup:**

```bash
engenheiro backup
```

```bash
engenheiro backup --completo --destino /mnt/homelab/backups
```

- `backup` guarda o que não dá para recriar: perfil, inventário, avaliações,
  arquivos personalizados, caderno, conversas e o `config.yaml`. É pequeno;
  rode sempre.
- `backup --completo` acrescenta livros, índice, cache de extração e rastros.
  É grande, mas evita reprocessar os livros (a parte que leva noites).

Para restaurar:

```bash
tar -xzf data/backups/<arquivo>.tar.gz -C <pasta do projeto>
```

