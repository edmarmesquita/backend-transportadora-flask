import secrets

from models.operacao import Rastreamento


ALFABETO_CODIGO_RASTREAMENTO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
QUANTIDADE_CARACTERES_ALEATORIOS = 10


def gerar_codigo_rastreamento():
    for _tentativa in range(20):
        sufixo = "".join(
            secrets.choice(ALFABETO_CODIGO_RASTREAMENTO)
            for _ in range(QUANTIDADE_CARACTERES_ALEATORIOS)
        )
        codigo = f"TRK-{sufixo}"

        if not Rastreamento.query.filter_by(codigo=codigo).first():
            return codigo

    raise RuntimeError("Não foi possível gerar um código de rastreamento único.")
