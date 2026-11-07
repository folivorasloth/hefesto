"""Carregamento da configuração (config.yaml) com validação.

Por que pydantic: um erro de digitação no YAML (ex.: `max_caracteres: "2400a"`)
deve falhar na hora, com mensagem clara, e não virar um comportamento estranho
no meio de uma indexação noturna.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Assistente(BaseModel):
    id: str = "engenheiro"
    # Nome, tom e exemplos ficam no arquivo de persona (editável).
    persona: Path = Path("persona/engenheiro.yaml")


class Caminhos(BaseModel):
    biblioteca: Path = Path("data/biblioteca")
    indice: Path = Path("data/indice.sqlite")
    cache: Path = Path("data/cache")
    figuras: Path = Path("data/figuras")
    rastros: Path = Path("data/rastros")


class ModelosOllama(BaseModel):
    embeddings: str = "bge-m3"
    rapido: str = "qwen3:4b"
    forte: str = "qwen3:14b"
    visao: str = "qwen2.5vl:7b"


class Ollama(BaseModel):
    url: str = "http://localhost:11434"
    timeout_s: float = 900
    modelos: ModelosOllama = Field(default_factory=ModelosOllama)


class Ocr(BaseModel):
    ativo: bool = True
    idiomas: list[str] = ["por", "eng"]
    limiar_caracteres_pagina: int = 30


class Figuras(BaseModel):
    salvar_imagens: bool = True
    descrever_com_visao: bool = False


class Corte(BaseModel):
    max_caracteres: int = Field(2400, gt=200)
    sobreposicao_caracteres: int = Field(300, ge=0)


class Ingestao(BaseModel):
    ocr: Ocr = Field(default_factory=Ocr)
    figuras: Figuras = Field(default_factory=Figuras)
    corte: Corte = Field(default_factory=Corte)
    embeddings_lote: int = 16


class Reranker(BaseModel):
    ativo: bool = True
    modelo: str = "BAAI/bge-reranker-v2-m3"
    max_tokens: int = 1024
    dispositivo: str = "cpu"


class Busca(BaseModel):
    candidatos_por_lista: int = 30
    # Custo do reranker em CPU cresce linear com isto (ver config.example.yaml).
    candidatos_rerank: int = 15
    final: int = 6
    rrf_k: int = 60
    roteamento: str = "palavras_chave"
    reranker: Reranker = Field(default_factory=Reranker)
    # Trecho com score do reranker abaixo disso não vai para o LLM. Se nenhum
    # passar, a resposta é "não encontrei". Valor PROVISÓRIO: calibre com
    # `engenheiro avaliar` (compare score_rerank_min_dos_acertos com
    # score_rerank_max_fora_da_base) depois de indexar seus livros.
    limiar_relevancia: float = Field(0.10, ge=0, le=1)
    # Pontua cada trecho também contra a tradução da pergunta para o inglês
    # (gerada pelo modelo rápido) e fica com o maior score. Medido no corpus de
    # teste: pergunta em PT x trecho em EN = 0,06; a tradução = 0,998.
    rerank_com_traducao: bool = True


class Geracao(BaseModel):
    # Janela de contexto pedida ao Ollama. O padrão do Ollama é pequeno e,
    # quando o prompt passa dele, o começo é cortado SEM aviso. Aqui o código
    # estima o tamanho do prompt e descarta trechos de menor score, avisando.
    num_ctx: int = 12288
    temperatura: float = 0.0
    # None = não envia o parâmetro "think" (comportamento padrão do modelo).
    # Para qwen3: false deixa bem mais rápido; true pode raciocinar melhor.
    pensar: bool | None = None
    max_trechos_contexto: int = 8


class Verificador(BaseModel):
    ativo: bool = True


class Ferramentas(BaseModel):
    ativo: bool = True
    # Rodadas de chamada de ferramenta antes da resposta (cada rodada é uma
    # chamada ao modelo forte; em CPU, cada uma custa tempo).
    max_rodadas: int = 4


class Ativacao(BaseModel):
    # "transcricao": transcreve trechos de fala e procura a palavra no começo
    #   (funciona já, sem treinar nada; gasta mais CPU).
    # "openwakeword": detector dedicado (leve). Precisa de um modelo da
    #   palavra; para "Hefesto" ele tem que ser treinado (ver README).
    # "botao": só botão de falar (Enter no terminal).
    modo: str = "transcricao"
    palavra: str = "Hefesto"
    modelo_openwakeword: str = ""          # caminho do .onnx/.tflite treinado
    limiar_openwakeword: float = 0.5
    modelo_whisper_ativacao: str = "tiny"  # modelo pequeno só para achar a palavra


class Voz(BaseModel):
    whisper_modelo: str = "small"          # tiny/base/small/medium: maior = melhor e mais lento
    whisper_compute_type: str = "int8"
    dispositivo: str = "cpu"
    piper_voz: Path = Path("data/vozes/pt_BR-faber-medium.onnx")
    velocidade_fala: float = 1.0           # >1 fala mais devagar (length_scale do Piper)
    volume: float = 1.0
    mumbling: bool = True
    volume_mumbling: float = 0.45
    intervalo_minimo_mumbling_s: float = 4.0
    silencio_fim_fala_ms: int = 900        # silêncio que encerra a sua fala
    duracao_max_fala_s: float = 20.0
    janela_resposta_s: float = 8.0         # depois que ele pergunta algo, ouve sem palavra de ativação
    agressividade_vad: int = 2             # 0-3: maior ignora mais ruído (garagem: 2 ou 3)
    ativacao: Ativacao = Field(default_factory=Ativacao)


class Api(BaseModel):
    host: str = "0.0.0.0"
    porta: int = 8765
    # Token opcional (recomendado na rede de casa também). Prefira a variável
    # de ambiente HEFESTO_API_TOKEN a escrever o token aqui.
    token: str = ""


class Mqtt(BaseModel):
    ativo: bool = True
    host: str = ""                 # endereço do Mosquitto; vazio = MQTT desligado
    porta: int = 1883
    usuario: str = ""              # senha: variável de ambiente HEFESTO_MQTT_SENHA
    qos: int = 1
    # {id} vira assistente.id ("engenheiro").
    topico_fala: str = "npc/{id}/fala"
    topico_status: str = "npc/{id}/status"
    topico_entrada: str = "joao/fala/{id}"
    topico_pensamento: str = "npc/{id}/pensamento"   # mumbling em texto ("" = não publica)
    # Telemetria do carro: valores publicados abaixo deste prefixo ficam
    # disponíveis para a ferramenta ler_telemetria (ex.: carro/telemetria/rpm).
    telemetria_prefixo: str = "carro/telemetria/"
    telemetria_max_idade_s: float = 10.0


class Web(BaseModel):
    # URL do seu SearXNG (ver docker/searxng/). Vazio = busca web desligada.
    searxng_url: str = ""
    # "pedido": só quando a pergunta pede (web, internet, pesquise online...);
    # "sem_fontes": também quando a base não tem nada relevante; "nunca".
    modo: str = "pedido"
    maximo_resultados: int = 5


COLECOES_PADRAO = [
    "veiculo",
    "carburacao_etanol",
    "ignicao",
    "eletrica_automotiva",
    "eletronica",
    "mecanica_motor",
    "sensores",
    "esp32",
    "aquisicao_dados",
    "caderno_de_bordo",
]


class Config(BaseModel):
    assistente: Assistente = Field(default_factory=Assistente)
    caminhos: Caminhos = Field(default_factory=Caminhos)
    ollama: Ollama = Field(default_factory=Ollama)
    colecoes: list[str] = Field(default_factory=lambda: list(COLECOES_PADRAO))
    colecoes_sempre: list[str] = Field(default_factory=lambda: ["veiculo", "caderno_de_bordo"])
    ingestao: Ingestao = Field(default_factory=Ingestao)
    busca: Busca = Field(default_factory=Busca)
    geracao: Geracao = Field(default_factory=Geracao)
    verificador: Verificador = Field(default_factory=Verificador)
    ferramentas: Ferramentas = Field(default_factory=Ferramentas)
    web: Web = Field(default_factory=Web)
    voz: Voz = Field(default_factory=Voz)
    api: Api = Field(default_factory=Api)
    mqtt: Mqtt = Field(default_factory=Mqtt)
    perfil_veiculo: Path = Path("perfil_veiculo.yaml")

    # Pasta raiz do projeto (onde fica o config.yaml e dados_ref/).
    raiz: Path = Path(".")

    def caminho(self, p: Path) -> Path:
        """Resolve um caminho do config relativo à pasta do config.yaml."""
        return p if p.is_absolute() else (self.raiz / p)

    @property
    def dados_ref(self) -> Path:
        return self.raiz / "dados_ref"


def _normalizar_url_ollama(valor: str) -> str:
    # OLLAMA_HOST costuma vir como "maquina:11434", sem esquema. O próprio
    # Ollama aceita assim, então aceitamos também.
    valor = valor.strip().rstrip("/")
    if not valor.startswith(("http://", "https://")):
        valor = "http://" + valor
    return valor


def carregar_config(caminho: str | Path | None = None) -> Config:
    """Lê o config.yaml.

    Ordem de busca: argumento > variável ENGENHEIRO_CONFIG > ./config.yaml.
    Sem arquivo, usa os padrões (útil para testes), mas avisa quem chamou
    via `Config.raiz`, que aponta para o diretório atual.
    """
    caminho = caminho or os.environ.get("ENGENHEIRO_CONFIG") or "config.yaml"
    caminho = Path(caminho)
    dados: dict = {}
    if caminho.exists():
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        raiz = caminho.resolve().parent
    else:
        raiz = Path.cwd()
    cfg = Config.model_validate({**dados, "raiz": raiz})
    if os.environ.get("OLLAMA_HOST"):
        cfg.ollama.url = _normalizar_url_ollama(os.environ["OLLAMA_HOST"])
    else:
        cfg.ollama.url = _normalizar_url_ollama(cfg.ollama.url)
    return cfg
