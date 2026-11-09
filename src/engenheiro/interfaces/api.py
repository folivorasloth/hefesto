"""API HTTP (FastAPI) para integrar o Hefesto num assistente central.

Documentação interativa em http://<máquina>:8765/docs quando o serviço está no ar.

Autenticação: se houver token (HEFESTO_API_TOKEN ou api.token), toda rota
exceto /status exige o cabeçalho `Authorization: Bearer <token>`.

As rotas que chamam o modelo demoram (minutos em CPU): o cliente precisa de
timeout longo. Pedidos simultâneos esperam na fila (um modelo por vez).
"""

from __future__ import annotations

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from engenheiro import rastro as mod_rastro
from engenheiro.servico import Servico


class Pergunta(BaseModel):
    pergunta: str = Field(..., min_length=1, examples=["Como eu identifico o tipo de ignição do Gol?"])


class Fala(BaseModel):
    fala: str = Field(..., min_length=1, examples=["tem três fios no conector"])


class Nota(BaseModel):
    texto: str = Field(..., min_length=1)
    titulo: str | None = None
    tags: list[str] = []


class ArgsFerramenta(BaseModel):
    argumentos: dict = {}


def criar_app(servico: Servico, token: str = "") -> FastAPI:
    app = FastAPI(title=f"{servico.eng.persona.nome} (engenheiro)", version="1.0",
                  description="Assistente de mecânica e elétrica com fontes verificáveis.")
    cfg = servico.eng.cfg

    def autorizar(authorization: str | None = Header(default=None)) -> None:
        if not token:
            return
        esperado = f"Bearer {token}"
        # compare_digest: comparação em tempo constante (não vaza o token por tempo de resposta).
        if not authorization or not hmac.compare_digest(authorization, esperado):
            raise HTTPException(401, "token ausente ou inválido (Authorization: Bearer <token>)")

    protegido = [Depends(autorizar)]

    @app.get("/status")
    def status() -> dict:
        return servico.status()

    @app.post("/perguntar", dependencies=protegido)
    def perguntar(p: Pergunta) -> dict:
        """Pergunta isolada (sem memória). Resposta com texto, versão falada e id do rastro."""
        return servico.perguntar(p.pergunta)

    @app.post("/conversas", dependencies=protegido)
    def nova_conversa(interlocutor: str = "api") -> dict:
        return {"conversa": servico.nova_conversa(interlocutor), "interlocutor": interlocutor}

    @app.post("/conversas/{interlocutor}/turno", dependencies=protegido)
    def turno(interlocutor: str, f: Fala) -> dict:
        """Um turno de conversa com memória. `interlocutor` separa as conversas
        (ex.: "joao", "grilo"). Responda "sim"/"não" às propostas de anotação."""
        return servico.turno(f"api:{interlocutor}", f.fala)

    @app.get("/rastro/{id_rastro}", dependencies=protegido)
    def rastro(id_rastro: str) -> dict:
        try:
            return mod_rastro.carregar(cfg.caminho(cfg.caminhos.rastros), id_rastro)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, f"rastro {id_rastro} não encontrado") from None

    @app.post("/caderno", dependencies=protegido)
    def anotar(n: Nota) -> dict:
        a = servico.anotar(n.texto, n.titulo, n.tags)
        return {"citacao": a.citacao, "arquivo": a.arquivo, "titulo": a.titulo}

    @app.get("/caderno", dependencies=protegido)
    def caderno(termo: str = "", limite: int = 10) -> list[dict]:
        return [{"citacao": a.citacao, "titulo": a.titulo, "texto": a.texto, "tags": a.tags}
                for a in servico.caderno.buscar(termo, limite)]

    @app.get("/perfil", dependencies=protegido)
    def perfil() -> dict:
        return {"texto": servico.perfil.para_prompt(), "dados": servico.perfil.dados}

    @app.get("/ferramentas", dependencies=protegido)
    def ferramentas() -> list[dict]:
        reg = servico.eng.registro
        return [{"nome": f.nome, "descricao": f.descricao, "parametros": f.parametros} for f in reg.ferramentas.values()] if reg else []

    @app.post("/ferramentas/{nome}", dependencies=protegido)
    def ferramenta(nome: str, a: ArgsFerramenta) -> dict:
        """Roda uma ferramenta de cálculo direto (sem LLM). Útil para os outros personagens."""
        reg = servico.eng.registro
        if reg is None or nome not in reg.ferramentas:
            raise HTTPException(404, f"ferramenta {nome} não existe")
        ch = reg.executar(nome, a.argumentos)
        if ch.erro:
            raise HTTPException(422, ch.erro)
        return {"id": ch.id, "saida": ch.saida}

    return app
