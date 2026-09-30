import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts import reset_demo_local


SCHEMA = """
CREATE TABLE usuario_sistema (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    usuario TEXT NOT NULL UNIQUE,
    email TEXT,
    senha TEXT NOT NULL,
    perfil TEXT NOT NULL,
    ativo INTEGER NOT NULL
);
CREATE TABLE configuracao_transportadora (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    nome_exibicao TEXT NOT NULL,
    razao_social TEXT NOT NULL,
    logo TEXT
);
CREATE TABLE cliente (
    id INTEGER PRIMARY KEY,
    razao_social TEXT NOT NULL
);
CREATE TABLE motorista (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    usuario_sistema_id INTEGER UNIQUE,
    FOREIGN KEY (usuario_sistema_id) REFERENCES usuario_sistema(id)
);
CREATE TABLE veiculo (
    id INTEGER PRIMARY KEY,
    placa TEXT NOT NULL UNIQUE
);
CREATE TABLE rota (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL
);
CREATE TABLE cotacao (
    id INTEGER PRIMARY KEY,
    cliente TEXT NOT NULL
);
CREATE TABLE cotac (
    id INTEGER PRIMARY KEY,
    cliente TEXT NOT NULL
);
CREATE TABLE cotacoes (
    id INTEGER PRIMARY KEY,
    cliente TEXT NOT NULL
);
CREATE TABLE carga (
    id INTEGER PRIMARY KEY,
    cotacao_id INTEGER NOT NULL UNIQUE,
    cliente TEXT NOT NULL,
    FOREIGN KEY (cotacao_id) REFERENCES cotacao(id)
);
CREATE TABLE rastreamento (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL UNIQUE,
    cliente TEXT NOT NULL,
    cliente_id INTEGER,
    motorista_id INTEGER,
    veiculo_id INTEGER,
    rota_id INTEGER,
    FOREIGN KEY (cliente_id) REFERENCES cliente(id),
    FOREIGN KEY (motorista_id) REFERENCES motorista(id),
    FOREIGN KEY (veiculo_id) REFERENCES veiculo(id),
    FOREIGN KEY (rota_id) REFERENCES rota(id)
);
CREATE TABLE viagem (
    id INTEGER PRIMARY KEY,
    rastreamento_id INTEGER NOT NULL,
    motorista_id INTEGER,
    veiculo_id INTEGER,
    FOREIGN KEY (rastreamento_id) REFERENCES rastreamento(id),
    FOREIGN KEY (motorista_id) REFERENCES motorista(id),
    FOREIGN KEY (veiculo_id) REFERENCES veiculo(id)
);
CREATE TABLE cliente_usuario (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER,
    usuario_sistema_id INTEGER UNIQUE,
    nome TEXT NOT NULL,
    empresa TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    senha TEXT NOT NULL,
    ativo INTEGER,
    FOREIGN KEY (cliente_id) REFERENCES cliente(id),
    FOREIGN KEY (usuario_sistema_id) REFERENCES usuario_sistema(id)
);
CREATE TABLE arquivo_comprovante_viagem (
    id INTEGER PRIMARY KEY,
    viagem_id INTEGER NOT NULL,
    nome_arquivo TEXT NOT NULL,
    FOREIGN KEY (viagem_id) REFERENCES viagem(id)
);
CREATE TABLE finalizacao_entrega (
    id INTEGER PRIMARY KEY,
    viagem_id INTEGER NOT NULL,
    FOREIGN KEY (viagem_id) REFERENCES viagem(id)
);
CREATE TABLE historico_operacao (
    id INTEGER PRIMARY KEY,
    viagem_id INTEGER NOT NULL,
    FOREIGN KEY (viagem_id) REFERENCES viagem(id)
);
CREATE TABLE historico_viagem (
    id INTEGER PRIMARY KEY,
    viagem_id INTEGER NOT NULL,
    FOREIGN KEY (viagem_id) REFERENCES viagem(id)
);
CREATE TABLE ocorrencia_viagem (
    id INTEGER PRIMARY KEY,
    viagem_id INTEGER NOT NULL,
    FOREIGN KEY (viagem_id) REFERENCES viagem(id)
);
CREATE TABLE localizacao_viagem (
    id INTEGER PRIMARY KEY,
    viagem_id INTEGER NOT NULL,
    FOREIGN KEY (viagem_id) REFERENCES viagem(id)
);
CREATE TABLE comprovante_entrega (
    id INTEGER PRIMARY KEY,
    rastreamento_id INTEGER NOT NULL,
    nome_arquivo TEXT NOT NULL,
    FOREIGN KEY (rastreamento_id) REFERENCES rastreamento(id)
);
CREATE TABLE historico_rastreamento (
    id INTEGER PRIMARY KEY,
    rastreamento_id INTEGER NOT NULL,
    FOREIGN KEY (rastreamento_id) REFERENCES rastreamento(id)
);
CREATE TABLE ocorrencia_entrega (
    id INTEGER PRIMARY KEY,
    rastreamento_id INTEGER NOT NULL,
    FOREIGN KEY (rastreamento_id) REFERENCES rastreamento(id)
);
CREATE TABLE localizacao_motorista (
    id INTEGER PRIMARY KEY,
    motorista_id INTEGER,
    rastreamento_id INTEGER,
    FOREIGN KEY (motorista_id) REFERENCES motorista(id),
    FOREIGN KEY (rastreamento_id) REFERENCES rastreamento(id)
);
CREATE TABLE log_acao (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    acao TEXT,
    FOREIGN KEY (usuario_id) REFERENCES usuario_sistema(id)
);
"""


DATA = """
INSERT INTO usuario_sistema
    (id, nome, usuario, email, senha, perfil, ativo)
VALUES
    (1, 'Administrador', 'admin', 'admin@example.invalid',
     'hash-administrador-preservado', 'administrador', 1),
    (2, 'Cliente Demo Antigo', 'cliente-antigo', 'cliente@example.invalid',
     'hash-cliente-antigo', 'cliente', 1),
    (3, 'Motorista Demo Antigo', 'motorista-antigo', 'motorista@example.invalid',
     'hash-motorista-antigo', 'motorista', 1);
INSERT INTO configuracao_transportadora
    (id, nome_exibicao, razao_social, logo)
VALUES (1, 'ROTANZA Teste', 'ROTANZA Teste Ltda.', 'logo-demo.png');
INSERT INTO cliente (id, razao_social) VALUES (1, 'Cliente Antigo');
INSERT INTO motorista (id, nome, usuario_sistema_id)
VALUES (1, 'Motorista Antigo', 3);
INSERT INTO veiculo (id, placa) VALUES (1, 'ABC1D23');
INSERT INTO rota (id, nome) VALUES (1, 'Rota Antiga');
INSERT INTO cotacao (id, cliente) VALUES (1, 'Cliente Antigo');
INSERT INTO cotac (id, cliente) VALUES (1, 'Legado cotac');
INSERT INTO cotacoes (id, cliente) VALUES (1, 'Legado cotacoes');
INSERT INTO carga (id, cotacao_id, cliente)
VALUES (1, 1, 'Cliente Antigo');
INSERT INTO rastreamento
    (id, codigo, cliente, cliente_id, motorista_id, veiculo_id, rota_id)
VALUES (1, 'DEMO-ANTIGA', 'Cliente Antigo', 1, 1, 1, 1);
INSERT INTO viagem
    (id, rastreamento_id, motorista_id, veiculo_id)
VALUES (1, 1, 1, 1);
INSERT INTO cliente_usuario
    (id, cliente_id, usuario_sistema_id, nome, empresa, email, senha, ativo)
VALUES
    (1, 1, 2, 'Cliente Demo Antigo', 'Cliente Antigo',
     'cliente@example.invalid', 'hash-cliente-antigo', 1);
INSERT INTO arquivo_comprovante_viagem
    (id, viagem_id, nome_arquivo)
VALUES (1, 1, 'comprovante-antigo.pdf');
INSERT INTO finalizacao_entrega (id, viagem_id) VALUES (1, 1);
INSERT INTO historico_operacao (id, viagem_id) VALUES (1, 1);
INSERT INTO historico_viagem (id, viagem_id) VALUES (1, 1);
INSERT INTO ocorrencia_viagem (id, viagem_id) VALUES (1, 1);
INSERT INTO localizacao_viagem (id, viagem_id) VALUES (1, 1);
INSERT INTO comprovante_entrega
    (id, rastreamento_id, nome_arquivo)
VALUES (1, 1, 'legado.pdf');
INSERT INTO historico_rastreamento (id, rastreamento_id) VALUES (1, 1);
INSERT INTO ocorrencia_entrega (id, rastreamento_id) VALUES (1, 1);
INSERT INTO localizacao_motorista
    (id, motorista_id, rastreamento_id)
VALUES (1, 1, 1);
INSERT INTO log_acao (id, usuario_id, acao)
VALUES (1, 2, 'Ação antiga');
"""


class ResetDemoLocalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rotanza-reset-test-")
        self.base = Path(self.temp.name)
        self.projeto = self.base / "backend_transportadora"
        self.projeto.mkdir()
        (self.projeto / "scripts").mkdir()
        (self.projeto / "app.py").write_text("# teste\n", encoding="utf-8")
        (self.projeto / "config.py").write_text("# teste\n", encoding="utf-8")
        (self.projeto / ".env").write_text(
            "APP_ENV=development\n",
            encoding="utf-8",
        )
        self.uploads = self.projeto / "static" / "uploads"
        self.logos = self.uploads / "logos_transportadora"
        self.logos.mkdir(parents=True)
        self.logo = self.logos / "logo-demo.png"
        self.logo.write_bytes(b"logo-demo")
        self.comprovante = self.uploads / "comprovante-antigo.pdf"
        self.comprovante.write_bytes(b"%PDF-comprovante-demo")
        self.desconhecido = self.uploads / "arquivo-desconhecido.txt"
        self.desconhecido.write_text("preservar", encoding="utf-8")
        self.banco = self.projeto / "database.db"

        with closing(sqlite3.connect(self.banco)) as conexao:
            conexao.execute("PRAGMA foreign_keys = ON")
            conexao.executescript(SCHEMA)
            conexao.executescript(DATA)
            conexao.commit()

        self.backups = self.base / "backups"
        self.contexto = reset_demo_local.construir_contexto(
            projeto=self.projeto,
            variaveis={"APP_ENV": "development"},
            backups=self.backups,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _dump_banco(self):
        with closing(sqlite3.connect(self.banco)) as conexao:
            return tuple(conexao.iterdump())

    def _snapshot_arquivos(self):
        return {
            arquivo.relative_to(self.projeto).as_posix(): arquivo.read_bytes()
            for arquivo in self.projeto.rglob("*")
            if arquivo.is_file()
        }

    def test_dry_run_nao_altera_banco_nem_arquivos(self):
        banco_antes = self.banco.read_bytes()
        arquivos_antes = self._snapshot_arquivos()

        relatorio = reset_demo_local.relatorio_dry_run(self.contexto)

        self.assertEqual(self.banco.read_bytes(), banco_antes)
        self.assertEqual(self._snapshot_arquivos(), arquivos_antes)
        self.assertFalse(self.backups.exists())
        self.assertEqual(relatorio["modo"], "dry-run")
        self.assertEqual(relatorio["usuarios_removidos"], 2)
        self.assertEqual(relatorio["arquivos_comprovante_quarentena"], 1)
        self.assertEqual(
            relatorio["administrador_preservado"]["usuario"],
            "admin",
        )

    def test_recusa_ambiente_producao_e_indicador_railway(self):
        producao = reset_demo_local.construir_contexto(
            projeto=self.projeto,
            variaveis={"APP_ENV": "production"},
            backups=self.backups,
        )
        railway = reset_demo_local.construir_contexto(
            projeto=self.projeto,
            variaveis={
                "APP_ENV": "development",
                "RAILWAY_PROJECT_ID": "projeto-remoto",
            },
            backups=self.backups,
        )

        with self.assertRaises(reset_demo_local.ResetDemoErro):
            reset_demo_local.relatorio_dry_run(producao)
        with self.assertRaises(reset_demo_local.ResetDemoErro):
            reset_demo_local.relatorio_dry_run(railway)

    def test_recusa_database_url_remota_e_banco_fora_do_projeto(self):
        with self.assertRaises(reset_demo_local.ResetDemoErro):
            reset_demo_local.construir_contexto(
                projeto=self.projeto,
                variaveis={
                    "APP_ENV": "development",
                    "DATABASE_URL": "postgresql://example.invalid/producao",
                },
                backups=self.backups,
            )

        banco_fora = self.base / "outro.db"
        shutil.copy2(self.banco, banco_fora)
        contexto_fora = reset_demo_local.construir_contexto(
            projeto=self.projeto,
            variaveis={
                "APP_ENV": "development",
                "DATABASE_URL": f"sqlite:///{banco_fora.as_posix()}",
            },
            backups=self.backups,
        )

        with self.assertRaises(reset_demo_local.ResetDemoErro):
            reset_demo_local.relatorio_dry_run(contexto_fora)

    def test_confirmacao_explicita_e_obrigatoria(self):
        dump_antes = self._dump_banco()

        with self.assertRaises(reset_demo_local.ResetDemoErro):
            reset_demo_local.executar_reset(self.contexto, "sim")

        self.assertEqual(self._dump_banco(), dump_antes)
        self.assertTrue(self.comprovante.exists())
        self.assertFalse(self.backups.exists())

    def test_execucao_temporaria_preserva_identidade_e_limpa_dependencias(self):
        resultado = reset_demo_local.executar_reset(
            self.contexto,
            reset_demo_local.CONFIRMACAO_EXATA,
        )

        backup = Path(resultado["backup"])
        self.assertTrue((backup / "database.db").is_file())
        self.assertTrue((backup / "inventario.json").is_file())
        self.assertTrue((backup / "preservados" / self.logo.name).is_file())
        self.assertTrue(
            (
                backup
                / "quarentena"
                / "comprovantes"
                / self.comprovante.name
            ).is_file()
        )
        self.assertFalse(self.comprovante.exists())
        self.assertTrue(self.logo.exists())
        self.assertTrue(self.desconhecido.exists())

        with closing(sqlite3.connect(self.banco)) as conexao:
            conexao.row_factory = sqlite3.Row
            administrador = conexao.execute(
                "SELECT id, nome, usuario, senha, perfil, ativo "
                "FROM usuario_sistema"
            ).fetchall()
            self.assertEqual(len(administrador), 1)
            self.assertEqual(administrador[0]["id"], 1)
            self.assertEqual(administrador[0]["usuario"], "admin")
            self.assertEqual(
                administrador[0]["senha"],
                "hash-administrador-preservado",
            )
            self.assertTrue(administrador[0]["ativo"])
            configuracao = conexao.execute(
                "SELECT id, nome_exibicao, razao_social, logo "
                "FROM configuracao_transportadora"
            ).fetchall()
            self.assertEqual(len(configuracao), 1)
            self.assertEqual(configuracao[0]["id"], 1)
            self.assertEqual(configuracao[0]["logo"], self.logo.name)

            for tabela in reset_demo_local.TABELAS_LIMPEZA:
                quantidade = conexao.execute(
                    f'SELECT COUNT(*) FROM "{tabela}"'
                ).fetchone()[0]
                self.assertEqual(quantidade, 0, tabela)

            self.assertEqual(
                conexao.execute("PRAGMA foreign_key_check").fetchall(),
                [],
            )

        with closing(sqlite3.connect(backup / "database.db")) as copia:
            self.assertEqual(
                copia.execute(
                    "SELECT COUNT(*) FROM usuario_sistema"
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                copia.execute(
                    "SELECT COUNT(*) FROM rastreamento"
                ).fetchone()[0],
                1,
            )

    def test_backup_termina_antes_de_quarentena_e_primeiro_delete(self):
        eventos = []

        reset_demo_local.executar_reset(
            self.contexto,
            reset_demo_local.CONFIRMACAO_EXATA,
            evento=eventos.append,
        )

        self.assertEqual(eventos[0], "backup:concluido")
        self.assertEqual(eventos[1], "quarentena:concluida")
        self.assertTrue(eventos[2].startswith("delete:"))

    def test_falha_de_backup_impede_reset_e_movimentacao(self):
        dump_antes = self._dump_banco()
        arquivos_antes = self._snapshot_arquivos()

        with patch.object(
            reset_demo_local,
            "criar_backup_local",
            side_effect=OSError("falha de backup simulada"),
        ):
            with self.assertRaises(reset_demo_local.ResetDemoErro):
                reset_demo_local.executar_reset(
                    self.contexto,
                    reset_demo_local.CONFIRMACAO_EXATA,
                )

        self.assertEqual(self._dump_banco(), dump_antes)
        self.assertEqual(self._snapshot_arquivos(), arquivos_antes)

    def test_rollback_restaura_banco_e_comprovante(self):
        dump_antes = self._dump_banco()
        arquivos_antes = self._snapshot_arquivos()

        with self.assertRaises(reset_demo_local.ResetDemoErro):
            reset_demo_local.executar_reset(
                self.contexto,
                reset_demo_local.CONFIRMACAO_EXATA,
                falhar_apos_tabela="viagem",
            )

        self.assertEqual(self._dump_banco(), dump_antes)
        self.assertEqual(self._snapshot_arquivos(), arquivos_antes)
        self.assertTrue(self.logo.exists())
        self.assertTrue(self.comprovante.exists())

        with closing(sqlite3.connect(self.banco)) as conexao:
            self.assertEqual(
                conexao.execute("PRAGMA foreign_key_check").fetchall(),
                [],
            )

    def test_inventario_do_backup_nao_contem_hash_administrativo(self):
        resultado = reset_demo_local.executar_reset(
            self.contexto,
            reset_demo_local.CONFIRMACAO_EXATA,
        )
        inventario = json.loads(
            (Path(resultado["backup"]) / "inventario.json").read_text(
                encoding="utf-8"
            )
        )
        serializado = json.dumps(inventario, ensure_ascii=False)

        self.assertNotIn("hash-administrador-preservado", serializado)
        self.assertNotIn('"senha"', serializado)


if __name__ == "__main__":
    unittest.main()
