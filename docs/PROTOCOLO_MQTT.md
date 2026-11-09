# Protocolo MQTT do Hefesto (Divine Machinery)

Este é o contrato para os outros personagens (e o assistente central)
conversarem com o Hefesto. Os nomes de tópico são configuráveis em
`config.yaml` (`mqtt.*`); `{id}` é `assistente.id` (padrão `engenheiro`).

## Tópicos

| Direção | Tópico | Retido | Conteúdo |
|---|---|---|---|
| entrada | `joao/fala/engenheiro` | não | pergunta ou fala para o Hefesto |
| saída | `npc/engenheiro/fala` | não | resposta |
| saída | `npc/engenheiro/status` | **sim** | estado atual (também é o Last Will) |
| saída | `npc/engenheiro/pensamento` | não | "pensando em voz alta" (mumbling), em texto |
| entrada | `carro/telemetria/<sinal>` | — | valores ao vivo do carro (para `ler_telemetria`) |

## Entrada: `joao/fala/engenheiro`

Texto puro:

```
onde fica a bobina?
```

ou JSON (recomendado para personagens):

```json
{"texto": "onde fica a bobina?", "id": "abc123", "de": "grilo"}
```

- `de`: quem está falando. **Cada interlocutor tem uma conversa própria, com
  memória.** O padrão é `"joao"`.
- `id`: devolvido em `em_resposta_a`, para você casar pergunta e resposta.
- Para responder às propostas de anotação, mande `"sim"` ou `"não"` com o
  mesmo `de`.

## Saída: `npc/engenheiro/fala`

```json
{
  "de": "engenheiro",
  "nome": "Hefesto",
  "para": "grilo",
  "em_resposta_a": "abc123",
  "texto": "versão CURTA, feita para ser falada",
  "texto_completo": "texto da tela, com seções, citações e avisos",
  "rastro_id": "20261107T174500Z-1a2b3c",
  "espera_resposta": true,
  "problemas_criticos": [],
  "conversa": "20261107-174500-ab12",
  "quando": "2026-11-07T17:45:00"
}
```

- `espera_resposta: true`: ele terminou com uma pergunta (modo guiado) ou
  pediu confirmação de uma anotação. A próxima fala do mesmo `de` é a
  resposta.
- `problemas_criticos`: se não estiver vazio, mostre ou fale ANTES de qualquer
  outra coisa (afirmação crítica reprovada ou não verificada, valor sem
  fonte, informação crítica só da web).
- `rastro_id`: auditoria completa em `GET /rastro/{id}` (API) ou
  `engenheiro rastro <id>`.
- Em caso de erro, vem `"erro"` e um `texto` dizendo que houve erro interno.

## Estado: `npc/engenheiro/status` (retido)

```json
{"estado": "online", "nome": "Hefesto", "id": "engenheiro", "quando": "..."}
```

| estado | significado |
|---|---|
| `online` | pronto |
| `pensando` | montando uma resposta (pode levar minutos em CPU) |
| `sem_cerebro` | o Ollama está fora: ele só aponta trechos, não responde. Volta sozinho quando o Ollama ligar |
| `offline` | desligado. Publicado na despedida e, se ele cair, pelo **broker** (Last Will) |

## Pensamento: `npc/engenheiro/pensamento`

```json
{"de": "engenheiro", "texto": "Deixa eu ver na parte de ignição..."}
```

Frases curtas geradas a partir dos passos reais da resposta (busca,
trechos achados, conta, verificação). Para desligar, use
`mqtt.topico_pensamento: ""`.

## Telemetria: `carro/telemetria/<sinal>`

O ESP32 do carro publica, por exemplo:

```
carro/telemetria/rpm          912
carro/telemetria/temp_motor   {"valor": 88.5, "unidade": "°C"}
```

O Hefesto guarda o último valor de cada sinal. A ferramenta `ler_telemetria`
devolve esse valor com a idade e **recusa** dado com mais de
`mqtt.telemetria_max_idade_s` segundos.

## Testando sem nenhum personagem

Num terminal, acompanhe tudo o que o Hefesto publica:

```bash
mosquitto_sub -h <broker> -t 'npc/engenheiro/#' -v
```

Em outro, mande uma pergunta:

```bash
mosquitto_pub -h <broker> -t joao/fala/engenheiro -m '{"texto": "onde fica a bobina?", "id": "t1"}'
```
