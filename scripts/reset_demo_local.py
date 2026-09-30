"""Reset seguro e exclusivamente local da base de demonstração ROTANZA.

O modo de execução real existe para uso futuro, mas exige ambiente local,
``--execute`` e a frase de confirmação exata. O modo ``--dry-run`` é
estritamente somente leitura.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIRMACAO_EXATA = "RESETAR BASE DEMO LOCAL ROTANZA"

TABELAS_LIMPEZA: tuple[str, ...] = (
    "arquivo_comprovante_viagem",
    "finalizacao_entrega",
    "historico_operacao",
    "historico_viagem",
    "ocorrencia_viagem",
    "localizacao_viagem",
    "viagem",
    "comprovante_entrega",
    "historico_rastreamento",
    "ocorrencia_entrega",
    "localizacao_motorista",
    "rastreamento",
    "carga",
    "cotacao",
    "cotac",
    "cotacoes",
    "cliente_usuario",
    "log_acao",
    "motorista",
    "veiculo",
    "rota",
    "cliente",
)

TABELAS_OBRIGATORIAS = frozenset(
    (*TABELAS_LIMPEZA, "usuario_sistema", "configuracao_transportadora")
)

MARCADORES_AMBIENTE_REMOTO = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_STATIC_URL",
    "VERCEL",
    "VERCEL_ENV",
    "RENDER",
    "RENDER_SERVICE_ID",
    "FLY_APP_NAME",
    "HEROKU_APP_NAME",
    "DYNO",
    "K_SERVICE",
)


class ResetDemoErro(RuntimeError):
    """Falha segura que impede ou reverte o reset."""


@dataclass(frozen=True)
class ContextoReset:
    projeto: Path
    banco: Path
    uploads: Path
    backups: Path
    ambiente: str
    variaveis: Mapping[str, str]


@dataclass(frozen=True)
class Inventario:
    administrador: dict[str, object]
    transportadora: dict[str, object]
    contagens: dict[str, int]
    usuarios_a_remover: int
    comprovantes: tuple[dict[str, object], ...]
    arquivos_comprovante_existentes: tuple[Path, ...]
    arquivos_comprovante_ausentes: tuple[str, ...]
    logo: Path
    objetos_schema: tuple[tuple[object, ...], ...]


Evento = Callable[[str], None]


def _ler_dotenv(caminho: Path) -> dict[str, str]:
    valores: dict[str, str] = {}

    if not caminho.is_file():
        return valores

    for linha_bruta in caminho.read_text(
        encoding="utf-8-sig",
        errors="strict",
    ).splitlines():
        linha = linha_bruta.strip()

        if not linha or linha.startswith("#") or "=" not in linha:
            continue

        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip()

        if (
            len(valor) >= 2
            and valor[0] == valor[-1]
            and valor[0] in {'"', "'"}
        ):
            valor = valor[1:-1]

        valores[chave] = valor

    return valores


def _caminho_sqlite_url(database_url: str, projeto: Path) -> Path:
    prefixo = "sqlite:///"

    if not database_url.lower().startswith(prefixo):
        raise ResetDemoErro(
            "DATABASE_URL não é SQLite local; reset recusado."
        )

    caminho_texto = database_url[len(prefixo):].split("?", 1)[0]

    if not caminho_texto or caminho_texto == ":memory:":
        raise ResetDemoErro(
            "DATABASE_URL não aponta para um arquivo SQLite permitido."
        )

    if re.match(r"^/[A-Za-z]:/", caminho_texto):
        caminho_texto = caminho_texto[1:]

    caminho = Path(caminho_texto).expanduser()

    if not caminho.is_absolute():
        caminho = projeto / caminho

    return caminho.resolve(strict=False)


def construir_contexto(
    projeto: Path = PROJECT_ROOT,
    variaveis: Mapping[str, str] | None = None,
    backups: Path | None = None,
) -> ContextoReset:
    projeto = projeto.resolve(strict=False)
    combinadas = _ler_dotenv(projeto / ".env")
    combinadas.update(dict(os.environ if variaveis is None else variaveis))

    ambiente = combinadas.get("APP_ENV", "").strip().lower()
    banco_esperado = (projeto / "database.db").resolve(strict=False)
    database_url = combinadas.get("DATABASE_URL", "").strip()
    banco = (
        _caminho_sqlite_url(database_url, projeto)
        if database_url
        else banco_esperado
    )

    upload_configurado = combinadas.get("UPLOAD_FOLDER", "").strip()
    uploads = (
        Path(upload_configurado).expanduser()
        if upload_configurado
        else projeto / "static" / "uploads"
    )

    if not uploads.is_absolute():
        uploads = projeto / uploads

    raiz_backups = backups or (
        projeto.parent / "rotanza_local_backups" / "reset_demo"
    )

    return ContextoReset(
        projeto=projeto,
        banco=banco.resolve(strict=False),
        uploads=uploads.resolve(strict=False),
        backups=raiz_backups.resolve(strict=False),
        ambiente=ambiente,
        variaveis=combinadas,
    )


def validar_contexto(contexto: ContextoReset) -> None:
    if contexto.ambiente not in {"development", "local"}:
        raise ResetDemoErro(
            "APP_ENV deve ser explicitamente development ou local."
        )

    indicadores = [
        chave
        for chave in MARCADORES_AMBIENTE_REMOTO
        if str(contexto.variaveis.get(chave, "")).strip()
    ]

    if indicadores:
        raise ResetDemoErro(
            "Indicadores de ambiente remoto detectados: "
            + ", ".join(indicadores)
        )

    if str(contexto.variaveis.get("REDIS_URL", "")).strip():
        raise ResetDemoErro(
            "REDIS_URL está configurada; ambiente não é inequivocamente local."
        )

    if not (contexto.projeto / "app.py").is_file() or not (
        contexto.projeto / "config.py"
    ).is_file():
        raise ResetDemoErro("Raiz do projeto ROTANZA não reconhecida.")

    banco_esperado = (contexto.projeto / "database.db").resolve(
        strict=False
    )

    if contexto.banco != banco_esperado:
        raise ResetDemoErro(
            "O banco efetivo não é o database.db local esperado do projeto."
        )

    if not contexto.banco.is_file() or contexto.banco.is_symlink():
        raise ResetDemoErro(
            "database.db local ausente, inválido ou apontado por link simbólico."
        )

    uploads_esperados = (
        contexto.projeto / "static" / "uploads"
    ).resolve(strict=False)

    if contexto.uploads != uploads_esperados:
        raise ResetDemoErro(
            "UPLOAD_FOLDER não é o diretório local esperado do projeto."
        )

    if contexto.uploads.exists() and (
        not contexto.uploads.is_dir() or contexto.uploads.is_symlink()
    ):
        raise ResetDemoErro("Diretório local de uploads não é seguro.")

    try:
        contexto.backups.relative_to(contexto.projeto)
    except ValueError:
        pass
    else:
        raise ResetDemoErro(
            "A pasta de backup deve ficar fora da raiz do projeto."
        )


def _conectar_somente_leitura(banco: Path) -> sqlite3.Connection:
    conexao = sqlite3.connect(
        f"file:{banco.as_posix()}?mode=ro",
        uri=True,
    )
    conexao.row_factory = sqlite3.Row
    return conexao


def _nomes_tabelas(conexao: sqlite3.Connection) -> set[str]:
    return {
        str(linha[0])
        for linha in conexao.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _snapshot_schema(
    conexao: sqlite3.Connection,
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(linha)
        for linha in conexao.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE type IN ('table', 'index') "
            "AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        )
    )


def _caminho_filho_seguro(pasta: Path, nome: str) -> Path:
    if (
        not nome
        or os.path.isabs(nome)
        or os.path.basename(nome) != nome
        or nome in {".", ".."}
    ):
        raise ResetDemoErro(
            f"Referência de arquivo insegura no banco: {nome!r}."
        )

    caminho = (pasta / nome).resolve(strict=False)

    if caminho.parent != pasta.resolve(strict=False):
        raise ResetDemoErro(
            f"Arquivo de comprovante fora da pasta permitida: {nome!r}."
        )

    return caminho


def criar_inventario(
    conexao: sqlite3.Connection,
    contexto: ContextoReset,
) -> Inventario:
    tabelas = _nomes_tabelas(conexao)
    ausentes = sorted(TABELAS_OBRIGATORIAS - tabelas)

    if ausentes:
        raise ResetDemoErro(
            "Schema local inesperado; tabelas ausentes: "
            + ", ".join(ausentes)
        )

    administrador_linha = conexao.execute(
        "SELECT id, nome, usuario, email, perfil, ativo "
        "FROM usuario_sistema WHERE id = 1"
    ).fetchone()

    if not administrador_linha:
        raise ResetDemoErro("Administrador preservado ID 1 não existe.")

    administrador = dict(administrador_linha)

    if not (
        administrador["nome"] == "Administrador"
        and administrador["usuario"] == "admin"
        and str(administrador["perfil"]).strip().lower()
        == "administrador"
        and bool(administrador["ativo"])
    ):
        raise ResetDemoErro(
            "Administrador ID 1 não corresponde à identidade preservada."
        )

    transportadoras = conexao.execute(
        "SELECT id, nome_exibicao, razao_social, logo "
        "FROM configuracao_transportadora ORDER BY id"
    ).fetchall()

    if len(transportadoras) != 1 or int(transportadoras[0]["id"]) != 1:
        raise ResetDemoErro(
            "configuracao_transportadora ID 1 não é única ou está ausente."
        )

    transportadora = dict(transportadoras[0])
    referencia_logo = str(transportadora.get("logo") or "").strip()
    logo = _caminho_filho_seguro(
        contexto.uploads / "logos_transportadora",
        referencia_logo,
    )

    if not logo.is_file() or logo.is_symlink():
        raise ResetDemoErro(
            "O logo referenciado pela transportadora não existe ou é inseguro."
        )

    contagens = {
        tabela: int(
            conexao.execute(
                f'SELECT COUNT(*) FROM "{tabela}"'
            ).fetchone()[0]
        )
        for tabela in TABELAS_LIMPEZA
    }
    usuarios_a_remover = int(
        conexao.execute(
            "SELECT COUNT(*) FROM usuario_sistema WHERE id != 1"
        ).fetchone()[0]
    )
    comprovantes = tuple(
        dict(linha)
        for linha in conexao.execute(
            "SELECT id, viagem_id, nome_arquivo "
            "FROM arquivo_comprovante_viagem ORDER BY id"
        )
    )
    arquivos_existentes: list[Path] = []
    arquivos_ausentes: list[str] = []
    vistos: set[Path] = set()

    for comprovante in comprovantes:
        nome = str(comprovante["nome_arquivo"] or "").strip()
        caminho = _caminho_filho_seguro(contexto.uploads, nome)

        if caminho in vistos:
            continue

        vistos.add(caminho)

        if caminho.is_file() and not caminho.is_symlink():
            arquivos_existentes.append(caminho)
        else:
            arquivos_ausentes.append(nome)

    return Inventario(
        administrador=administrador,
        transportadora=transportadora,
        contagens=contagens,
        usuarios_a_remover=usuarios_a_remover,
        comprovantes=comprovantes,
        arquivos_comprovante_existentes=tuple(arquivos_existentes),
        arquivos_comprovante_ausentes=tuple(arquivos_ausentes),
        logo=logo,
        objetos_schema=_snapshot_schema(conexao),
    )


def caminho_novo_backup(
    contexto: ContextoReset,
    instante: datetime | None = None,
) -> Path:
    momento = instante or datetime.now()
    sufixo = momento.strftime("%Y%m%d-%H%M%S-%f")
    return contexto.backups / sufixo


def relatorio_dry_run(
    contexto: ContextoReset,
    instante: datetime | None = None,
) -> dict[str, object]:
    validar_contexto(contexto)

    with closing(_conectar_somente_leitura(contexto.banco)) as conexao:
        inventario = criar_inventario(conexao, contexto)

    return {
        "modo": "dry-run",
        "ambiente": contexto.ambiente,
        "banco": str(contexto.banco),
        "administrador_preservado": inventario.administrador,
        "transportadora_preservada": inventario.transportadora,
        "registros_por_tabela": inventario.contagens,
        "usuarios_removidos": inventario.usuarios_a_remover,
        "arquivos_comprovante_quarentena": len(
            inventario.arquivos_comprovante_existentes
        ),
        "arquivos_comprovante_ausentes": list(
            inventario.arquivos_comprovante_ausentes
        ),
        "logo_preservado": str(inventario.logo),
        "backup_planejado": str(caminho_novo_backup(contexto, instante)),
        "ordem_limpeza": [
            *TABELAS_LIMPEZA,
            "usuario_sistema (somente id != 1)",
        ],
    }


def _serializar_inventario(
    contexto: ContextoReset,
    inventario: Inventario,
) -> dict[str, object]:
    return {
        "banco_origem": str(contexto.banco),
        "uploads_origem": str(contexto.uploads),
        "administrador_preservado": inventario.administrador,
        "transportadora_preservada": inventario.transportadora,
        "contagens_antes": inventario.contagens,
        "usuarios_a_remover": inventario.usuarios_a_remover,
        "comprovantes": list(inventario.comprovantes),
        "arquivos_existentes": [
            caminho.name
            for caminho in inventario.arquivos_comprovante_existentes
        ],
        "arquivos_ausentes": list(
            inventario.arquivos_comprovante_ausentes
        ),
        "logo_preservado": str(inventario.logo),
    }


def criar_backup_local(
    conexao: sqlite3.Connection,
    contexto: ContextoReset,
    inventario: Inventario,
    destino: Path,
) -> None:
    if destino.exists():
        raise ResetDemoErro("Pasta de backup já existe; operação recusada.")

    destino.mkdir(parents=True, exist_ok=False)

    try:
        banco_backup = destino / "database.db"
        shutil.copy2(contexto.banco, banco_backup)

        with closing(_conectar_somente_leitura(banco_backup)) as copia:
            integridade = copia.execute("PRAGMA integrity_check").fetchone()[0]

            if integridade != "ok":
                raise ResetDemoErro("Backup SQLite falhou na integridade.")

        pasta_preservados = destino / "preservados"
        pasta_preservados.mkdir()
        shutil.copy2(inventario.logo, pasta_preservados / inventario.logo.name)

        (destino / "inventario.json").write_text(
            json.dumps(
                _serializar_inventario(contexto, inventario),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(destino, ignore_errors=True)
        raise


def _restaurar_arquivos(
    movidos: Sequence[tuple[Path, Path]],
) -> None:
    erros: list[str] = []

    for origem, quarentena in reversed(movidos):
        try:
            if quarentena.exists():
                if origem.exists():
                    raise ResetDemoErro(
                        f"Destino de restauração já existe: {origem}"
                    )
                shutil.move(str(quarentena), str(origem))
        except Exception as erro:
            erros.append(f"{origem.name}: {erro}")

    if erros:
        raise ResetDemoErro(
            "Falha ao restaurar comprovantes: " + "; ".join(erros)
        )


def mover_comprovantes_para_quarentena(
    inventario: Inventario,
    destino_backup: Path,
) -> list[tuple[Path, Path]]:
    quarentena = destino_backup / "quarentena" / "comprovantes"
    movidos: list[tuple[Path, Path]] = []

    if not inventario.arquivos_comprovante_existentes:
        return movidos

    quarentena.mkdir(parents=True, exist_ok=False)

    try:
        for origem in inventario.arquivos_comprovante_existentes:
            destino = quarentena / origem.name

            if destino.exists():
                raise ResetDemoErro(
                    f"Colisão na quarentena para {origem.name}."
                )

            shutil.move(str(origem), str(destino))
            movidos.append((origem, destino))
    except Exception:
        _restaurar_arquivos(movidos)
        raise

    return movidos


def _validar_estado_limpo(
    conexao: sqlite3.Connection,
    contexto: ContextoReset,
    inventario: Inventario,
) -> None:
    for tabela in TABELAS_LIMPEZA:
        quantidade = int(
            conexao.execute(
                f'SELECT COUNT(*) FROM "{tabela}"'
            ).fetchone()[0]
        )

        if quantidade != 0:
            raise ResetDemoErro(
                f"Tabela {tabela} não ficou vazia após o reset."
            )

    usuarios = conexao.execute(
        "SELECT id, nome, usuario, perfil, ativo "
        "FROM usuario_sistema ORDER BY id"
    ).fetchall()

    if len(usuarios) != 1 or not (
        int(usuarios[0]["id"]) == 1
        and usuarios[0]["nome"] == "Administrador"
        and usuarios[0]["usuario"] == "admin"
        and str(usuarios[0]["perfil"]).strip().lower() == "administrador"
        and bool(usuarios[0]["ativo"])
    ):
        raise ResetDemoErro("Administrador preservado ficou inconsistente.")

    configuracoes = conexao.execute(
        "SELECT id, nome_exibicao, razao_social, logo "
        "FROM configuracao_transportadora ORDER BY id"
    ).fetchall()

    if len(configuracoes) != 1 or dict(configuracoes[0]) != (
        inventario.transportadora
    ):
        raise ResetDemoErro(
            "Configuração da transportadora não foi preservada."
        )

    if not inventario.logo.is_file():
        raise ResetDemoErro("Logo preservado não está mais disponível.")

    violacoes = conexao.execute("PRAGMA foreign_key_check").fetchall()

    if violacoes:
        raise ResetDemoErro("foreign_key_check encontrou violações.")

    if _snapshot_schema(conexao) != inventario.objetos_schema:
        raise ResetDemoErro("Estrutura, índices ou constraints foram alterados.")

    integridade = conexao.execute("PRAGMA integrity_check").fetchone()[0]

    if integridade != "ok":
        raise ResetDemoErro("Banco falhou no integrity_check final.")


def _limpar_banco(
    conexao: sqlite3.Connection,
    contexto: ContextoReset,
    inventario: Inventario,
    falhar_apos_tabela: str | None = None,
    evento: Evento | None = None,
) -> None:
    for tabela in TABELAS_LIMPEZA:
        conexao.execute(f'DELETE FROM "{tabela}"')

        if evento:
            evento(f"delete:{tabela}")

        if falhar_apos_tabela == tabela:
            raise ResetDemoErro(
                f"Falha de teste injetada após limpar {tabela}."
            )

    conexao.execute("DELETE FROM usuario_sistema WHERE id != 1")

    if evento:
        evento("delete:usuario_sistema")

    if falhar_apos_tabela == "usuario_sistema":
        raise ResetDemoErro(
            "Falha de teste injetada após limpar usuario_sistema."
        )

    _validar_estado_limpo(conexao, contexto, inventario)


def executar_reset(
    contexto: ContextoReset,
    confirmacao: str,
    *,
    falhar_apos_tabela: str | None = None,
    evento: Evento | None = None,
) -> dict[str, object]:
    validar_contexto(contexto)

    if confirmacao != CONFIRMACAO_EXATA:
        raise ResetDemoErro(
            "Confirmação textual ausente ou incorreta; nada foi alterado."
        )

    conexao = sqlite3.connect(str(contexto.banco), timeout=1)
    conexao.row_factory = sqlite3.Row
    movidos: list[tuple[Path, Path]] = []
    destino_backup: Path | None = None
    commit_realizado = False

    try:
        conexao.execute("PRAGMA foreign_keys = ON")

        if int(conexao.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
            raise ResetDemoErro("Não foi possível habilitar foreign keys.")

        journal_mode = str(
            conexao.execute("PRAGMA journal_mode").fetchone()[0]
        ).lower()

        if journal_mode not in {"delete", "truncate", "persist"}:
            raise ResetDemoErro(
                "Journal mode não permite backup local seguro sob lock: "
                + journal_mode
            )

        conexao.execute("BEGIN EXCLUSIVE")
        inventario = criar_inventario(conexao, contexto)
        destino_backup = caminho_novo_backup(contexto)
        criar_backup_local(
            conexao,
            contexto,
            inventario,
            destino_backup,
        )

        if evento:
            evento("backup:concluido")

        movidos = mover_comprovantes_para_quarentena(
            inventario,
            destino_backup,
        )

        if evento:
            evento("quarentena:concluida")

        _limpar_banco(
            conexao,
            contexto,
            inventario,
            falhar_apos_tabela=falhar_apos_tabela,
            evento=evento,
        )
        conexao.commit()
        commit_realizado = True
        conexao.close()

        with closing(
            _conectar_somente_leitura(contexto.banco)
        ) as verificacao:
            _validar_estado_limpo(verificacao, contexto, inventario)

        return {
            "modo": "execute",
            "banco": str(contexto.banco),
            "backup": str(destino_backup),
            "administrador_preservado": inventario.administrador,
            "transportadora_preservada": inventario.transportadora,
            "arquivos_em_quarentena": len(movidos),
            "arquivos_ausentes_antes": list(
                inventario.arquivos_comprovante_ausentes
            ),
            "foreign_key_check": "ok",
            "integrity_check": "ok",
        }
    except Exception as erro:
        if not commit_realizado and conexao.in_transaction:
            conexao.rollback()

        try:
            conexao.close()
        except Exception:
            pass

        erros_recuperacao: list[str] = []

        if commit_realizado and destino_backup:
            try:
                shutil.copy2(destino_backup / "database.db", contexto.banco)
            except Exception as erro_backup:
                erros_recuperacao.append(
                    f"restauração do banco falhou: {erro_backup}"
                )

        try:
            _restaurar_arquivos(movidos)
        except Exception as erro_arquivos:
            erros_recuperacao.append(str(erro_arquivos))

        if erros_recuperacao:
            raise ResetDemoErro(
                f"Reset falhou: {erro}. Recuperação incompleta: "
                + "; ".join(erros_recuperacao)
            ) from erro

        if isinstance(erro, ResetDemoErro):
            raise

        raise ResetDemoErro(f"Reset abortado com segurança: {erro}") from erro


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audita ou limpa com segurança somente a base demo LOCAL ROTANZA."
        )
    )
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument(
        "--dry-run",
        action="store_true",
        help="Exibe o plano sem criar, alterar ou mover nada.",
    )
    modo.add_argument(
        "--execute",
        action="store_true",
        help="Executa o reset local após todas as travas.",
    )
    parser.add_argument(
        "--confirmation",
        default="",
        help=(
            "Frase obrigatória para --execute: "
            f"{CONFIRMACAO_EXATA!r}."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argumentos = _parser().parse_args(argv)

    try:
        contexto = construir_contexto()

        if argumentos.dry_run:
            resultado = relatorio_dry_run(contexto)
        else:
            resultado = executar_reset(
                contexto,
                argumentos.confirmation,
            )

        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0
    except ResetDemoErro as erro:
        print(f"RESET RECUSADO: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
