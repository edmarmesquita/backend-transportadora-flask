from datetime import datetime, timezone
from zoneinfo import ZoneInfo


UTC = timezone.utc
FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")



def analisar_data_operacional_local(valor):
    """Parse datetime-local como horario Sao Paulo sem deslocamento UTC."""
    if valor in (None, ""):
        return None
    if not isinstance(valor, str):
        raise TypeError("valor deve ser uma string ISO local ou None")
    data = datetime.fromisoformat(valor)
    if data.tzinfo is not None and data.utcoffset() is not None:
        return data.astimezone(FUSO_BRASILIA).replace(tzinfo=None)
    return data


def formatar_data_operacional_local(data):
    """Formatar data planejada para datetime-local sem conversao UTC."""
    if data is None:
        return ""
    if not isinstance(data, datetime):
        raise TypeError("data deve ser um datetime ou None")
    if data.tzinfo is not None and data.utcoffset() is not None:
        data = data.astimezone(FUSO_BRASILIA).replace(tzinfo=None)
    return data.strftime("%Y-%m-%dT%H:%M")


def exibir_data_operacional_local(data):
    """Exibir data planejada como horario local operacional."""
    if data is None:
        return ""
    if not isinstance(data, datetime):
        raise TypeError("data deve ser um datetime ou None")
    if data.tzinfo is not None and data.utcoffset() is not None:
        data = data.astimezone(FUSO_BRASILIA).replace(tzinfo=None)
    return data.strftime("%d/%m/%Y %H:%M")


def instante_atual_utc():
    """Retorna o instante atual como datetime aware em UTC."""
    return datetime.now(UTC)


def serializar_instante_utc(data):
    """Serializa um instante como ISO 8601 UTC com sufixo Z.

    Datetimes naive são interpretados como UTC, conforme a convenção legada
    do ROTANZA. Datetimes aware são convertidos para UTC antes da serialização.
    None permanece None para campos opcionais.
    """
    if data is None:
        return None

    if not isinstance(data, datetime):
        raise TypeError("data deve ser um datetime ou None")

    if data.tzinfo is None or data.utcoffset() is None:
        data_utc = data.replace(tzinfo=UTC)
    else:
        data_utc = data.astimezone(UTC)

    return data_utc.isoformat().replace("+00:00", "Z")


def formatar_instante_utc_brasilia(data):
    """Formata instante UTC em horário de São Paulo para saída legada.

    Valores naive seguem a convenção legada UTC. O resultado não inclui
    indicação de timezone, pois mantém o formato atual dd/mm/aaaa HH:MM.
    """
    if data is None:
        return ""

    if not isinstance(data, datetime):
        raise TypeError("data deve ser um datetime ou None")

    if data.tzinfo is None or data.utcoffset() is None:
        data_utc = data.replace(tzinfo=UTC)
    else:
        data_utc = data.astimezone(UTC)

    return data_utc.astimezone(FUSO_BRASILIA).strftime("%d/%m/%Y %H:%M")


def formatar_data_brasilia(data):
    """Compatibilidade: mantém formato e interpretação UTC legados."""
    return formatar_instante_utc_brasilia(data) if data else ""
