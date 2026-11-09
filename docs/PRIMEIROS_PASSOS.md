# Primeiros passos: testar hoje nos seus notebooks

Roteiro para hoje, do zero até conversar com o Hefesto e alimentá-lo com os
livros. Ele usa:

| Apelido | Máquina | Papel hoje |
|---|---|---|
| **DOCKER** | Notebook do trabalho, i5-1334U, 16 GB | **Cérebro**: roda os modelos de conversa (Ollama) |
| **ESTE** | Notebook do trabalho que você está usando, 8 GB | **Hefesto**: livros, índice, busca, conversa por texto |
| **RYZEN** | Seu notebook de casa, 12 GB | À noite: **cérebro** em casa |

O ESTE vai com você para casa. No trabalho, o Hefesto usa o DOCKER; em casa,
usa o RYZEN **sozinho**, sem você mexer em nada (ele usa o primeiro cérebro da
lista que estiver respondendo).

> **Seus dados ficam no ESTE só por enquanto.** Ele é da empresa. Quando o
> homelab estiver pronto, você leva tudo para lá com `engenheiro backup
> --completo` (Etapa 7).

Tempo estimado (depende da internet e dos livros):
- Ollama nos dois notebooks: 30 a 60 min, a maior parte download;
- Hefesto no ESTE: 30 a 60 min;
- livros: de minutos a horas por livro. Deixe rodando.

**Antes de começar, descubra o sistema operacional de cada notebook.** O
roteiro cobre **Windows** e **Linux**. No Windows, o Ollama roda direto no
Windows, e o Hefesto roda dentro do **WSL** (um Ubuntu dentro do Windows), que
é o ambiente onde ele foi testado.

> **Notebook da empresa:** instalar o WSL e o Ollama pode exigir permissão de
> administrador, e a rede da empresa pode bloquear um notebook de falar com o
> outro. A Etapa 2.4 testa isso; se der bloqueio, há um plano B.

---

## Etapa 1: Ollama no DOCKER (o cérebro)

### 1.1 Quanta memória está livre

O DOCKER já roda os containers da empresa. O modelo de 14B precisa de uns
**11 GB livres** (estimativa, com o contexto); o de 8B, de uns **7 GB**.

- **Windows:** Gerenciador de Tarefas → Desempenho → Memória → "Disponível".
- **Linux:**

  ```bash
  free -h
  ```

  Olhe a coluna `available`.

| Memória disponível | Modelo forte |
|---|---|
| 11 GB ou mais | `qwen3:14b` |
| entre 7 e 11 GB | `qwen3:8b` |
| menos de 7 GB | Plano B (Etapa 2.4): o ESTE não aguenta ser o cérebro com 8 GB e o Hefesto junto |

### 1.2 Instalar o Ollama

**Windows:** baixe e instale pelo site oficial:
<https://ollama.com/download/windows>. Ele fica no ícone da bandeja, perto do
relógio.

**Linux:**

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 1.3 Deixar o Ollama acessível na rede e com o modelo na memória

**Windows.** Abra o PowerShell **como administrador** e rode:

```powershell
setx OLLAMA_HOST "0.0.0.0" /M
```

```powershell
setx OLLAMA_KEEP_ALIVE "30m" /M
```

```powershell
setx OLLAMA_MAX_LOADED_MODELS "2" /M
```

Libere a porta no firewall, só para redes privadas e de domínio:

```powershell
New-NetFirewallRule -DisplayName "Ollama" -Direction Inbound -LocalPort 11434 -Protocol TCP -Action Allow -Profile Private,Domain
```

Depois, **feche o Ollama** (botão direito no ícone da bandeja → Quit) e
**abra de novo** pelo menu Iniciar. Ele só lê as variáveis novas ao reabrir.

**Linux:**

```bash
sudo systemctl edit ollama
```

Cole e salve:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
Environment="OLLAMA_KEEP_ALIVE=30m"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
```

```bash
sudo systemctl restart ollama
```

### 1.4 Baixar os modelos

Num terminal do DOCKER (PowerShell ou Linux), baixe o forte que você escolheu
na tabela da 1.1 (aqui, o 14B):

```bash
ollama pull qwen3:14b
```

E o rápido:

```bash
ollama pull qwen3:4b
```

> Se o `pull` disser que o modelo não existe (os nomes mudam com o tempo), rode
> `ollama list` e me mande o erro. Eu ajusto os nomes no config.

### 1.5 Descobrir o IP do DOCKER

- **Windows:**

  ```powershell
  ipconfig
  ```

  Procure o "Endereço IPv4" da placa em uso (Wi-Fi ou Ethernet).
- **Linux:**

  ```bash
  hostname -I
  ```

Anote: é o `<IP-DOCKER>` das próximas etapas.

### 1.6 Teste rápido no próprio DOCKER

```bash
ollama run qwen3:4b "Responda só: ok"
```

✅ Responde alguma coisa. A primeira vez demora, porque carrega o modelo.

---

## Etapa 2: preparar o ESTE (Windows → WSL)

Se o ESTE já for **Linux**, pule para a Etapa 3.

### 2.1 Instalar o WSL com Ubuntu 24.04

PowerShell **como administrador**:

```powershell
wsl --install -d Ubuntu-24.04
```

**Reinicie o notebook.** Na volta, o Ubuntu abre sozinho e pede um usuário e
uma senha (são só do Ubuntu; anote).

### 2.2 Dar memória suficiente ao WSL

Por padrão, o WSL usa metade da RAM (4 GB). Isso é pouco para ler PDFs. No
Windows, crie o arquivo `C:\Users\<SEU_USUARIO>\.wslconfig` (no Bloco de
Notas, salvando com "Todos os arquivos", sem `.txt` no fim) com:

```ini
[wsl2]
memory=6GB
swap=4GB
```

No PowerShell, reinicie o WSL para valer:

```powershell
wsl --shutdown
```

Abra o "Ubuntu 24.04" pelo menu Iniciar. **Todo o resto deste roteiro, no
ESTE, roda dentro desse terminal do Ubuntu.**

> Com 8 GB no total, sobram uns 2 GB para o Windows. Feche navegador pesado,
> Teams etc. enquanto os livros estiverem sendo lidos.

### 2.3 Não deixar o notebook dormir

A leitura dos livros pode levar horas. Em Configurações → Sistema → Energia,
ponha "Suspender" em **Nunca** quando estiver na tomada.

### 2.4 O ESTE enxerga o Ollama do DOCKER?

No terminal do Ubuntu:

```bash
curl http://<IP-DOCKER>:11434/api/tags
```

✅ **Esperado:** um JSON listando `qwen3:14b` e `qwen3:4b`. Siga para a Etapa 3.

❌ **Se der erro ou ficar parado:**
1. Confira se o Ollama do DOCKER foi **reaberto** depois do `setx` (1.3).
2. Confira se a regra de firewall foi criada (1.3).
3. Teste do próprio DOCKER: `curl http://localhost:11434/api/tags`.

Se no DOCKER funciona e do ESTE não, **a rede da empresa está bloqueando**
conexões entre notebooks. Plano B: instale o Hefesto **no DOCKER** (Etapas 2 e
3 no DOCKER, em vez do ESTE). No config, use
`url: http://localhost:11434` (Windows com WSL: veja o fim da 3.6). O DOCKER
tem 16 GB, mas os containers já ocupam parte; nesse caso, use o `qwen3:8b`.

---

## Etapa 3: instalar o Hefesto no ESTE (no Ubuntu do WSL ou no Linux)

### 3.1 Pacotes do sistema

```bash
sudo apt update
```

```bash
sudo apt install -y git python3 python3-venv python3-dev tesseract-ocr tesseract-ocr-por tesseract-ocr-eng
```

Confira o Python: **3.12 ou mais novo** (o Ubuntu 24.04 já vem com o 3.12):

```bash
python3 --version
```

### 3.2 Ollama local, só para a busca (bge-m3)

O modelo de busca (`bge-m3`, cerca de 1,2 GB) roda **no próprio ESTE**. Assim a
busca funciona no trabalho e em casa, qualquer que seja o cérebro:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

```bash
ollama pull bge-m3
```

### 3.3 Baixar o projeto

Se você já juntou o pull request na `main` (no GitHub: PR #1 → "Merge pull
request"):

```bash
git clone https://github.com/folivorasloth/hefesto
```

Se ainda não juntou:

```bash
git clone -b dados-versoes-ci https://github.com/folivorasloth/hefesto
```

```bash
cd hefesto
```

### 3.4 Ambiente Python e instalação

```bash
python3 -m venv .venv
```

```bash
. .venv/bin/activate
```

PyTorch só para CPU (economiza alguns GB):

```bash
pip install torch==2.15.0 torchvision==0.29.2 --index-url https://download.pytorch.org/whl/cpu
```

O Hefesto, com as versões testadas. Hoje sem voz, para instalar mais rápido:

```bash
pip install -e ".[ingestao,reranker,servico,dev]" -c requisitos/testados.txt
```

> **Toda vez que abrir um terminal novo:** `cd ~/hefesto` e depois
> `. .venv/bin/activate`.

### 3.5 Testes automáticos (sem modelos, alguns segundos)

```bash
pytest
```

✅ Cerca de 190 testes passando. (Os de MQTT são pulados, porque o Mosquitto
não está instalado aqui. É normal.)

### 3.6 Configurar

```bash
cp config.example.yaml config.yaml
```

```bash
nano config.yaml
```

No bloco `ollama:`, **apague a linha `cerebros: []`** e as linhas de exemplo
comentadas logo abaixo dela, e ponha no lugar o bloco abaixo. Depois ajuste
`url_embeddings` e `manter_carregado`, que já existem mais abaixo. Use espaços,
nunca Tab, com a mesma indentação do resto do bloco:

```yaml
  cerebros:
    - nome: trabalho
      url: http://<IP-DOCKER>:11434
      modelos: {forte: "qwen3:14b"}       # ou "qwen3:8b", conforme a 1.1
    # Descomente à noite, quando souber o IP do RYZEN (Etapa 6):
    # - nome: ryzen
    #   url: http://<IP-RYZEN>:11434
    #   modelos: {forte: "qwen3:8b"}
  url_embeddings: http://localhost:11434   # o bge-m3 do próprio ESTE
  manter_carregado: "30m"
```

Para conferir se o YAML ficou válido (erro de indentação aparece aqui, com a
linha):

```bash
engenheiro status
```

E, mais abaixo, no bloco `geracao:`, troque `pensar: null` por:

```yaml
  pensar: false
```

`pensar: false` deixa o qwen3 bem mais rápido. Depois você compara com `true`
na avaliação.

Para salvar no `nano`: `Ctrl+O`, `Enter`, `Ctrl+X`.

> Plano B (Hefesto no próprio DOCKER com Windows): o Ollama roda no Windows e
> o Hefesto no WSL. Primeiro tente `url: http://localhost:11434`. Se não
> responder, use o IP do Windows (o da 1.5).

### 3.7 Conferir tudo

```bash
engenheiro status
```

✅ **Esperado:**
- `trabalho ... respondendo ← em uso agora`, com `forte` e `rapido` como
  "instalado";
- "Embeddings em http://localhost:11434: respondendo", com o `bge-m3`
  instalado.

---

## Etapa 4: primeira conversa (ainda sem livros)

```bash
engenheiro conversar
```

Com a base vazia, ele só pode orientar com **conhecimento geral** (onde olhar,
o que observar, nunca valores) e dizer "não encontrei" para o resto. É o
comportamento certo. Teste:

1. `Hefesto, como eu identifico o tipo de ignição do meu Gol?`
   ✅ Esperado:
   - uma seção "Conhecimento geral" com orientação, **sem nenhum número**;
   - os avisos de segurança da ignição;
   - termina com uma pergunta (➜).
2. Responda o que ele perguntou, se souber. Se ele propuser anotar, teste o
   `sim` ou o `não`.
3. `qual o torque do cabeçote do AP 1.6?`
   ✅ "Não encontrei nas fontes", **sem chutar valor**.
4. `/rastro` mostra o comando para auditar a última resposta. Rode-o num
   **outro** terminal (lembre de `cd ~/hefesto` e `. .venv/bin/activate`).
5. `/sair` para sair.

**Anote quanto tempo cada resposta levou.** A primeira de cada sessão é mais
lenta, porque carrega o modelo no DOCKER e o reranker no ESTE.

> Se aparecer "Nenhum cérebro respondendo", rode `engenheiro status` e veja a
> Etapa 2.4.

---

## Etapa 5: alimentar com os livros

### 5.1 Onde põe os PDFs

Cada livro vai na pasta da **coleção** certa, dentro de `data/biblioteca/`:

| Coleção | O que vai nela |
|---|---|
| `veiculo` | Manual do proprietário e de reparação do Gol, esquemas elétricos do Gol |
| `carburacao_etanol` | Carburação, carburadores Weber/Brosol, etanol |
| `ignicao` | Ignição (platinado, eletrônica, Hall, bobina) |
| `eletrica_automotiva` | Elétrica automotiva em geral (Bosch, Denton etc.) |
| `eletronica` | Eletrônica geral (circuitos, componentes) |
| `mecanica_motor` | Mecânica do motor, motor AP |
| `sensores` | Sensores |
| `esp32` | Datasheet e manuais do ESP32 |
| `aquisicao_dados` | Aquisição de dados, telemetria |

```bash
mkdir -p data/biblioteca/{veiculo,carburacao_etanol,ignicao,eletrica_automotiva,eletronica,mecanica_motor,sensores,esp32,aquisicao_dados}
```

**Copiar do Windows para o WSL:** os arquivos do Windows aparecem em
`/mnt/c/`. Por exemplo, para um PDF na pasta Downloads (troque o nome de
usuário e o do arquivo):

```bash
cp "/mnt/c/Users/<SEU_USUARIO_WINDOWS>/Downloads/manual_gol.pdf" data/biblioteca/veiculo/
```

Copie em vez de apontar para `/mnt/c`: ler direto do disco do Windows é bem
mais lento.

### 5.2 A ficha de cada livro (recomendado)

Ao lado de cada PDF, crie um `.yaml` com o **mesmo nome**. Exemplo para
`data/biblioteca/veiculo/manual_gol.pdf`:

```bash
nano data/biblioteca/veiculo/manual_gol.yaml
```

```yaml
titulo: "Manual de Reparação Gol"
citacao: "Manual Gol"        # nome curto que aparece em [Manual Gol, p. 45]
idioma: pt
deslocamento_paginas: 0      # veja abaixo
```

O **`deslocamento_paginas`** faz a citação bater com a página impressa:
1. Abra o PDF numa página que tenha o número impresso.
2. Compare o número da folha no leitor de PDF com o número impresso. Ex.: a
   folha 67 do PDF mostra "45" impresso.
3. O deslocamento é a diferença: 67 − 45 = **22**.

Sem a ficha também funciona, mas a citação sai com o nome do arquivo e com
"p. X do PDF".

### 5.3 Comece com um livro só

Indexe primeiro **um** livro pequeno, para ver se está tudo certo:

```bash
engenheiro indexar --colecao veiculo
```

A primeira vez baixa os modelos de leitura de PDF (cerca de 500 MB). Ele
mostra "Extraindo ...", e depois "→ N trechos". Livro escaneado (só imagem) é
lido por OCR, que é bem mais lento.

Teste a busca, sem LLM e na hora:

```bash
engenheiro buscar "um assunto que você sabe que está nesse livro"
```

✅ O primeiro resultado é a seção certa, com livro e página. **Confira a página
no PDF**: se não bater, ajuste o `deslocamento_paginas` da ficha e rode
`engenheiro indexar` de novo (ele só refaz o que mudou e não relê o PDF).

E converse sobre o livro:

```bash
engenheiro conversar
```

✅ Agora as respostas trazem a seção "Das fontes", com `[Manual Gol, p. X]`.

### 5.4 O resto dos livros (deixe rodando)

Copie todos os PDFs e fichas para as pastas e rode, num terminal que vai
ficar aberto:

```bash
engenheiro indexar 2>&1 | tee data/indexacao.log
```

Pode levar horas. Pode interromper (`Ctrl+C`) e rodar de novo a qualquer
momento: ele continua de onde parou e não refaz o que já leu.

Para ver o andamento, de outro terminal:

```bash
engenheiro status
```

---

## Etapa 6: à noite, em casa (RYZEN)

### 6.1 Ollama no RYZEN

Repita a Etapa 1 no RYZEN (1.2, 1.3, 1.5 e 1.6), mas na 1.4 baixe:

```bash
ollama pull qwen3:8b
```

```bash
ollama pull qwen3:4b
```

Com 12 GB, use o 8B. O 14B fica para depois do upgrade de memória.

### 6.2 Avisar o ESTE

Já com o ESTE em casa, no Ubuntu dele:

```bash
cd ~/hefesto && . .venv/bin/activate
```

```bash
nano config.yaml
```

Descomente o bloco `ryzen` e ponha o IP do RYZEN (o da 1.5, feita no RYZEN).

```bash
engenheiro status
```

✅ `trabalho ... inacessível` (ficou no trabalho) e `ryzen ... respondendo ←
em uso agora`.

Pronto: a partir de agora, o Hefesto escolhe sozinho. No trabalho usa o
DOCKER; em casa, o RYZEN.

### 6.3 Comparar 14B × 8B (quando tiver as duas máquinas na mesma rede)

Ponha algumas perguntas reais em `data/usuario/avaliacao/perguntas.yaml` (ele
é criado na primeira avaliação; veja o [Manual](MANUAL.md), seção 9) e rode:

```bash
engenheiro avaliar --modo completo --cerebro trabalho
```

```bash
engenheiro avaliar --modo completo --cerebro ryzen
```

```bash
engenheiro comparar-relatorios <relatorio-ryzen>.json <relatorio-trabalho>.json
```

Os relatórios ficam em `data/usuario/avaliacao/relatorios/`.

---

## Etapa 7: tirar seus dados do notebook da empresa (depois)

Quando o homelab, ou o próprio RYZEN, for a casa definitiva do Hefesto:

```bash
engenheiro backup --completo
```

Isso gera `data/backups/hefesto-completo-....tar.gz`, com livros, índice, cache
de leitura, perfil, caderno e conversas. Copie para a máquina nova, instale o
Hefesto lá (Etapa 3) e restaure dentro da pasta do projeto:

```bash
tar -xzf hefesto-completo-<data>.tar.gz -C ~/hefesto
```

Depois, apague a pasta do Hefesto do ESTE.

---

## O que me mandar depois do teste

1. A saída do `engenheiro status`.
2. O tempo das primeiras respostas (Etapa 4) e se ele chutou algo que não
   devia.
3. Se a página citada bateu com o PDF (Etapa 5.3).
4. Qualquer erro, com a mensagem completa.
5. Ids de rastro de respostas estranhas (aparecem no fim de cada resposta).

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `wsl --install` pede permissão ou falha | Precisa de administrador; a TI pode ter bloqueado |
| "Nenhum cérebro respondendo" | Etapa 2.4 |
| `engenheiro: command not found` | `cd ~/hefesto && . .venv/bin/activate` |
| Leitura de PDF morre sem mensagem ("Killed") | Faltou memória: feche programas, ou aumente o `memory` do `.wslconfig` para 7 GB e rode `wsl --shutdown` |
| Muito lento | A primeira resposta carrega modelos; as seguintes são mais rápidas. Confira o `pensar: false` |
| Citação com a página errada | Ajuste o `deslocamento_paginas` na ficha e rode `engenheiro indexar` |
| Tudo vira "não encontrei" mesmo com o livro | `engenheiro buscar "..." --candidatos` e me mande a saída (pode ser o limiar de relevância) |
