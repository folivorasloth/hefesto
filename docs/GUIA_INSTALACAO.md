# Guia de instalação, configuração e testes do Hefesto

Este guia leva do zero até o Hefesto conversando por voz na garagem, testando
cada parte no caminho. Siga na ordem: cada etapa confirma que a anterior
funcionou. O que fazer com o Hefesto depois de instalado está no
[Manual](MANUAL.md).

> Quer testar hoje, nos notebooks (incluindo Windows/WSL)? Use o roteiro curto
> [Primeiros passos](PRIMEIROS_PASSOS.md). Este guia é o completo, com o homelab.

**Onde roda cada coisa:**

| Máquina | O que roda |
|---|---|
| **Notebook do LLM** (i7 10ª, 16 GB) | Ollama com os modelos |
| **Máquina do Hefesto** (notebook pessoal na garagem, ou o próprio notebook do LLM) | O programa `engenheiro`: índice, busca, voz, API, MQTT |
| **Homelab** (Docker) | Mosquitto (já existe) e SearXNG (opcional, para busca na web) |

Os comandos assumem **Linux (Ubuntu/Debian)**. Em Windows, use o WSL2 (não
testado; a voz pelo WSL exige configuração de áudio à parte).

> Onde aparecer `<IP-DO-NOTEBOOK-LLM>`, `<IP-DO-HOMELAB>` e semelhantes, use o
> endereço da sua rede. Nenhum endereço fica no código: tudo vai para o
> `config.yaml`, que fica fora do git.

---

## Sua divisão de máquinas (recomendada)

| Máquina | Papel | O que instalar |
|---|---|---|
| **Homelab** (i5-4670, 16 GB, SSD 500 GB + HD 2 TB), 24 h | **Base**: serviço do Hefesto (API + MQTT), livros, índice, caderno, perfil, Mosquitto, SearXNG, leitura de PDF de madrugada, backups no HD | Parte 1 com **só o `bge-m3`**; Parte 2 (sem o extra `voz`); Partes 3 e 5 |
| **Notebook do trabalho** (i5-1334U, 16 GB), enquanto você o tiver | **Cérebro preferido**: `qwen3:14b` + `qwen3:4b` | Só a Parte 1 (Ollama). Nada seu fica nele |
| **Ryzen 7 5700U** (12 GB; até 20 GB) | **Cérebro reserva/definitivo** (`qwen3:8b`; `qwen3:14b` depois do upgrade para 20 GB) e **voz na garagem** | Parte 1 (Ollama) e Parte 2 só com os extras `voz,servico` |

Como as peças conversam:
- O serviço no homelab usa o primeiro cérebro que estiver ligado, nessa
  ordem: notebook do trabalho, depois o Ryzen.
- A busca semântica usa o `bge-m3` do próprio homelab, então funciona com os
  dois notebooks desligados.
- Na garagem, o Ryzen só ouve e fala (`engenheiro voz --servidor`): livros,
  índice e memória ficam no homelab.

No `config.yaml` **do homelab**:

```yaml
ollama:
  url_embeddings: http://localhost:11434      # o Ollama do próprio homelab, com o bge-m3
  cerebros:                                   # ordem = preferência
    - nome: trabalho
      url: http://<IP-NOTEBOOK-TRABALHO>:11434
      modelos: {forte: "qwen3:14b"}
    - nome: ryzen
      url: http://<IP-RYZEN>:11434
      modelos: {forte: "qwen3:8b"}            # "qwen3:14b" depois do upgrade de RAM
mqtt:
  host: "localhost"
```

No dia em que você sair da empresa, apague o bloco `trabalho` e desinstale o
Ollama do notebook. Nenhum dado seu fica lá.

Na **garagem** (Ryzen), o Hefesto não precisa de índice nem de livros. O
`config.yaml` de lá só precisa do MQTT, para o "pensar em voz alta":

```yaml
mqtt:
  host: "<IP-DO-HOMELAB>"
```

Por padrão a API só atende a própria máquina. Para o homelab atender as
outras, abra a API no `config.yaml` **do homelab** e defina o token (sem
token, o `engenheiro servir` se recusa a abrir a API para a rede):

```yaml
api:
  host: 0.0.0.0
```

```bash
export HEFESTO_API_TOKEN="$(openssl rand -hex 24)"
```

Nas máquinas clientes, defina `HEFESTO_API_TOKEN` com o mesmo valor. A
conversa por voz aponta para o homelab:

```bash
engenheiro voz --servidor http://<IP-DO-HOMELAB>:8765
```

Para conversar por texto, de qualquer máquina:

```bash
engenheiro conversar --servidor http://<IP-DO-HOMELAB>:8765
```

**Decidir entre 8B e 14B com dados**, enquanto você ainda tem o notebook do
trabalho:

```bash
engenheiro avaliar --modo completo --cerebro trabalho
```

```bash
engenheiro avaliar --modo completo --cerebro ryzen
```

```bash
engenheiro comparar-relatorios <relatorio-ryzen>.json <relatorio-trabalho>.json
```

Se o 14B acertar claramente mais, vale o upgrade do Ryzen para 20 GB (troque o
pente de 8 GB por um de 16 GB DDR4-3200 SODIMM) antes de sair da empresa. Se
empatar, o Ryzen como está basta.

---

## Parte 1: notebook do LLM (Ollama)

### 1.1 Instalar o Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 1.2 Deixar o Ollama acessível na rede

Por padrão, o Ollama só aceita conexões da própria máquina. Abra a
configuração do serviço:

```bash
sudo systemctl edit ollama
```

Cole isto e salve:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
Environment="OLLAMA_KEEP_ALIVE=30m"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
```

- `OLLAMA_KEEP_ALIVE=30m` mantém os modelos na memória entre perguntas.
  Recarregar o modelo de 14B leva dezenas de segundos na CPU.
- `OLLAMA_MAX_LOADED_MODELS=2` deixa o modelo forte e o rápido carregados
  juntos. **Se o Hefesto rodar neste mesmo notebook**, use `1`: os 16 GB não
  comportam os dois modelos mais o reranker e o Docling. O preço é a troca de
  modelo, que fica mais lenta.

Reinicie o serviço:

```bash
sudo systemctl restart ollama
```

Se usar firewall, libere a porta só para a sua rede local (troque pela faixa
da sua rede):

```bash
sudo ufw allow from 192.168.0.0/24 to any port 11434
```

### 1.3 Baixar os modelos

```bash
ollama pull bge-m3
```

```bash
ollama pull qwen3:4b
```

```bash
ollama pull qwen3:14b
```

O `qwen2.5vl:7b` (descrição de figuras dos livros) é opcional. Só baixe se for
ligar `ingestao.figuras.descrever_com_visao`:

```bash
ollama pull qwen2.5vl:7b
```

### 1.4 Testar

Da **máquina do Hefesto**, confira se o Ollama responde:

```bash
curl http://<IP-DO-NOTEBOOK-LLM>:11434/api/tags
```

✅ **Esperado:** um JSON com os modelos baixados.

---

## Parte 2: máquina do Hefesto

### 2.1 Pacotes do sistema

```bash
sudo apt update
```

```bash
sudo apt install -y git python3 python3-venv python3-dev tesseract-ocr tesseract-ocr-por tesseract-ocr-eng libportaudio2 mosquitto-clients
```

Precisa de Python **3.12 ou mais novo**. Confira com `python3 --version`.
O Ubuntu 24.04 já vem com o 3.12. Várias bibliotecas usadas (numpy, scipy,
pint) não têm mais versão para o 3.11.

Se a sua distribuição tiver um Python mais antigo (Ubuntu 22.04, Debian 12), o
jeito mais simples é o `uv`, que baixa um Python 3.12 só para o projeto:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
uv python install 3.12
```

Depois, na etapa 2.3, crie o ambiente com `uv venv --python 3.12 .venv` em
vez de `python3 -m venv .venv`.

### 2.2 Baixar o projeto

```bash
git clone https://github.com/folivorasloth/hefesto
```

```bash
cd hefesto
```

> Se o pull request com o projeto ainda não tiver sido juntado na `main`, clone
> o branch dele: `git clone -b dados-versoes-ci https://github.com/folivorasloth/hefesto`.

### 2.3 Ambiente Python

```bash
python3 -m venv .venv
```

```bash
. .venv/bin/activate
```

**Economize alguns GB:** sem isto, o pip baixa a versão do PyTorch para placas
NVIDIA, que é enorme. Sem GPU, instale antes a versão só para CPU:

```bash
pip install torch==2.15.0 torchvision==0.29.2 --index-url https://download.pytorch.org/whl/cpu
```

Instale o Hefesto com todos os extras, usando as **versões exatas que passaram
nos testes** (`requisitos/testados.txt`). Sem o `-c`, o pip pega as mais novas
de cada biblioteca, que podem ter mudado de comportamento:

```bash
pip install -e ".[ingestao,reranker,voz,servico,dev]" -c requisitos/testados.txt
```

| Extra | Para quê | Pode deixar de fora se... |
|---|---|---|
| `ingestao` | Ler PDFs (Docling, OCR) | Outra máquina indexa e você copia o `data/indice.sqlite` |
| `reranker` | Reordenar a busca (bge-reranker) | **Não deixe:** sem ele, o "não encontrei" perde o limiar |
| `voz` | Microfone, Whisper, Piper | Não for usar voz nesta máquina |
| `servico` | API HTTP e MQTT | Não for usar `engenheiro servir` |
| `dev` | Testes | — |

Se faltar um extra, o comando avisa exatamente o que instalar.

### 2.4 Configuração

```bash
cp config.example.yaml config.yaml
```

Abra o `config.yaml`. Todas as opções estão comentadas nele. Para começar, só
estas importam:

```yaml
ollama:
  url: http://<IP-DO-NOTEBOOK-LLM>:11434

mqtt:
  host: "<IP-DO-HOMELAB>"      # seu Mosquitto; deixe "" para não usar MQTT ainda
  usuario: ""                  # se o seu Mosquitto exige usuário

web:
  searxng_url: ""              # preencha na Parte 3, se for usar busca na web
```

Senhas e tokens **não** vão no arquivo. Vão em variáveis de ambiente:

```bash
export HEFESTO_API_TOKEN="$(openssl rand -hex 24)"
```

```bash
export HEFESTO_MQTT_SENHA="senha-do-mosquitto"
```

Para elas valerem em todo terminal, ponha as duas linhas no `~/.bashrc` (ou
use o arquivo de ambiente do serviço, na Parte 5). O token da API é gerado
aleatoriamente: guarde o valor, porque outros clientes vão precisar dele.

### 2.5 Voz em português

```bash
python -m piper.download_voices --download-dir data/vozes pt_BR-faber-medium
```

### 2.6 Testar

```bash
engenheiro status
```

✅ **Esperado:** "Ollama ... disponível" e cada modelo como "instalado". O
índice ainda não existe, e isso é normal agora.

---

## Parte 3 (opcional): homelab

### 3.1 SearXNG (busca na web)

No homelab, dentro de uma cópia do projeto (ou copie só a pasta
`docker/searxng`):

```bash
cd docker/searxng && cp settings.example.yml settings.yml
```

Gere uma chave e cole no campo `secret_key` do `settings.yml`:

```bash
openssl rand -hex 32
```

```bash
docker compose up -d
```

Teste (o formato JSON precisa responder):

```bash
curl "http://<IP-DO-HOMELAB>:8888/search?q=ESP32&format=json" | head -c 300
```

Depois, no `config.yaml` da máquina do Hefesto: `web.searxng_url:
"http://<IP-DO-HOMELAB>:8888"`.

### 3.2 Mosquitto

Você já tem. Se ele usa ACL (lista de permissões por tópico), o usuário do
Hefesto precisa de:
- **ler** `joao/fala/engenheiro` e `carro/telemetria/#`;
- **escrever** `npc/engenheiro/#`.

O protocolo completo está em [PROTOCOLO_MQTT.md](PROTOCOLO_MQTT.md).

---

## Parte 4: testes, do mais simples ao completo

Em cada etapa, compare com o ✅ esperado. Se algo divergir, anote o que
apareceu e o id do rastro, quando houver.

### T1. Testes automáticos (sem Ollama, alguns segundos)

```bash
pytest
```

✅ Cerca de 190 testes passando. Os de MQTT rodam se o `mosquitto` estiver
instalado na máquina (`sudo apt install mosquitto` só para o teste; não
precisa deixar o serviço ativo). Senão, são pulados.

Testes lentos (Docling, reranker, voz reais; baixam modelos na primeira vez):

```bash
HEFESTO_VOZ_TESTE=data/vozes/pt_BR-faber-medium.onnx pytest -m ""
```

✅ Cerca de 206 testes passando.

### T2. Busca no corpus de teste (sem LLM)

Gera PDFs **fictícios** (marcados como "TEXTO DE TESTE") e indexa. Na
primeira vez, baixa os modelos do Docling (~500 MB) e do reranker (~2,2 GB):

```bash
engenheiro corpus-teste
```

```bash
engenheiro indexar --biblioteca data/teste --indice data/teste.sqlite
```

```bash
engenheiro buscar --indice data/teste.sqlite "como regular a marcha lenta?"
```

✅ O primeiro trecho é "1 Motor > 1.2 Regulagem da marcha lenta", com score do
reranker perto de 1, e o procedimento de 10 passos inteiro, com o aviso de
ventilação junto.

```bash
engenheiro avaliar --perguntas eval/perguntas_corpus_teste.yaml --indice data/teste.sqlite
```

✅ `acerto@6` = 1.0. Anote `score_rerank_min_dos_acertos` e
`score_rerank_max_fora_da_base`.

### T3. Respostas com o modelo real

```bash
engenheiro perguntar --indice data/teste.sqlite "qual o torque de aperto do cabeçote?"
```

✅ Esperado:
- seção "Das fontes" com 17,3 N·m e 41,7 N·m (valores **fictícios** do corpus
  de teste) e citação `[manual_ficticio_gol, p. 1 do PDF]`;
- nenhum "⚠ VERIFICAÇÃO" no topo;
- leva alguns minutos na CPU.

```bash
engenheiro rastro <id-mostrado-no-fim>
```

✅ A tabela de verificação mostra cada afirmação com o veredito `suporta`.

```bash
engenheiro avaliar --modo resposta --perguntas eval/perguntas_corpus_teste.yaml --indice data/teste.sqlite
```

✅ Esperado:
- `fonte_aprovada` = 1.0 e `nao_sei_correto` = 1.0;
- `falso_nao_sei` perto de 0;
- `segundos_medio`: é o número que diz se a GPU faz falta.

**Me mande o relatório** (`data/usuario/avaliacao/relatorios/*.md`) dessa etapa.

### T4. Conversa (modo JARVIS)

```bash
engenheiro conversar --nova
```

Converse:
1. `Hefesto, como eu identifico o tipo de ignição do meu Gol?`
   ✅ Seção "Conhecimento geral" com orientação de onde olhar (sem nenhum
   número), terminando com uma pergunta (➜).
2. Responda o que você vê de verdade no carro, por exemplo
   `tem três fios no conector`.
   ✅ Ele continua o raciocínio e pergunta se pode anotar.
3. `sim`
   ✅ "Anotado". Confira com `/perfil`.

```bash
engenheiro avaliar --modo cenarios
```

✅ `cenarios_ok` = 1.0. Os cenários usam uma cópia do perfil e não mexem no
seu.

### T5. Ferramentas, perfil, caderno e inventário (sem LLM)

```bash
engenheiro ferramenta escolher_divisor vin_max_v=16 vout_max_v=3.3
```

✅ Pares de resistores **do seu kit** (ex.: 20 kΩ + 4,7 kΩ), com o pior caso
abaixo de 3,3 V.

```bash
engenheiro ferramenta verificar_pinos_esp32 pinos='[G34]' uso=saida_digital
```

✅ `pode_usar: false` (o G34 é só de entrada).

```bash
engenheiro anotar -t "Bateria em repouso" --tag bateria "Medi 12,6 V com o motor desligado"
```

Troque pelo valor que **você** mediu com o multímetro.

```bash
engenheiro caderno bateria
```

```bash
engenheiro inventario --pendencias
```

### T6. Voz

Primeiro o alto-falante e o microfone:

```bash
engenheiro audio falar
```

✅ Você ouve "Olá, eu sou o Hefesto...".

```bash
engenheiro audio ouvir
```

Diga "Hefesto, onde fica a bobina?". ✅ A transcrição aparece com "Palavra de
ativação: sim".

Depois, conversa por voz. Comece com o botão (Enter e fale), que é o mais
confiável:

```bash
engenheiro voz --botao
```

Depois, com a palavra de ativação:

```bash
engenheiro voz
```

✅ Esperado:
- ele fala baixinho o que está fazendo ("deixa eu ver...") enquanto pensa;
- responde falando;
- quando termina com uma pergunta, ouve a sua resposta **sem** você dizer
  "Hefesto";
- dizer "Hefesto" enquanto ele fala o interrompe.

Teste também "modo dirigindo" e "parei". Se o barulho atrapalhar, veja
"Ajustes para a garagem" no [Manual](MANUAL.md).

### T7. Serviço: API e MQTT

Em um terminal:

```bash
engenheiro servir
```

Em outro, a API:

```bash
curl http://localhost:8765/status
```

```bash
curl -X POST http://localhost:8765/conversas/joao/turno -H "Authorization: Bearer $HEFESTO_API_TOKEN" -H "Content-Type: application/json" -d '{"fala": "onde fica a bobina?"}'
```

A documentação interativa fica em `http://localhost:8765/docs`. Para acessar
de outra máquina, use `api.host: 0.0.0.0` no config; nesse caso o token é
obrigatório.

Agora o MQTT. Num terminal, acompanhe tudo o que o Hefesto publica:

```bash
mosquitto_sub -h <IP-DO-HOMELAB> -u <usuario> -P "$HEFESTO_MQTT_SENHA" -t 'npc/engenheiro/#' -v
```

Em outro, mande uma pergunta:

```bash
mosquitto_pub -h <IP-DO-HOMELAB> -u <usuario> -P "$HEFESTO_MQTT_SENHA" -t joao/fala/engenheiro -m '{"texto": "onde fica a bobina?", "id": "t1"}'
```

✅ Esperado, nesta ordem:
- `status` → `pensando`;
- frases em `pensamento`;
- a resposta em `fala`, com `"em_resposta_a": "t1"`;
- `status` volta a `online`.

Simule a telemetria do carro:

```bash
mosquitto_pub -h <IP-DO-HOMELAB> -u <usuario> -P "$HEFESTO_MQTT_SENHA" -t carro/telemetria/rpm -m 912
```

E, em até 10 s, pergunte pela API ou pelo MQTT: "qual a rotação agora?".
✅ Ele chama a ferramenta `ler_telemetria`.

**Last Will:** mate o serviço sem despedida, com `kill -9` no processo.
✅ O broker publica `offline` em `npc/engenheiro/status`.

### T8. Seus livros (pode rodar à noite)

1. Coloque os PDFs em `data/biblioteca/<coleção>/` e crie a ficha `.yaml` de
   cada um (título, nome curto para citação, deslocamento de página). Veja o
   [Manual](MANUAL.md), seção 1. Comece pelo manual do Gol e pelo datasheet
   do ESP32, que a Espressif publica.
2. Indexe:

   ```bash
   engenheiro indexar
   ```

3. Preencha `data/usuario/avaliacao/perguntas.yaml` (criado na primeira
   avaliação) com perguntas reais. Inclua algumas cuja
   resposta **não** está nos livros.
4. Rode a avaliação completa:

   ```bash
   engenheiro avaliar --modo completo
   ```

5. Ajuste `busca.limiar_relevancia` entre `score_rerank_min_dos_acertos` e
   `score_rerank_max_fora_da_base`, mais perto do segundo.
6. Com o datasheet do ESP32 indexado, confira `dados_ref/esp32_pinos.yaml` e
   mude o `status` para `confirmado`.

### O que me mandar de volta

- os relatórios de `data/usuario/avaliacao/relatorios/` (T2, T3, T4 e T8);
- 2 ou 3 ids de rastro de respostas que pareceram estranhas (o JSON fica em
  `data/rastros/`);
- quanto tempo cada resposta levou e como foi a voz na garagem.

---

## Parte 5: deixar rodando sozinho (systemd)

Para o Hefesto subir junto com a máquina e ficar no MQTT. Crie o arquivo de
ambiente, só legível por você:

```bash
mkdir -p ~/.config/hefesto
```

```bash
printf 'HEFESTO_API_TOKEN=%s\nHEFESTO_MQTT_SENHA=%s\n' "$HEFESTO_API_TOKEN" "$HEFESTO_MQTT_SENHA" > ~/.config/hefesto/ambiente
```

```bash
chmod 600 ~/.config/hefesto/ambiente
```

Crie `~/.config/systemd/user/hefesto.service`, trocando o caminho pelo da sua
cópia do projeto:

```ini
[Unit]
Description=Hefesto (engenheiro)
After=network-online.target

[Service]
WorkingDirectory=/home/SEU_USUARIO/hefesto
EnvironmentFile=/home/SEU_USUARIO/.config/hefesto/ambiente
ExecStart=/home/SEU_USUARIO/hefesto/.venv/bin/engenheiro servir
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
```

```bash
systemctl --user enable --now hefesto
```

Para acompanhar o log:

```bash
journalctl --user -u hefesto -f
```

Para continuar rodando depois do logout:

```bash
sudo loginctl enable-linger $USER
```

### Backup automático diário

Abra o agendador:

```bash
crontab -e
```

Acrescente esta linha (todo dia às 3h; troque o caminho pelo da sua cópia e,
se quiser, o destino por uma pasta do homelab):

```
0 3 * * * cd /home/SEU_USUARIO/hefesto && .venv/bin/engenheiro backup --destino /home/SEU_USUARIO/backups-hefesto
```

Isso guarda o que não dá para recriar: perfil, inventário, caderno, conversas,
avaliações e config. De vez em quando, rode também `engenheiro backup
--completo` (livros, índice e cache, que levam noites para reprocessar).

---

## Parte 6: velocidade

Em ordem de efeito, do maior para o menor:

1. **GPU** (veja a conversa sobre hardware): leva cada resposta de minutos para
   dezenas de segundos. É o único salto grande.
2. **Modelo mantido na memória:** o Hefesto já pede ao Ollama que mantenha o
   modelo carregado por 30 minutos (`ollama.manter_carregado`). No notebook do
   cérebro, use também `OLLAMA_KEEP_ALIVE=30m` (Parte 1.2). Recarregar um 14B do
   disco leva dezenas de segundos.
3. **Modelos no SSD,** nunca no HD.
4. **`geracao.pensar: false`** no config, para o qwen3: menos texto gerado antes
   da resposta.
5. **Opções do Ollama para testar** (no `systemctl edit ollama`, como na Parte
   1.2). Cada uma pode ajudar ou não, conforme a máquina: meça antes e depois
   com `engenheiro avaliar`.
   - `Environment="OLLAMA_FLASH_ATTENTION=1"`
   - `Environment="OLLAMA_KV_CACHE_TYPE=q8_0"` (o contexto ocupa metade da
     memória; só funciona junto com a anterior)
6. **Menos candidatos no reranker** (`busca.candidatos_rerank`): o padrão de 15
   já é enxuto. Abaixo disso, confira na avaliação se a fonte certa não está
   ficando de fora (`fonte_recuperada_mas_cortada_no_rerank`).
7. **Modo conversa:** pergunta de orientação ("onde fica", "como identifico")
   já vai para o modelo rápido, sem etapa de ferramentas.

O que **não** muda: o verificador e a checagem de números rodam sempre. Velocidade
nunca é comprada com uma resposta menos conferida.

---

## Solução de problemas

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `Ollama inacessível` | IP errado, `OLLAMA_HOST` não aplicado, firewall | `curl http://<IP>:11434/api/tags` da máquina do Hefesto; Parte 1.2 |
| `modelo ... faltando` no `status` | Modelo não baixado | `ollama pull <modelo>` no notebook do LLM |
| `índice usa o embedder X` | Índice criado com outro embedder (ex.: `--embedder-falso`) | Apague o `.sqlite` e reindexe |
| `precisa do pacote ...` | Extra do pip faltando | Rode o comando que a mensagem mostra |
| Resposta "sem o modelo de linguagem" | Ollama fora agora | Ele volta sozinho quando o Ollama responder |
| Tudo vira "não encontrei" | Limiar alto demais ou base sem o assunto | `engenheiro buscar "..." --candidatos` para ver os scores; ajuste o limiar |
| `O prompt pode ter sido truncado` | Contexto maior que `num_ctx` | Aumente `geracao.num_ctx` (gasta mais RAM) ou reduza `max_trechos_contexto` |
| Respostas muito lentas | CPU | Parte 6 |
| Voz não ouve nada | Microfone padrão errado ou VAD agressivo | `engenheiro audio ouvir`; `voz.agressividade_vad: 1` |
| Voz dispara com barulho | VAD sensível | `voz.agressividade_vad: 3`, ou `engenheiro voz --botao` |
| SearXNG `403` | JSON desabilitado | `search.formats: [html, json]` no `settings.yml` |
| MQTT não conecta | Host, usuário, senha ou ACL | `mosquitto_sub` com as mesmas credenciais; Parte 3.2 |
