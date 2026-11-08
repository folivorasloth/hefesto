# Hefesto

Assistente pessoal de engenharia, no estilo JARVIS: mecânica, elétrica
automotiva e eletrônica embarcada (ESP32). Foco: o projeto de telemetria de um
**VW Gol CL 1994, motor AP 1.6, a etanol, carburado**. É um personagem do
ecossistema **Divine Machinery**.

Você conversa com ele por texto ou por voz ("Hefesto, como eu identifico o
tipo de ignição?"). Ele busca nos seus livros, faz as contas com ferramentas,
confere a própria resposta, guia você no carro passo a passo e aprende o que
você descobre, sempre com a sua confirmação.

## O princípio

> **Correção acima de tudo.** Prefiro "não encontrei" a uma resposta errada com
> confiança.

- Toda afirmação técnica tem fonte: `[Livro, p. X]` ou `[cálculo: ferramenta]`.
  A citação é montada pelo código, nunca escrita pelo modelo.
- Toda conta passa por uma ferramenta em Python, nunca pelo modelo.
- Um verificador confere cada afirmação contra a fonte citada, e o código
  confere cada número (valor e unidade). Problema em informação crítica
  (tensão, torque, combustível, segurança) aparece no topo.
- A resposta separa **fonte**, **inferência**, **conhecimento geral** (só para
  orientar onde olhar, nunca com valores) e **web** (não verificado).
- Toda resposta gera um rastro JSON auditável.
- Tudo roda localmente (Ollama). Web só pelo seu SearXNG, e só quando você
  pede.

## Documentação

| Documento | Para quê |
|---|---|
| [**Guia de instalação e testes**](docs/GUIA_INSTALACAO.md) | Instalar em cada máquina e testar tudo, passo a passo |
| [**Manual**](docs/MANUAL.md) | Usar: livros, conversa, voz, ferramentas, perfil, caderno, serviço, avaliação |
| [**Arquitetura**](docs/ARQUITETURA.md) | Como funciona, decisões e porquês, números medidos, limitações |
| [**Protocolo MQTT**](docs/PROTOCOLO_MQTT.md) | Contrato para os outros personagens do Divine Machinery |
| [Inventário](docs/INVENTARIO.md) | Componentes da bancada |
| [Seus dados e backup](docs/MANUAL.md#11-seus-dados-personalização-e-backup) | Onde ficam os seus dados, como personalizar e fazer backup |

## Comandos principais

| Comando | O que faz |
|---|---|
| `engenheiro conversar` | Conversa por texto, com memória e modo guiado |
| `engenheiro voz` | Conversa por voz ("Hefesto, ...", ou `--botao`) |
| `engenheiro perguntar "..."` | Pergunta avulsa |
| `engenheiro rastro <id>` | Por que ele respondeu o que respondeu |
| `engenheiro indexar` | Indexa os livros de `data/biblioteca/` (incremental) |
| `engenheiro buscar "..."` | Busca nos livros, sem LLM, com scores |
| `engenheiro ferramenta <nome> k=v` | Calculadoras (Ohm, divisor, fio, fusível, pinos do ESP32...) |
| `engenheiro anotar "..."` / `caderno` | Caderno de bordo |
| `engenheiro perfil` / `perfil definir` | O que ele sabe do carro (confirmado × suposição) |
| `engenheiro inventario` | O que você tem na bancada |
| `engenheiro servir` | API HTTP + MQTT (Divine Machinery) |
| `engenheiro avaliar --modo ...` | Mede a qualidade e compara com a execução anterior |
| `engenheiro status` | Ollama, modelos e índice |
| `engenheiro personalizar` / `backup` | Ajustar arquivos de referência; guardar os seus dados |

## Estado

| Fase | Conteúdo | Estado |
|---|---|---|
| 1 | Ingestão (Docling + OCR), corte por seção, busca híbrida, reranker | pronta |
| 2 | Respostas com citação e verificador, segurança, rastro | pronta |
| 3 | Ferramentas, pinos do ESP32, perfil, caderno, web | pronta |
| Conversa | Memória, modo guiado, conhecimento geral rotulado, aprendizado com confirmação | pronta |
| 4 | Avaliação completa (busca, respostas, cenários de conversa) | pronta |
| 5 | Voz: ativação, Whisper, Piper, mumbling, interrupção, modo dirigindo | pronta |
| 6 | API HTTP, MQTT com Last Will, telemetria ao vivo | pronta |

Os 189 testes automáticos passam, inclusive os que rodam Docling, reranker,
voz e Mosquitto de verdade. O que ainda falta validar na sua máquina, com o
modelo de linguagem real, o microfone da garagem e os seus livros, está no
[guia](docs/GUIA_INSTALACAO.md) e nas
[limitações](docs/ARQUITETURA.md#10-limitações-conhecidas).
