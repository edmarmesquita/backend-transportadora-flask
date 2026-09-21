from collections import defaultdict, deque
import hashlib
from ipaddress import ip_address
import logging
import os
from threading import Lock
from time import monotonic

from flask import jsonify


logger = logging.getLogger(__name__)

MENSAGEM_RATE_LIMIT = (
    "Muitas tentativas. Aguarde antes de tentar novamente."
)

NAMESPACE_RATE_LIMIT = "transportadora:rate-limit"
AMBIENTES_RAILWAY_CONFIAVEIS = {"staging", "production"}
HEADER_IP_REAL_RAILWAY = "X-Real-IP"

SCRIPT_RATE_LIMIT_ATOMICO = """
local antes = {}
local ttl_antes = {}
local bloqueado = 0

for indice, chave in ipairs(KEYS) do
    local posicao = (indice - 1) * 2
    local limite = tonumber(ARGV[posicao + 1])
    local janela = tonumber(ARGV[posicao + 2])
    local atual = tonumber(redis.call('GET', chave) or '0')
    local ttl = redis.call('TTL', chave)

    antes[indice] = atual
    ttl_antes[indice] = ttl

    if atual >= limite then
        bloqueado = 1
    end
end

local resultado = {bloqueado}

for indice, chave in ipairs(KEYS) do
    local posicao = (indice - 1) * 2
    local limite = tonumber(ARGV[posicao + 1])
    local janela = tonumber(ARGV[posicao + 2])
    local atual = antes[indice]
    local depois = atual
    local ttl = ttl_antes[indice]

    if bloqueado == 0 then
        depois = redis.call('INCR', chave)

        if depois == 1 then
            redis.call('EXPIRE', chave, janela)
        end

        ttl = redis.call('TTL', chave)
    elseif atual >= limite and ttl < 1 then
        redis.call('EXPIRE', chave, janela)
        ttl = janela
    end

    table.insert(resultado, atual)
    table.insert(resultado, depois)
    table.insert(resultado, ttl)
end

return resultado
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


def _nome_limite(chave):
    prefixo = str(chave).split(":", 1)[0].strip().lower()
    nomes = {
        "rastreamento": "tracking",
        "cotacao": "quotes",
        "cotacao-hora": "quotes",
    }
    return nomes.get(prefixo, prefixo or "desconhecido")


def _hash_chave(chave):
    digest = hashlib.sha256(str(chave).encode("utf-8")).hexdigest()
    return digest[:12]


def _registrar_diagnostico(
    habilitado,
    backend,
    chave,
    contador_antes,
    contador_depois,
    ttl,
    permitido,
):
    if not habilitado:
        return

    logger.info(
        "rate_limit_diag backend=%s limite=%s chave_hash=%s "
        "contador_antes=%d contador_depois=%d ttl=%d permitido=%s",
        backend,
        _nome_limite(chave),
        _hash_chave(chave),
        int(contador_antes),
        int(contador_depois),
        int(ttl),
        str(bool(permitido)).lower(),
    )


class RateLimiterMemoria:
    def __init__(self, instrumentar=False, ambiente="development"):
        self._janelas = defaultdict(deque)
        self._duracoes = {}
        self._operacoes_desde_limpeza = 0
        self._lock = Lock()
        self._instrumentar = bool(
            instrumentar and ambiente.strip().lower() == "staging"
        )

    def verificar(self, regras):
        regras = _validar_regras(regras)
        agora = monotonic()

        with self._lock:
            self._operacoes_desde_limpeza += 1
            if self._operacoes_desde_limpeza >= 100:
                self._limpar_expiradas_locked(agora)
                self._operacoes_desde_limpeza = 0

            situacoes = []
            bloqueado = False

            for chave, limite, janela in regras:
                self._duracoes[chave] = janela
                registros = self._janelas[chave]
                limite_inferior = agora - janela

                while registros and registros[0] <= limite_inferior:
                    registros.popleft()

                contador_antes = len(registros)
                ttl = janela
                if registros:
                    ttl = max(
                        1,
                        int(registros[0] + janela - agora + 0.999)
                    )

                situacoes.append((
                    chave,
                    contador_antes,
                    janela,
                    ttl,
                    limite,
                ))

                if contador_antes >= limite:
                    if not bloqueado:
                        retry_after = max(
                            1,
                            int(registros[0] + janela - agora + 0.999)
                        )
                    bloqueado = True

            if bloqueado:
                for chave, antes, _janela, ttl, _limite in situacoes:
                    _registrar_diagnostico(
                        self._instrumentar,
                        "memory",
                        chave,
                        antes,
                        antes,
                        ttl,
                        False,
                    )
                return retry_after

            for chave, _antes, _janela, _ttl, _limite in situacoes:
                self._janelas[chave].append(agora)

            for chave, antes, janela, _ttl, _limite in situacoes:
                ttl = max(
                    1,
                    int(self._janelas[chave][0] + janela - agora + 0.999)
                )
                _registrar_diagnostico(
                    self._instrumentar,
                    "memory",
                    chave,
                    antes,
                    antes + 1,
                    ttl,
                    True,
                )

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
        instrumentar=False,
        ambiente="development",
    ):
        self._cliente = cliente
        self._namespace = namespace.strip(":")
        self._instrumentar = bool(
            instrumentar and ambiente.strip().lower() == "staging"
        )

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

            esperado = 1 + (3 * len(regras))
            if len(resultado) != esperado:
                raise ValueError("Metadados incompletos do rate limit.")

            bloqueado = bool(int(resultado[0]))
            metadados = []
            for indice in range(len(regras)):
                posicao = 1 + (indice * 3)
                metadados.append((
                    int(resultado[posicao]),
                    int(resultado[posicao + 1]),
                    int(resultado[posicao + 2]),
                ))
        except Exception:
            # Não inclui REDIS_URL nem detalhes de conexão na exceção.
            raise RuntimeError(
                "Backend compartilhado de rate limiting indisponível."
            ) from None

        for (chave, _limite, _janela), (antes, depois, ttl) in zip(
            regras,
            metadados,
        ):
            _registrar_diagnostico(
                self._instrumentar,
                "redis",
                chave,
                antes,
                depois,
                ttl,
                not bloqueado,
            )

        if not bloqueado:
            return None

        for (_chave, limite, _janela), (antes, _depois, ttl) in zip(
            regras,
            metadados,
        ):
            if antes >= limite:
                return max(1, ttl)

        return 1


def criar_limiter(
    redis_url="",
    redis_obrigatorio=False,
    cliente_redis=None,
    instrumentar=False,
    ambiente="development",
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

        return RateLimiterRedis(
            cliente_redis,
            instrumentar=instrumentar,
            ambiente=ambiente,
        )

    if redis_obrigatorio:
        raise RuntimeError(
            "REDIS_URL é obrigatória em staging e produção."
        )

    return RateLimiterMemoria(
        instrumentar=instrumentar,
        ambiente=ambiente,
    )


limiter = RateLimiterMemoria()


def configurar_limiter(
    redis_url="",
    redis_obrigatorio=False,
    cliente_redis=None,
    instrumentar=False,
    ambiente="development",
):
    global limiter

    limiter = criar_limiter(
        redis_url=redis_url,
        redis_obrigatorio=redis_obrigatorio,
        cliente_redis=cliente_redis,
        instrumentar=instrumentar,
        ambiente=ambiente,
    )

    if (
        instrumentar
        and str(ambiente or "").strip().lower() == "staging"
    ):
        logger.setLevel(logging.INFO)

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
