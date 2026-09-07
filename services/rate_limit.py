from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from flask import jsonify


MENSAGEM_RATE_LIMIT = (
    "Muitas tentativas. Aguarde antes de tentar novamente."
)


class RateLimiterMemoria:
    def __init__(self):
        self._janelas = defaultdict(deque)
        self._duracoes = {}
        self._operacoes_desde_limpeza = 0
        self._lock = Lock()

    def verificar(self, regras):
        agora = monotonic()

        with self._lock:
            self._operacoes_desde_limpeza += 1
            if self._operacoes_desde_limpeza >= 100:
                self._limpar_expiradas_locked(agora)
                self._operacoes_desde_limpeza = 0

            for chave, limite, janela in regras:
                self._duracoes[chave] = janela
                registros = self._janelas[chave]
                limite_inferior = agora - janela

                while registros and registros[0] <= limite_inferior:
                    registros.popleft()

                if len(registros) >= limite:
                    retry_after = max(
                        1,
                        int(registros[0] + janela - agora + 0.999)
                    )
                    return retry_after

            for chave, _limite, _janela in regras:
                self._janelas[chave].append(agora)

        return None

    def _limpar_expiradas_locked(self, agora):
        for chave, registros in list(self._janelas.items()):
            janela = self._duracoes.get(chave)
            if janela is None:
                continue

            limite_inferior = agora - janela
            while registros and registros[0] <= limite_inferior:
                registros.popleft()

            if not registros:
                del self._janelas[chave]
                self._duracoes.pop(chave, None)

    def limpar_expiradas(self, agora=None):
        if agora is None:
            agora = monotonic()

        with self._lock:
            self._limpar_expiradas_locked(agora)

    def limpar(self):
        with self._lock:
            self._janelas.clear()
            self._duracoes.clear()
            self._operacoes_desde_limpeza = 0


limiter = RateLimiterMemoria()


def resposta_rate_limit(retry_after):
    resposta = jsonify({"erro": MENSAGEM_RATE_LIMIT})
    resposta.status_code = 429
    resposta.headers["Retry-After"] = str(retry_after)
    return resposta


def verificar_limite(regras):
    retry_after = limiter.verificar(regras)
    if retry_after is None:
        return None

    return resposta_rate_limit(retry_after)


def chave_ip(request, nome):
    return f"{nome}:ip:{request.remote_addr or 'unknown'}"