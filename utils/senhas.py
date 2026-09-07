from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)


PREFIXOS_HASH_SUPORTADOS = (
    "scrypt:",
    "pbkdf2:",
)


def gerar_hash_senha(senha):
    return generate_password_hash(senha)


def senha_esta_em_hash(valor_armazenado):
    if not isinstance(valor_armazenado, str):
        return False

    return valor_armazenado.startswith(
        PREFIXOS_HASH_SUPORTADOS
    )


def verificar_senha(valor_armazenado, senha_informada):
    if not isinstance(valor_armazenado, str):
        return False

    if not isinstance(senha_informada, str):
        return False

    if senha_esta_em_hash(valor_armazenado):
        try:
            return check_password_hash(
                valor_armazenado,
                senha_informada,
            )
        except (TypeError, ValueError):
            return False

    return False
