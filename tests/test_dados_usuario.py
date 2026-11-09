"""Seus dados separados do projeto, sobreposição de arquivos de referência e backup."""

import shutil
import tarfile
from pathlib import Path

import yaml
from typer.testing import CliRunner

from engenheiro import fabrica
from engenheiro.backup import criar_backup
from engenheiro.config import carregar_config
from engenheiro.interfaces.cli import app

RAIZ = Path(__file__).parents[1]


def _projeto(tmp_path: Path) -> Path:
    """Cópia mínima do projeto (modelos, dados_ref, persona, eval) numa pasta temporária."""
    for pasta in ("modelos", "dados_ref", "persona", "eval"):
        shutil.copytree(RAIZ / pasta, tmp_path / pasta)
    shutil.copy(RAIZ / "config.example.yaml", tmp_path / "config.yaml")
    return tmp_path


def test_perfil_pessoal_criado_do_modelo_e_modelo_intocado(tmp_path):
    cfg = carregar_config(_projeto(tmp_path) / "config.yaml")
    modelo = (tmp_path / "modelos" / "perfil_veiculo.yaml").read_text(encoding="utf-8")
    p = fabrica.perfil(cfg)
    assert p.caminho == tmp_path / "data" / "usuario" / "perfil_veiculo.yaml"
    p.definir("carburador.modelo", "Weber 460", "confirmado", "gravação no corpo")
    # O modelo do projeto não mudou; a sua cópia, sim.
    assert (tmp_path / "modelos" / "perfil_veiculo.yaml").read_text(encoding="utf-8") == modelo
    assert fabrica.perfil(cfg).valor_confirmado("carburador.modelo") == "Weber 460"


def test_copia_pessoal_nao_e_sobrescrita(tmp_path):
    cfg = carregar_config(_projeto(tmp_path) / "config.yaml")
    inv = cfg.arquivo_inventario
    inv.write_text(inv.read_text(encoding="utf-8").replace("quantidade: 600", "quantidade: 599"), encoding="utf-8")
    assert "quantidade: 599" in cfg.arquivo_inventario.read_text(encoding="utf-8")


def test_referencia_personalizada_vale_no_lugar_do_padrao(tmp_path):
    cfg = carregar_config(_projeto(tmp_path) / "config.yaml")
    assert cfg.ref("combustiveis.yaml") == tmp_path / "dados_ref" / "combustiveis.yaml"
    r = CliRunner().invoke(app, ["personalizar", "combustiveis", "--config", str(tmp_path / "config.yaml")])
    assert r.exit_code == 0, r.output
    sua = tmp_path / "data" / "usuario" / "dados_ref" / "combustiveis.yaml"
    assert cfg.ref("combustiveis.yaml") == sua
    # Preenche a estequiometria (valor FICTÍCIO, só para o teste) e a ferramenta passa a usá-lo.
    d = yaml.safe_load(sua.read_text(encoding="utf-8"))
    d["combustiveis"]["etanol_hidratado"].update(afr_estequiometrico=9.0, status="confirmado", fonte="teste")
    sua.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    from engenheiro.eventos import Barramento

    reg = fabrica.registro_ferramentas(cfg, Barramento())
    ch = reg.executar("lambda_afr", {"combustivel": "etanol_hidratado", "lambda": 1.0})
    assert ch.erro is None and ch.saida["resultado"]["afr"] == 9.0


def test_personalizar_lista_e_recusa_nome_desconhecido(tmp_path):
    cfg_arq = str(_projeto(tmp_path) / "config.yaml")
    r = CliRunner().invoke(app, ["personalizar", "--config", cfg_arq], env={"COLUMNS": "200"})
    assert "combustiveis" in r.output and "persona" in r.output
    assert CliRunner().invoke(app, ["personalizar", "xyz", "--config", cfg_arq]).exit_code == 1


def test_backup_padrao_e_completo(tmp_path):
    raiz = _projeto(tmp_path)
    cfg = carregar_config(raiz / "config.yaml")
    fabrica.perfil(cfg)                                   # cria data/usuario/perfil_veiculo.yaml
    cad = raiz / "data" / "biblioteca" / "caderno_de_bordo"
    cad.mkdir(parents=True)
    (cad / "2026-11-08.md").write_text("## 2026-11-08 10:00 · Bateria\n\n12,6 V\n", encoding="utf-8")
    (raiz / "data" / "biblioteca" / "veiculo").mkdir()
    (raiz / "data" / "biblioteca" / "veiculo" / "manual.pdf").write_bytes(b"%PDF")
    (raiz / "data" / "indice.sqlite").write_bytes(b"x")

    arq, n, avisos = criar_backup(cfg)
    with tarfile.open(arq) as t:
        nomes = set(t.getnames())
    assert "data/usuario/perfil_veiculo.yaml" in nomes and "data/biblioteca/caderno_de_bordo/2026-11-08.md" in nomes
    assert "config.yaml" in nomes and "data/indice.sqlite" not in nomes and n >= 3 and not avisos

    arq2, _, _ = criar_backup(cfg, completo=True)
    with tarfile.open(arq2) as t:
        nomes2 = set(t.getnames())
    assert "data/indice.sqlite" in nomes2 and "data/biblioteca/veiculo/manual.pdf" in nomes2
    assert not any(n.startswith("data/backups") for n in nomes2)   # backup não guarda backups antigos


def test_backup_avisa_token_no_config(tmp_path):
    raiz = _projeto(tmp_path)
    c = raiz / "config.yaml"
    c.write_text(c.read_text(encoding="utf-8").replace('token: ""', 'token: "abc123"'), encoding="utf-8")
    _, _, avisos = criar_backup(carregar_config(c))
    assert avisos and "token" in avisos[0]
