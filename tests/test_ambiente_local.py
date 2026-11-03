import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.ambiente_local import carregar_dotenv_local


class AmbienteLocalTest(unittest.TestCase):
    def criar_env(self, conteudo):
        pasta = tempfile.TemporaryDirectory()
        caminho = Path(pasta.name) / ".env"
        caminho.write_text(conteudo, encoding="utf-8")
        self.addCleanup(pasta.cleanup)
        return caminho

    def test_desenvolvimento_carrega_configuracao_do_dotenv(self):
        caminho = self.criar_env(
            "JWT_SECRET_KEY=chave-local-de-teste-com-mais-de-32-caracteres\n"
            "APP_ENV=development\n"
            "FLASK_DEBUG=true\n"
        )

        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(carregar_dotenv_local(caminho))
            self.assertEqual(
                os.environ["JWT_SECRET_KEY"],
                "chave-local-de-teste-com-mais-de-32-caracteres",
            )
            self.assertEqual(os.environ["APP_ENV"], "development")
            self.assertEqual(os.environ["FLASK_DEBUG"], "true")

    def test_variaveis_externas_tem_precedencia_sobre_dotenv(self):
        caminho = self.criar_env(
            "JWT_SECRET_KEY=chave-do-arquivo-com-mais-de-32-caracteres\n"
            "APP_ENV=development\n"
            "FLASK_DEBUG=true\n"
        )
        ambiente_externo = {
            "JWT_SECRET_KEY": "chave-externa-com-mais-de-32-caracteres-123",
            "APP_ENV": "development",
            "FLASK_DEBUG": "false",
        }

        with patch.dict(os.environ, ambiente_externo, clear=True):
            carregar_dotenv_local(caminho)
            self.assertEqual(
                os.environ["JWT_SECRET_KEY"],
                ambiente_externo["JWT_SECRET_KEY"],
            )
            self.assertEqual(os.environ["FLASK_DEBUG"], "false")

    def test_ambiente_producao_nao_carrega_valores_locais(self):
        caminho = self.criar_env(
            "JWT_SECRET_KEY=chave-local-de-teste-com-mais-de-32-caracteres\n"
            "APP_ENV=development\n"
            "FLASK_DEBUG=true\n"
        )

        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
            self.assertFalse(carregar_dotenv_local(caminho))
            self.assertNotIn("JWT_SECRET_KEY", os.environ)
            self.assertEqual(os.environ["APP_ENV"], "production")

    def test_railway_nao_carrega_dotenv_mesmo_sem_app_env_externo(self):
        caminho = self.criar_env(
            "JWT_SECRET_KEY=chave-local-de-teste-com-mais-de-32-caracteres\n"
            "APP_ENV=development\n"
        )

        with patch.dict(
            os.environ,
            {"RAILWAY_ENVIRONMENT_NAME": "production"},
            clear=True,
        ):
            self.assertFalse(carregar_dotenv_local(caminho))
            self.assertNotIn("JWT_SECRET_KEY", os.environ)
            self.assertNotIn("APP_ENV", os.environ)


if __name__ == "__main__":
    unittest.main()
