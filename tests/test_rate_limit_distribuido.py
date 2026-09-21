import os
import subprocess
import sys
import unittest
from pathlib import Path
from threading import Lock
from unittest.mock import patch

from flask import Flask, request

from services.rate_limit import (
    RateLimiterMemoria,
    RateLimiterRedis,
    chave_ip,
    criar_limiter,
)


class RelogioFalso:
    def __init__(self):
        self.agora = 0

    def avancar(self, segundos):
        self.agora += segundos


class BackendRedisFalso:
    def __init__(self, relogio):
        self.relogio = relogio
        self.valores = {}
        self.expiracoes = {}
        self.lock = Lock()

    def _remover_expiradas(self):
        for chave, expiracao in list(self.expiracoes.items()):
            if expiracao <= self.relogio.agora:
                self.expiracoes.pop(chave, None)
                self.valores.pop(chave, None)

    def executar(self, quantidade_chaves, valores):
        chaves = valores[:quantidade_chaves]
        argumentos = valores[quantidade_chaves:]

        with self.lock:
            self._remover_expiradas()

            estados = []
            bloqueado = False
            retry_after = None

            for indice, chave in enumerate(chaves):
                limite = int(argumentos[indice * 2])
                janela = int(argumentos[indice * 2 + 1])
                atual = self.valores.get(chave, 0)
                estados.append((chave, limite, janela, atual))

                if atual >= limite:
                    bloqueado = True

            if not bloqueado:
                for chave, _limite, janela, atual in estados:
                    atual += 1
                    self.valores[chave] = atual

                    if atual == 1:
                        self.expiracoes[chave] = (
                            self.relogio.agora + janela
                        )

                return [0, 0]

            for chave, limite, janela, atual in estados:
                if atual < limite:
                    continue

                expiracao = self.expiracoes.get(chave)
                if expiracao is None:
                    expiracao = self.relogio.agora + janela
                    self.expiracoes[chave] = expiracao

                ttl = max(1, int(expiracao - self.relogio.agora))
                if retry_after is None:
                    retry_after = ttl

        return [1, retry_after or 1]


class ClienteRedisFalso:
    def __init__(self, backend):
        self.backend = backend

    def ping(self):
        return True

    def eval(self, _script, quantidade_chaves, *valores):
        return self.backend.executar(quantidade_chaves, valores)


class ClienteRedisComFalha:
    MENSAGEM_SENSIVEL = "detalhe interno simulado da conexao Redis"

    def ping(self):
        raise ConnectionError(self.MENSAGEM_SENSIVEL)

    def eval(self, _script, _quantidade_chaves, *_valores):
        raise ConnectionError(self.MENSAGEM_SENSIVEL)


class RateLimiterDistribuidoTest(unittest.TestCase):
    def setUp(self):
        self.relogio = RelogioFalso()
        self.backend = BackendRedisFalso(self.relogio)
        self.cliente_a = ClienteRedisFalso(self.backend)
        self.cliente_b = ClienteRedisFalso(self.backend)
        self.app_requisicao = Flask(__name__)

    def _chave_ip_requisicao(
        self,
        x_real_ip=None,
        incluir_header=True,
        remote_addr="192.0.2.10",
        app_env="staging",
        railway_env="staging",
    ):
        headers = {}
        if incluir_header:
            headers["X-Real-IP"] = x_real_ip

        ambiente = {
            "APP_ENV": app_env,
            "RAILWAY_ENVIRONMENT_NAME": railway_env,
        }
        with patch.dict(os.environ, ambiente):
            with self.app_requisicao.test_request_context(
                "/",
                headers=headers,
                environ_base={"REMOTE_ADDR": remote_addr},
            ):
                return chave_ip(request, "login")

    def test_x_real_ip_valido_gera_chave_estavel(self):
        for ambiente in ("staging", "production"):
            with self.subTest(ambiente=ambiente):
                chave_a = self._chave_ip_requisicao(
                    x_real_ip="203.0.113.10",
                    remote_addr="10.0.0.1",
                    app_env=ambiente,
                    railway_env=ambiente,
                )
                chave_b = self._chave_ip_requisicao(
                    x_real_ip="203.0.113.10",
                    remote_addr="10.0.0.2",
                    app_env=ambiente,
                    railway_env=ambiente,
                )

                self.assertEqual(chave_a, chave_b)
                self.assertEqual(chave_a, "login:ip:203.0.113.10")

    def test_x_real_ips_diferentes_geram_chaves_diferentes(self):
        chave_a = self._chave_ip_requisicao(
            x_real_ip="203.0.113.10",
        )
        chave_b = self._chave_ip_requisicao(
            x_real_ip="203.0.113.11",
        )

        self.assertNotEqual(chave_a, chave_b)

    def test_x_real_ip_ausente_usa_remote_addr(self):
        chave = self._chave_ip_requisicao(
            incluir_header=False,
            remote_addr="192.0.2.20",
        )

        self.assertEqual(chave, "login:ip:192.0.2.20")

    def test_x_real_ip_invalido_usa_fallback_seguro(self):
        valores_invalidos = (
            "",
            "203.0.113.10, 198.51.100.20",
            " 203.0.113.10",
            "203.0.113.10 ",
            "203.0.113.10:443",
            "203.0.113.10 extra",
            "fe80::1%eth0",
            "texto-arbitrario",
        )

        for valor in valores_invalidos:
            with self.subTest(valor=valor):
                chave = self._chave_ip_requisicao(
                    x_real_ip=valor,
                    remote_addr="192.0.2.30",
                )
                self.assertEqual(chave, "login:ip:192.0.2.30")

    def test_x_real_ip_e_ignorado_fora_da_railway_comercial(self):
        for app_env, railway_env in (
            ("development", ""),
            ("test", ""),
            ("production", ""),
        ):
            with self.subTest(
                app_env=app_env,
                railway_env=railway_env,
            ):
                chave = self._chave_ip_requisicao(
                    x_real_ip="203.0.113.10",
                    remote_addr="192.0.2.40",
                    app_env=app_env,
                    railway_env=railway_env,
                )
                self.assertEqual(chave, "login:ip:192.0.2.40")

    def test_x_real_ip_ipv6_e_normalizado(self):
        chave = self._chave_ip_requisicao(
            x_real_ip="2001:0db8:0000:0000:0000:0000:0000:0001",
        )

        self.assertEqual(chave, "login:ip:2001:db8::1")

    def test_duas_instancias_compartilham_contador(self):
        limiter_a = RateLimiterRedis(self.cliente_a)
        limiter_b = RateLimiterRedis(self.cliente_b)
        regra = [("login:ip:203.0.113.10", 5, 60)]

        for _ in range(3):
            self.assertIsNone(limiter_a.verificar(regra))
        for _ in range(2):
            self.assertIsNone(limiter_b.verificar(regra))

        self.assertGreaterEqual(limiter_a.verificar(regra), 1)

    def test_janela_expira(self):
        limiter = RateLimiterRedis(self.cliente_a)
        regra = [("rastreamento:ip:203.0.113.10", 2, 10)]

        self.assertIsNone(limiter.verificar(regra))
        self.assertIsNone(limiter.verificar(regra))
        self.assertEqual(limiter.verificar(regra), 10)

        self.relogio.avancar(10)
        self.assertIsNone(limiter.verificar(regra))

    def test_limites_diferentes_nao_colidem(self):
        limiter = RateLimiterRedis(self.cliente_a)
        login = [("login:ip:203.0.113.10", 1, 60)]
        rastreamento = [
            ("rastreamento:ip:203.0.113.10", 1, 60)
        ]

        self.assertIsNone(limiter.verificar(login))
        self.assertGreaterEqual(limiter.verificar(login), 1)
        self.assertIsNone(limiter.verificar(rastreamento))

    def test_ips_diferentes_nao_compartilham_contador(self):
        limiter = RateLimiterRedis(self.cliente_a)
        ip_a = [("login:ip:203.0.113.10", 1, 60)]
        ip_b = [("login:ip:203.0.113.11", 1, 60)]

        self.assertIsNone(limiter.verificar(ip_a))
        self.assertGreaterEqual(limiter.verificar(ip_a), 1)
        self.assertIsNone(limiter.verificar(ip_b))

    def test_regras_compostas_sao_atomicas(self):
        limiter = RateLimiterRedis(self.cliente_a)
        minuto = ("cotacao:ip:203.0.113.10", 1, 60)
        hora = ("cotacao-hora:ip:203.0.113.10", 30, 3600)

        self.assertIsNone(limiter.verificar([minuto, hora]))
        self.assertGreaterEqual(limiter.verificar([minuto, hora]), 1)

        chave_hora = (
            "transportadora:rate-limit:"
            "cotacao-hora:ip:203.0.113.10"
        )
        self.assertEqual(self.backend.valores[chave_hora], 1)

    def test_fallback_local_e_redis_obrigatorio(self):
        limiter = criar_limiter()
        self.assertIsInstance(limiter, RateLimiterMemoria)

        with self.assertRaisesRegex(RuntimeError, "REDIS_URL"):
            criar_limiter(redis_obrigatorio=True)

        redis_limiter = criar_limiter(
            cliente_redis=self.cliente_a,
            redis_obrigatorio=True,
        )
        self.assertIsInstance(redis_limiter, RateLimiterRedis)

    def test_staging_sem_redis_url_falha_na_inicializacao(self):
        backend_dir = Path(__file__).resolve().parents[1]
        ambiente = os.environ.copy()
        ambiente.update({
            "APP_ENV": "staging",
            "REDIS_URL": "",
        })

        resultado = subprocess.run(
            [sys.executable, "-c", "import config"],
            cwd=backend_dir,
            capture_output=True,
            text=True,
            env=ambiente,
        )

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("REDIS_URL", resultado.stderr)

    def test_erros_redis_nao_expoem_detalhes_da_conexao(self):
        cliente = ClienteRedisComFalha()

        with self.assertRaises(RuntimeError) as erro_inicializacao:
            criar_limiter(
                cliente_redis=cliente,
                redis_obrigatorio=True,
            )

        self.assertNotIn(
            ClienteRedisComFalha.MENSAGEM_SENSIVEL,
            str(erro_inicializacao.exception),
        )

        limiter = RateLimiterRedis(cliente)
        with self.assertRaises(RuntimeError) as erro_execucao:
            limiter.verificar([("login:ip:203.0.113.10", 5, 60)])

        self.assertNotIn(
            ClienteRedisComFalha.MENSAGEM_SENSIVEL,
            str(erro_execucao.exception),
        )

if __name__ == "__main__":
    unittest.main(verbosity=2)
