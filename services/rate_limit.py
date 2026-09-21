from collections import defaultdict, deque
from ipaddress import ip_address
import os
from threading import Lock
from time import monotonic

from flask import jsonify

MENSAGEM_RATE_LIMIT = (
    "Muitas tentativas. Aguarde antes de tentar novamente."
)

NAMESPACE_RATE_LIMIT = "transportadora:rate-limit"
AMBIENTES_RAILWAY_CONFIAVEIS = {"staging", "production"}
HEADER_IP_REAL_RAILWAY = "X-Real-IP"

SCRIPT_RATE_LIMIT_ATOMICO = """
local contadores = {}
local ttls = {}
local bloqueado = 0
local primeira_regra_bloqueada = 0

for indice, chave in ipairs(KEYS) do
    local posicao = (indice - 1) * 2
    local limite = tonumber(ARGV[posicao + 1])
    local atual = tonumber(redis.call('GET', chave) or '0')
    local ttl = redis.call('TTL', chave)

    contadores[indice] = atual
    ttls[indice] = ttl

    if atual >= limite then
        bloqueado = 1
        if primeira_regra_bloqueada == 0 then
            primeira_regra_bloqueada = indice
        end
    end
end

if bloqueado == 0 then
    for indice, chave in ipairs(KEYS) do
        local posicao = (indice - 1) * 2
        local janela = tonumber(ARGV[posicao + 2])
        local atual = redis.call('INCR', chave)

        if atual == 1 then
            redis.call('EXPIRE', chave, janela)
        end
    end

    return {0, 0}
end

local retry_after = 1

for indice, chave in ipairs(KEYS) do
    local posicao = (indice - 1) * 2
    local limite = tonumber(ARGV[posicao + 1])
    local janela = tonumber(ARGV[posicao + 2])

    if contadores[indice] >= limite then
        local ttl = ttls[indice]

        if ttl < 1 then
            redis.call('EXPIRE', chave, janela)
            ttl = janela
        end

        if indice == primeira_regra_bloqueada then
            retry_after = ttl
        end
    end
end

return {1, retry_after}
"""


def _validar_regras(regras):
    regras_validadas = []

    for chave, limite, janela in regras:
        chave = str(chave).strip()
        limite = int(limite)
        janela = int(janela)

        if not chave:
            raise ValueError("A chave do rate limit não pode ser vazia.")

        if limite < 1 or janela < 1:
            raise ValueError(
                "Limite e janela do rate limit devem ser positivos."
            )

        regras_validadas.append((chave, limite, janela))

    return regras_validadas


class RateLimiterMemoria:
    def __init__(self):
        self._janelas = defaultdict(deque)
        self._duracoes = {}
        self._operacoes_desde_limpeza = 0
        self._lock = Lock()

    def verificar(self, regras):
        regras = _validar_regras(regras)
        agora = monotonic()

        with self._lock:
            self._operacoes_desde_limpeza += 1
            if self._operacoes_desde_limpeza >= 100:
                self._limpar_expiradas_locked(agora)
                self._operacoes_desde_limpeza = 0

            registros_por_chave = []
            retry_after = None

            for chave, limite, janela in regras:
                self._duracoes[chave] = janela
                registros = self._janelas[chave]
                limite_inferior = agora - janela

                while registros and registros[0] <= limite_inferior:
                    registros.popleft()

                registros_por_chave.append(registros)

                if len(registros) >= limite:
                    if retry_after is None:
                        retry_after = max(
                            1,
                            int(registros[0] + janela - agora + 0.999)
                        )

            if retry_after is not None:
                return retry_after

            for registros in registros_por_chave:
                registros.append(agora)

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


class RateLimiterRedis:
    def __init__(
        self,
        cliente,
        namespace=NAMESPACE_RATE_LIMIT,
    ):
        self._cliente = cliente
        self._namespace = namespace.strip(":")

    def verificar(self, regras):
        regras = _validar_regras(regras)

        if not regras:
            return None

        chaves = [
            f"{self._namespace}:{chave}"
            for chave, _limite, _janela in regras
        ]
        argumentos = []

        for _chave, limite, janela in regras:
            argumentos.extend((limite, janela))

        try:
            resultado = self._cliente.eval(
                SCRIPT_RATE_LIMIT_ATOMICO,
                len(chaves),
                *chaves,
                *argumentos,
            )
            if not isinstance(resultado, (list, tuple)):
                raise ValueError("Resposta inesperada do script de rate limit.")

            if len(resultado) != 2:
                raise ValueError("Resposta incompleta do rate limit.")

            bloqueado = bool(int(resultado[0]))
            retry_after = int(resultado[1])
        except Exception:
            # Não inclui REDIS_URL nem detalhes de conexão na exceção.
            raise RuntimeError(
                "Backend compartilhado de rate limiting indisponível."
            ) from None

        if not bloqueado:
            return None

        return max(1, retry_after)


def criar_limiter(
    redis_url="",
    redis_obrigatorio=False,
    cliente_redis=None,
):
    redis_url = str(redis_url or "").strip()

    if cliente_redis is not None or redis_url:
        if cliente_redis is None:
            from redis import Redis

            cliente_redis = Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )

        try:
            cliente_redis.ping()
        except Exception:
            raise RuntimeError(
                "Não foi possível conectar ao Redis de rate limiting."
            ) from None

        return RateLimiterRedis(cliente_redis)

    if redis_obrigatorio:
        raise RuntimeError(
            "REDIS_URL é obrigatória em staging e produção."
        )

    return RateLimiterMemoria()


limiter = RateLimiterMemoria()


def configurar_limiter(
    redis_url="",
    redis_obrigatorio=False,
    cliente_redis=None,
):
    global limiter

    limiter = criar_limiter(
        redis_url=redis_url,
        redis_obrigatorio=redis_obrigatorio,
        cliente_redis=cliente_redis,
    )

    return limiter


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


def _executando_em_ambiente_railway_confiavel():
    ambiente_railway = os.environ.get(
        "RAILWAY_ENVIRONMENT_NAME",
        "",
    ).strip()
    ambiente_aplicacao = os.environ.get(
        "APP_ENV",
        ambiente_railway or "development",
    ).strip().lower()

    return bool(
        ambiente_railway
        and ambiente_aplicacao in AMBIENTES_RAILWAY_CONFIAVEIS
    )


def _ip_real_railway_validado(request):
    if not _executando_em_ambiente_railway_confiavel():
        return None

    valor = request.headers.get(HEADER_IP_REAL_RAILWAY)
    if (
        not isinstance(valor, str)
        or not valor
        or valor != valor.strip()
        or "%" in valor
    ):
        return None

    try:
        return str(ip_address(valor))
    except ValueError:
        return None


def chave_ip(request, nome):
    endereco = (
        _ip_real_railway_validado(request)
        or request.remote_addr
        or "unknown"
    )
    return f"{nome}:ip:{endereco}"
