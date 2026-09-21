import os
import subprocess
import sys
import unittest
from threading import Lock
from pathlib import Path

from services.rate_limit import (
    RateLimiterMemoria,
    RateLimiterRedis,
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

            for indice, chave in enumerate(chaves):
                limite = int(argumentos[indice * 2])
                janela = int(argumentos[indice * 2 + 1])
                atual = self.valores.get(chave, 0)

                if atual >= limite:
                    expiracao = self.expiracoes.get(
                        chave,
                        self.relogio.agora + janela,
                    )
                    return max(1, int(expiracao - self.relogio.agora))

            for indice, chave in enumerate(chaves):
                janela = int(argumentos[indice * 2 + 1])
                atual = self.valores.get(chave, 0) + 1
                self.valores[chave] = atual

                if atual == 1:
                    self.expiracoes[chave] = (
                        self.relogio.agora + janela
                    )

        return 0


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
