"""Tipos e apresentação pública da timeline da carga."""

STATUS_PUBLICOS = {
    "Em preparação": ("STATUS_EM_PREPARACAO", "Sua carga está em preparação."),
    "Em coleta": ("STATUS_EM_COLETA", "Sua carga está em coleta."),
    "Carregando": ("STATUS_CARREGANDO", "Sua carga está sendo carregada."),
    "Em trânsito": ("STATUS_EM_TRANSITO", "Sua carga está em trânsito."),
    "Saiu para entrega": ("STATUS_SAIU_PARA_ENTREGA", "Sua carga saiu para entrega."),
    "Entregue": ("STATUS_ENTREGUE", "Sua carga foi entregue."),
}

TEXTOS_PUBLICOS = {tipo: texto for tipo, texto in STATUS_PUBLICOS.values()}
TIPOS_PUBLICOS = frozenset(TEXTOS_PUBLICOS)


def tipo_status_comercial(status):
    """Usar somente em fluxos que produzem uma mudança comercial de status."""
    return STATUS_PUBLICOS.get(status, ("INTERNO", None))[0]
